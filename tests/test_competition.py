import random
import unittest

from prometheus import competition as C
from prometheus import medals as M
from prometheus import timeutil as T
from prometheus.core import Core
from prometheus.store import Store

MIN = 60_000


class CompetitionTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        # A Monday, 10:00, a few weeks back, so every week is complete.
        today = T.day_start(T.now_ms())
        self.monday = T.add_days(T.week_start(today), -7 * 12)

    def at(self, day, minutes=0):
        return T.add_days(self.monday, day) + 10 * 60 * MIN + minutes * MIN

    def work(self, day, minutes):
        """A session of `minutes` focus on `day` (minutes // 10 XP)."""
        self.core.start(None, self.at(day))
        self.core.end(self.at(day, minutes))

    def test_rivals_are_seeded_and_gaussian(self):
        w = C._monday(C._date(T.date_str(self.at(0))))
        a = C._rivals(w, 3, [100, 120, 80, 100], 1.0)
        self.assertEqual(a, C._rivals(w, 3, [100, 120, 80, 100], 1.0))
        self.assertEqual(len(a), 9)
        mean = sum(r["final"] for r in a) / 9
        self.assertTrue(550 < mean < 1000)               # the Sapphire floor, 87 % of 870 a round
        half = C._rivals(w, 3, [100, 120, 80, 100], 0.5)
        self.assertTrue(all(h["xp"] <= r["xp"] for h, r in zip(half, a)))

    def test_standings_zones(self):
        rivals = [{"name": str(i), "xp": 10 * i, "final": 10 * i} for i in range(1, 10)]
        self.assertEqual(C._standings(1000, rivals, 4)[1:], (1, "promotion"))
        self.assertEqual(C._standings(55, rivals, 4)[1:], (5, "stagnation"))
        self.assertEqual(C._standings(15, rivals, 4)[1:], (9, "relegation"))
        self.assertEqual(C._standings(0, [dict(r, xp=0) for r in rivals], 4)[2], "relegation")

    def test_top_three_below_the_minimum_is_no_promotion(self):
        rivals = [{"name": str(i), "xp": i, "final": i} for i in range(1, 10)]
        self.assertEqual(C._standings(599, rivals, 0)[1:], (1, "stagnation"))     # Bronze: 600 a round
        self.assertEqual(C._standings(600, rivals, 0)[1:], (1, "promotion"))
        self.assertEqual(C._standings(679, rivals, 1)[2], "stagnation")            # Silver: 680
        self.assertEqual(C._standings(300, rivals, 0, progress=0.5)[2], "promotion")   # prorated mid-round
        self.assertEqual(C.PROMOTION_MIN_WEEKLY[8], 2 * C.PROMOTION_MIN_WEEKLY[4])  # Obsidian = 2 x Ruby

    def round_day(self, k, day=0):
        """Day `day` of the k-th league round from the first one in setUp."""
        first = C.round_start(C._date(T.date_str(self.at(0)))) + __import__("datetime").timedelta(days=14)
        return T._start_of(first) + (14 * k + day) * 86_400_000 + 10 * 60 * MIN

    def work_at(self, ms, minutes):
        self.core.start(None, ms)
        self.core.end(ms + minutes * MIN)

    def test_one_league_at_a_time_up_and_down(self):
        self.work_at(self.round_day(0), 30000)       # 3000 XP: top of any table, but one league up only
        hist = C.leagues(C.Ledger(self.store, self.round_day(2, 1)))["history"]
        self.assertEqual([(w["before"], w["after"]) for w in hist[:2]], [(0, 1), (1, 0)])   # then an empty round
        self.assertEqual(C._date(hist[1]["week"]) - C._date(hist[0]["week"]), __import__("datetime").timedelta(days=14))

    def test_current_week_players(self):
        self.work_at(self.round_day(0), 6000)
        cur = C.leagues(C.Ledger(self.store, self.round_day(1, 0) + MIN))["current"]
        self.assertEqual(len(cur["players"]), 10)
        self.assertEqual(cur["zone"], "relegation")       # the round just began, 0 XP so far
        self.assertEqual(sum(p["you"] for p in cur["players"]), 1)
        self.assertEqual(cur["daysLeft"], 14)

    def test_seasons_goal_bars_grade(self):
        import datetime as dt
        self.assertEqual(C._season(dt.date(2026, 12, 3)), (2026, 0))
        self.assertEqual(C._season(dt.date(2027, 2, 28)), (2026, 0))      # still winter 2026
        self.assertEqual(C._season(dt.date(2026, 9, 1)), (2026, 3))
        self.assertEqual(C._season(dt.date(2026, 8, 31)), (2026, 2))
        self.assertEqual(C.season_label("2026-autumn"), "Autumn 2026")
        # Winter 2026 comes after autumn 2026, even though its index is 0.
        import datetime as dt2
        self.assertLess(C._season_start(2026, 3), C._season_start(2026, 0))
        ledger = C.Ledger(self.store, self.at(0))
        s = C.seasons(ledger)[-1]
        self.assertEqual(s["bars"], 0)
        self.assertGreaterEqual(s["weeklyGoal"], 250)
        self.assertGreaterEqual(s["weeklyHard"], 350)
        self.assertEqual(C._grade(720, 300, 600), "S")      # 20 % beyond the hard goal
        self.assertEqual(C._grade(719, 300, 600), "A")
        self.assertEqual(C._grade(600, 300, 600), "A")
        self.assertEqual(C._grade(300, 300, 600), "B")
        self.assertEqual(C._grade(240, 300, 600), "C")
        self.assertEqual(C._grade(180, 300, 600), "D")
        self.assertEqual(C._grade(179, 300, 600), "F")

    def test_good_weeks_pace(self):
        import datetime as dt
        sun = dt.date(2026, 1, 4)
        weeks = {sun + dt.timedelta(days=7 * k): x for k, x in enumerate([100, 400, 200, 300, 0, 500])}
        # Better half of the six weeks: 500, 400, 300.
        self.assertEqual(C._good_weeks_pace(weeks, sun + dt.timedelta(days=7 * 6)), 400)
        self.assertIsNone(C._good_weeks_pace(weeks, sun + dt.timedelta(days=7 * 3)))   # 3 weeks: too few

    def _season_now(self):
        ledger = C.Ledger(self.store, self.at(0))
        return [x for x in C.seasons(ledger) if x["start"] <= T.date_str(self.at(0)) <= x["end"]][0]

    def test_season_medal_is_won_upgraded_and_kept(self):
        self.work(0, 10)
        s = self._season_now()
        self.work(0, s["goal"] * 10)                       # minutes // 10 XP: the goal, at once
        new = self.core.check_medals(self.at(1))
        self.assertIn(s["label"] + " medal", [m["name"] for m in new])
        row = self.store.db.execute("SELECT * FROM season_medals").fetchone()
        self.assertEqual(row["bars"], 1)
        palette = {c.lower() for c in (M.RED, M.ORANGE, M.LIME, M.GREEN, M.SPRING, M.CYAN, M.AZURE,
                                       M.INDIGO, M.VIOLET, M.PINK)}
        self.assertFalse({row["bg"], row["dot"], row["edge"]} & palette)
        self.work(0, (s["hardGoal"] - s["goal"]) * 10 + 10)
        self.core.check_medals(self.at(1))
        row2 = self.store.db.execute("SELECT * FROM season_medals").fetchone()
        self.assertEqual((row2["bars"], row2["bg"]), (2, row["bg"]))   # same colors, two bars
        self.assertEqual(self.core.state(self.at(1))["seasonMedals"][0]["bars"], 2)

    def test_season_colors_contrasted_and_off_palette(self):
        rng = random.Random(1)
        lum = lambda c: 0.2126 * C._rgb(c)[0] + 0.7152 * C._rgb(c)[1] + 0.0722 * C._rgb(c)[2]
        for _ in range(500):
            c = C.season_colors(rng)
            for v in c.values():
                self.assertTrue(C._far_from_base(v), v)
            self.assertGreater(lum(c["dot"]) - lum(c["bg"]), 90)      # the star stands out

    def test_rosters_change_each_season_with_distinct_first_names(self):
        self.assertGreaterEqual(len(C.RIVAL_NAMES), 100)
        self.assertEqual(len(set(C.RIVAL_NAMES)), len(C.RIVAL_NAMES))
        rosters = [C.season_roster(C._season_key(y, i)) for y in (2026, 2027, 2028) for i in range(4)]
        for r in rosters:
            self.assertEqual(len(r), 9)
            self.assertEqual(len({n.split()[0] for n in r}), 9)
        self.assertGreater(len({tuple(r) for r in rosters}), 10)
        self.assertEqual(C.season_roster("2026-autumn"), C.season_roster("2026-autumn"))

    def test_every_rival_has_a_bio(self):
        from prometheus.bios import BIOS
        self.assertEqual(set(C.RIVAL_NAMES), set(BIOS))
        cur = C.leagues(C.Ledger(self.store, self.at(0)))["current"]
        for pl in cur["players"]:
            if not pl["you"]:
                self.assertTrue(pl["bio"]["line"])

    def test_weeks_start_on_sunday(self):
        import datetime as dt
        self.assertEqual(T.week_first(dt.date(2026, 10, 18)), dt.date(2026, 10, 18))   # a Sunday
        self.assertEqual(T.week_first(dt.date(2026, 10, 24)), dt.date(2026, 10, 18))   # the Saturday after
        self.assertEqual(T.week_key(dt.date(2026, 10, 18)), T.week_key(dt.date(2026, 10, 24)))

    def test_leaderboard_and_records(self):
        self.work(0, 100)
        self.work(1, 300)
        self.work(2, 200)
        board = self.core.leaderboard("days", self.at(3))
        self.assertEqual([e["value"] for e in board["entries"][:3]], [30, 20, 10])
        self.assertEqual(C.records([(1, 10), (2, 30), (3, 20), (4, 40)]), 2)
        self.assertEqual(C.podiums([(i, v) for i, v in enumerate([5, 4, 3, 2, 1, 9, 0, 4])]), 2)

    def test_season_preview_colors_are_the_medal_colors(self):
        self.work(0, 10)
        s = self._season_now()
        preview = [x for x in self.core.seasons(self.at(0))["seasons"] if x["key"] == s["key"]][0]["colors"]
        self.work(0, s["goal"] * 10)
        self.core.check_medals(self.at(1))
        row = self.store.db.execute("SELECT bg, dot, edge FROM season_medals").fetchone()
        self.assertEqual((row["bg"], row["dot"], row["edge"]), (preview["bg"], preview["dot"], preview["edge"]))

    def test_leaderboard_quest_removal_keeps_xp(self):
        q = self.core.quest_add("Ship it", "short", self.at(0))["quest"]["id"]
        self.core.quest_activate(q, self.at(0))
        self.work(0, 120)
        self.assertEqual(len(self.core.leaderboard("quests", self.at(1))["entries"]), 1)
        xp = self.core.profile(self.at(1))["xp"]
        self.core.leaderboard_remove_quest(q, self.at(1))
        self.assertEqual(self.core.leaderboard("quests", self.at(1))["entries"], [])
        self.assertEqual(self.core.profile(self.at(1))["xp"], xp)
        self.assertEqual(self.core.quests_list(self.at(1))["quests"], [])     # an open quest is deleted too

    def test_achievements(self):
        self.work_at(self.round_day(0), 30000)
        self.work_at(self.round_day(1), 40000)
        at = self.round_day(2, 1)
        self.core.check_medals(at)
        got = set(self.store.unlocked_achievements()) | {a["id"] for a in self.core.check_achievements(at)}
        for aid in ("promoted:1", "leagueclimb:2", "promostreak:2"):
            self.assertIn(aid, got)


if __name__ == "__main__":
    unittest.main()
