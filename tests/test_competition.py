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

    def test_thresholds_bronze_and_diamond(self):
        self.assertEqual(C._thresholds(0, None), (30, None))
        self.assertEqual(C._thresholds(9, 1000), (None, 300))
        self.assertEqual(C._thresholds(3, 200), (220, 75))

    def test_one_league_at_a_time_up_and_down(self):
        # Week 0: 600 min = 60 XP, way past Silver's floor: still one league only.
        self.work(0, 600)
        # Week 1: 70 XP, needs max(1.1 * 60, 50) = 66: up again, to Gold.
        self.work(7, 700)
        # Week 2: nothing at all: down one league.
        hist = C.leagues(C.Ledger(self.store, self.at(21)))["history"]
        self.assertEqual([(w["before"], w["after"]) for w in hist[:3]], [(0, 1), (1, 2), (2, 1)])

    def test_current_zone(self):
        self.work(0, 600)
        cur = C.leagues(C.Ledger(self.store, self.at(7, 1)))["current"]
        self.assertEqual(cur["league"], 1)
        self.assertEqual(cur["zone"], "relegation")       # Monday, 0 XP so far
        self.work(7, 400)                                  # 40 XP < 66 to promote
        cur = C.leagues(C.Ledger(self.store, self.at(8)))["current"]
        self.assertEqual(cur["zone"], "stagnation")

    def test_seasons_goal_bars_grade(self):
        ledger = C.Ledger(self.store, self.at(0))
        s = C.seasons(ledger)[-1]
        self.assertEqual((s["goal"], s["hardGoal"], s["bars"]), (300, 600, 0))
        self.assertEqual(C._grade(600, 300, 600), "A")
        self.assertEqual(C._grade(300, 300, 600), "B")
        self.assertEqual(C._grade(230, 300, 600), "C")
        self.assertEqual(C._grade(150, 300, 600), "D")
        self.assertEqual(C._grade(149, 300, 600), "F")

    def test_season_medal_is_won_upgraded_and_kept(self):
        for d in range(5):
            self.work(d, 600)                              # 5 x 60 = 300 XP
        new = self.core.check_medals(self.at(5))
        self.assertIn("Season 1 medal", [m["name"] for m in new])
        row = self.store.db.execute("SELECT * FROM season_medals").fetchone()
        self.assertEqual(row["bars"], 1)
        palette = {c.lower() for c in (M.RED, M.ORANGE, M.LIME, M.GREEN, M.SPRING, M.CYAN, M.AZURE,
                                       M.INDIGO, M.VIOLET, M.PINK)}
        self.assertFalse({row["bg"], row["dot"], row["edge"]} & palette)
        for d in range(5, 10):
            self.work(d, 600)
        self.core.check_medals(self.at(10))
        row2 = self.store.db.execute("SELECT * FROM season_medals").fetchone()
        self.assertEqual((row2["bars"], row2["bg"]), (2, row["bg"]))   # same colors, two bars
        self.assertEqual(self.core.state(self.at(10))["seasonMedals"][0]["bars"], 2)

    def test_season_colors_never_vivid(self):
        rng = random.Random(1)
        for _ in range(500):
            for c in C.season_colors(rng).values():
                r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
                hi, lo = max(r, g, b), min(r, g, b)
                self.assertLess((hi - lo) / hi if hi else 0, 0.62)   # saturation under the palette's

    def test_leaderboard_and_records(self):
        self.work(0, 100)
        self.work(1, 300)
        self.work(2, 200)
        board = self.core.leaderboard("days", self.at(3))
        self.assertEqual([e["value"] for e in board["entries"][:3]], [30, 20, 10])
        self.assertEqual(C.records([(1, 10), (2, 30), (3, 20), (4, 40)]), 2)
        self.assertEqual(C.podiums([(i, v) for i, v in enumerate([5, 4, 3, 2, 1, 9, 0, 4])]), 2)

    def test_achievements(self):
        self.work(0, 600)
        self.work(7, 700)
        self.core.check_medals(self.at(14))
        got = set(self.store.unlocked_achievements()) | {a["id"] for a in self.core.check_achievements(self.at(14))}
        for aid in ("promoted:1", "leagueclimb:2", "promostreak:2"):
            self.assertIn(aid, got)


if __name__ == "__main__":
    unittest.main()
