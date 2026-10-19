import datetime as dt
import unittest

from prometheus import coffee as K
from prometheus import timeutil as T
from prometheus.core import Core
from prometheus.store import Store

MIN = 60_000
H = 60 * MIN


class CoffeeTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        self.t9 = int(dt.datetime(2026, 10, 19, 9, 0).timestamp() * 1000)

    def test_caffeine_curve(self):
        cup = [0]
        peak = max(K.in_body(cup, m * MIN) for m in range(0, 180))
        at_peak = max(range(0, 180), key=lambda m: K.in_body(cup, m * MIN))
        self.assertTrue(80 < peak < 95, peak)
        self.assertTrue(30 <= at_peak <= 60, at_peak)
        # Five hours later, about half is left.
        self.assertAlmostEqual(K.in_body(cup, 5 * H + 45 * MIN) / K.in_body(cup, 45 * MIN), 0.5, delta=0.06)
        self.assertEqual(K.in_body(cup, -MIN), 0)

    def test_add_undo_and_ideal(self):
        c = self.core.coffee
        now = c.add(self.t9)
        self.assertEqual((now["cupsToday"], now["canUndo"]), (1, True))
        ideal = now["ideal"]["at"]
        self.assertGreater(ideal, self.t9 + 2 * H)           # caffeine must run low first
        self.assertLessEqual(K.in_body([self.t9], ideal), K.LOW_MG)
        self.assertTrue(c.undo(self.t9 + 2 * MIN)["success"])
        self.assertFalse(c.undo(self.t9 + 2 * MIN)["success"])   # nothing left
        c.add(self.t9)
        self.assertFalse(c.undo(self.t9 + 4 * MIN)["success"])   # too late (3 minutes)
        # No coffee within 8 h of bed (23:00).
        late = int(dt.datetime(2026, 10, 19, 16, 0).timestamp() * 1000)
        self.assertIsNone(c.ideal(late)["at"])
        c.set_bedtime(1)                                      # 1:00, the night after
        self.assertIsNotNone(c.ideal(late)["at"])
        c.set_bedtime(23)
        # The daily limit.
        for i in range(3):
            c.add(self.t9 + (i + 1) * MIN)
        self.assertIsNone(c.ideal(self.t9 + 5 * MIN)["at"])

    def test_day_view(self):
        c = self.core
        c.coffee.add(self.t9)
        c.start("Work", self.t9 + 30 * MIN)
        c.end(self.t9 + 150 * MIN)
        d = c.coffee.day(None, self.t9 + 3 * H)
        start = T.day_start(self.t9)
        h9 = d["hours"][(self.t9 - start) // H]
        self.assertEqual((h9["cups"], h9["focus"]), (1, 30))
        self.assertEqual(d["hours"][(self.t9 - start) // H + 1]["focus"], 60)
        self.assertEqual(len(d["sessions"]), 1)
        self.assertTrue(any(p["mg"] > 50 for p in d["caffeine"]))

    def test_measures_and_achievements(self):
        c = self.core
        c.coffee.add(self.t9)
        c.coffee.add(self.t9 + 10 * MIN)
        c.start("Work", self.t9 + 20 * MIN)
        c.end(self.t9 + 100 * MIN)
        c.check_achievements(self.t9 + 2 * H)
        got = set(self.store.unlocked_achievements())
        for aid in ("barista:1", "doubleshot:2", "peakcaffeine:100", "brewed:1"):
            self.assertIn(aid, got)


    def test_nudge(self):
        c = self.core
        k = c.coffee
        self.assertIsNone(k.nudge(self.t9, working=False))     # only in a session
        self.assertIsNotNone(k.nudge(self.t9, working=True))   # nothing on board: now
        k.nudge_no(self.t9)
        self.assertIsNone(k.nudge(self.t9 + 30 * MIN, working=True))
        self.assertIsNotNone(k.nudge(self.t9 + 61 * MIN, working=True))
        k.nudge_ok(self.t9 + 61 * MIN)
        self.assertEqual(k.now(self.t9 + 62 * MIN)["cupsToday"], 1)
        self.assertIsNone(k.nudge(self.t9 + 70 * MIN, working=True))   # just had one

    def test_break_next_at(self):
        c = self.core
        c.start("Work", self.t9)
        c.update_breaks(self.t9)
        self.assertEqual(c.break_next_at(self.t9 + MIN), self.t9 + 90 * MIN)
        c.pause(self.t9 + 10 * MIN)
        self.assertIsNone(c.break_next_at(self.t9 + 11 * MIN))


if __name__ == "__main__":
    unittest.main()
