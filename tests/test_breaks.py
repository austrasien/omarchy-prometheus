import unittest

from prometheus import timeutil as T
from prometheus.core import Core
from prometheus.store import Store

MIN = 60_000


class BreakTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        self.t0 = T.day_start(T.now_ms()) + 9 * 60 * MIN
        self.core.set_presence_every(120)       # keep "Still there?" out of the way

    def tick(self, minutes):
        at = self.t0 + minutes * MIN
        self.core.update_presence(at)
        return self.core.update_breaks(at), at

    def test_asks_after_ninety_minutes_then_later_and_take(self):
        c = self.core
        c.start("Work", self.t0)
        self.assertEqual(self.tick(89)[0], [])
        events, at = self.tick(90)
        self.assertEqual(events[0][0], "break")
        self.assertIn("90 min", c.break_state(at)["reason"])
        c.break_later(at)
        self.assertIsNone(c.break_state(at))
        self.assertEqual(self.tick(105)[0], [])            # snoozed 20 min
        events, at = self.tick(111)
        self.assertEqual(events[0][0], "break")
        c.break_take(at)
        self.assertIsNotNone(c._session()["pause_started_at"])
        self.assertEqual(self.store.count_events("break_taken"), 1)

    def test_a_pause_of_five_minutes_resets(self):
        c = self.core
        c.start("Work", self.t0)
        self.tick(60)
        c.pause(self.t0 + 60 * MIN)
        self.tick(66)                                     # 6 minutes paused
        c.resume(self.t0 + 66 * MIN)
        self.tick(67)
        self.assertEqual(self.tick(140)[0], [])           # 74 min since the break
        self.assertEqual(self.tick(157)[0][0][0], "break")

    def test_off(self):
        c = self.core
        c.set_break_every(0)
        c.start("Work", self.t0)
        self.assertEqual(self.tick(300)[0], [])


if __name__ == "__main__":
    unittest.main()
