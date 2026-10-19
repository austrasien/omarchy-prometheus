import unittest

from prometheus import achievements as A
from prometheus import timeutil as T
from prometheus.core import Core, Refused
from prometheus.store import Store

MIN = 60_000
DAY = 24 * 60 * MIN


class UsageAchievementTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        self.t0 = T.day_start(T.now_ms()) - 60 * DAY + 10 * 60 * MIN

    def unlocked(self, at):
        self.core.check_achievements(at)
        return set(self.store.unlocked_achievements())

    def test_rarity_is_set_by_hand_and_xp_follows(self):
        fam = {f.id: f for f in A.FAMILIES}
        self.assertEqual(fam["poweruser"].rarity(0), "epic")
        self.assertEqual(fam["poweruser"].xp(0), 80)
        self.assertEqual([fam["presskit"].rarity(i) for i in range(3)], ["common", "rare", "epic"])

    def test_share_settings_tabs_and_board(self):
        c, at = self.core, self.t0
        c.share(at)
        c.set_handle("x")
        c.set_day_start(6, at)
        c.set_presence_every(25)
        c.goal_set({"hours": 4, "period": "day"})
        c.set_hidden_apps(["Steam"], at)
        c.set_hidden_words(["bank"], at)
        c.set_aliases({"foot": "Terminal"}, at)
        c.set_share_format("apng")
        for t in A.TABS:
            c.ui_event(f"tab:{t}")
        c.ui_event("tab:stats")                       # once per tab
        self.assertEqual(self.store.count_events("tab:stats"), 1)
        with self.assertRaises(Refused):
            c.ui_event("tab:nope")
        q = c.quest_add("Done one", "short", at)["quest"]["id"]
        c.quest_complete(q, at)
        c.leaderboard_remove_quest(q, at)
        got = self.unlocked(at + MIN)
        for aid in ("presskit:1", "callsign", "timezone", "pacemaker", "goalsetter", "invisible",
                    "redacted", "rebrand", "formatwar", "poweruser", "grandtour", "revisionist"):
            self.assertIn(aid, got)

    def test_hall_of_fame_waits_thirty_days(self):
        c = self.core
        for d in range(12):                            # twelve growing days, the first month
            c.start(None, self.t0 + d * DAY)
            c.end(self.t0 + d * DAY + (60 + d) * MIN)
        self.assertNotIn("halloffame:1", self.unlocked(self.t0 + 13 * DAY))
        c.start(None, self.t0 + 31 * DAY)
        c.end(self.t0 + 31 * DAY + 200 * MIN)          # a big day, after the warm-up
        self.assertIn("halloffame:1", self.unlocked(self.t0 + 32 * DAY))


if __name__ == "__main__":
    unittest.main()
