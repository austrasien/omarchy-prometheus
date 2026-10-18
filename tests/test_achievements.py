import unittest

from prometheus import achievements as A
from prometheus import timeutil as T
from prometheus.core import Core, Window
from prometheus.store import Store

MIN = 60_000
H = 60 * MIN
DAY = 24 * H


class AchievementsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.battery = False
        self.weather = (None, None)
        self.pct = 50.0
        self.core.on_battery = lambda: self.battery
        self.core.battery_percent = lambda: self.pct
        self.core.weather_now = lambda at: self.weather
        # A Wednesday at 10:00 local, so weekdays and clocks are predictable.
        base = T.day_start(T.now_ms())
        while T._logical_date(base).weekday() != 2:
            base = T.add_days(base, -1)
        self.t0 = base + 5 * H            # day start is 5:00, so this is 10:00

    def tearDown(self):
        T.set_day_start_hour(T.DEFAULT_DAY_START_HOUR)

    def session(self, start, minutes, task="x", **kw):
        self.core.start(task, start)
        self.core.end(start + minutes * MIN, **kw)

    def unlocked(self):
        return set(self.store.unlocked_achievements())

    def check(self, at):
        return self.core.check_achievements(at)

    def test_sessions_and_short_ones_do_not_count(self):
        for i in range(10):
            self.session(self.t0 + i * 2 * H, 15)
        self.session(self.t0 + 30 * H, 5)          # under 10 min: ignored
        new = self.check(self.t0 + 40 * H)
        self.assertIn("sessions:10", {a["id"] for a in new})
        self.assertNotIn("sessions:20", self.unlocked())

    def test_endurance_live_and_monk_secret(self):
        self.core.start("long", self.t0)
        self.check(self.t0 + 2 * H)                       # open session counts live
        self.assertIn("endurance:7200", self.unlocked())
        self.core.end(self.t0 + 4 * H + MIN)
        self.check(self.t0 + 5 * H)
        self.assertIn("monk", self.unlocked())            # 4 h, no pause

    def test_streaks_and_night_and_morning(self):
        for d in range(5):
            day = T.add_days(T.day_start(self.t0), d)
            self.session(day + 15 * H + 30 * MIN, 20)     # 20:30 to 20:50
        self.session(T.add_days(T.day_start(self.t0), 5) + 1 * H + 30 * MIN, 20)   # 6:30
        self.check(self.t0 + 10 * DAY)
        got = self.unlocked()
        self.assertIn("streak:5", got)
        self.assertIn("night:20", got)                     # ended after 20:00
        self.assertNotIn("night:21", got)
        self.assertIn("morning:7", got)                    # started before 7:00
        self.assertNotIn("morning:6", got)

    def test_weather_and_battery(self):
        self.weather = ("rain", 12.0)
        self.battery = True
        self.session(self.t0, 15)
        self.weather = (None, 33.0)
        self.session(self.t0 + H, 15)
        self.check(self.t0 + 2 * H)
        got = self.unlocked()
        self.assertIn("rain:1", got)
        self.assertIn("heat:1", got)
        self.assertNotIn("battery:10", got)

    def test_level_achievements_feed_back(self):
        # Focus XP alone reaches level 5; the loop must settle and grant it.
        self.session(self.t0, 110 * 60)                   # 110 h in one go: 660 XP
        self.check(self.t0 + 120 * H)
        self.assertIn("levels:5", self.unlocked())
        self.assertGreater(self.core.profile(self.t0 + 120 * H)["achievementXp"], 0)

    def test_catalogue_hides_secrets(self):
        cat = self.core.achievements_list(self.t0)
        monk = next(f for f in cat["families"] if f["id"] == "monk")
        self.assertEqual(monk["title"], "???")
        self.assertEqual(monk["tiers"][0]["name"], "???")
        self.assertEqual(cat["unlocked"], 0)
        self.assertEqual(cat["total"], sum(len(f.thresholds) for f in A.FAMILIES))

    def test_xp_rules(self):
        fam = next(f for f in A.FAMILIES if f.id == "cumul")          # weight x3
        self.assertEqual([fam.xp(i) for i in (0, 1, 9, 10, 99)], [15, 30, 150, 156, 690])
        tasks = next(f for f in A.FAMILIES if f.id == "tasks")        # weight x1
        self.assertEqual([tasks.xp(i) for i in (0, 9)], [5, 50])
        self.assertEqual(next(f for f in A.FAMILIES if f.id == "newyear").xp(0), 25)   # secret
        self.assertEqual(next(f for f in A.FAMILIES if f.id == "y2k38").xp(0), 25)

    def test_old_unlocks_follow_new_rules(self):
        self.store.unlock("sessions:10", self.t0, 999)               # stale reward
        self.check(self.t0)
        self.assertEqual(self.store.unlocked_achievements()["sessions:10"]["xp"], 5)

    def test_comeback_tiers_and_calendar_years(self):
        self.session(self.t0, 15)
        self.session(self.t0 + 31 * DAY, 15)                          # back after 31 days
        self.check(self.t0 + 32 * DAY)
        got = self.unlocked()
        self.assertIn("comeback:30", got)
        self.assertNotIn("comeback:60", got)

    def test_task_families(self):
        c = self.core
        c.start("Ship it", self.t0)
        a = c.task_add("Ship it", "manual", self.t0)["task"]
        c.end(self.t0 + 20 * MIN, reason="procrastinated")       # put off once
        c.start("again", self.t0 + H)
        c.task_complete(a["id"], self.t0 + H + MIN)              # same day, list now empty
        c.end(self.t0 + H + 20 * MIN)
        self.check(self.t0 + 2 * H)
        got = self.unlocked()
        self.assertIn("inboxzero:1", got)
        self.assertIn("redemption:1", got)
        self.assertNotIn("sameday:5", got)

    def test_reflex_fumes_and_midnight(self):
        c = self.core
        midnight = T.add_days(T.day_start(self.t0), 1) - 5 * H     # next calendar midnight
        self.battery, self.pct = True, 7.0
        c.start("late", midnight - 30 * MIN)
        c.presence_asked_at = midnight - 20 * MIN
        c.presence_confirm(midnight - 20 * MIN + 4000)            # answered in 4 s
        c.end(midnight + 15 * MIN)
        self.check(midnight + H)
        got = self.unlocked()
        self.assertIn("reflexes:1", got)
        self.assertIn("fumes:1", got)
        self.assertIn("midnight:1", got)

    def test_secret_holidays(self):
        cat = {f["id"]: f for f in self.core.achievements_list(self.t0)["families"]}
        for fid in ("christmas", "orthodox", "newyear", "bookends", "midnight"):
            self.assertEqual(cat[fid]["title"], "???")

    def test_moon(self):
        full = 947182440000 + int(14.77 * DAY)          # 2000-01-06 new moon + 14.77 days
        self.assertLess(abs(A.moon_age(full) - 14.77), 0.01)


if __name__ == "__main__":
    unittest.main()
