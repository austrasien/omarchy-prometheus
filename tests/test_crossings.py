import unittest

from prometheus import achievements as A
from prometheus import timeutil as T
from prometheus.core import Core
from prometheus.store import Store

MIN = 60_000


class CrossingTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: ("rain", 12)
        self.core.set_presence_every(120)
        self.t0 = T.day_start(T.now_ms()) - 3 * 86_400_000 + 4 * 60 * MIN   # 9:00, three days ago

    def test_a_full_day(self):
        c, t = self.core, self.t0
        c.goal_set({"hours": 2, "period": "day"})
        q = c.quest_add("Ship it", "short", t)["quest"]["id"]
        c.quest_activate(q, t)
        c.coffee.add(t)
        c.start("Work", t + 10 * MIN)
        tid = c.task_add("Write", "panel", t)["task"]["id"]
        # Ninety minutes in: break suggested and taken, with a coffee in it.
        for m in range(10, 101, 5):
            c.update_presence(t + m * MIN)
            c.update_breaks(t + m * MIN)
        c.break_take(t + 101 * MIN)
        c.coffee.add(t + 105 * MIN)
        c.resume(t + 112 * MIN)
        c.task_complete(tid, t + 120 * MIN)               # within 30 min of the break
        c.end(t + 200 * MIN)
        c.quest_complete(q, t + 201 * MIN)
        m = A.build_context(self.store, t + 202 * MIN, 1).cross
        self.assertEqual(m["coffeeBreaks"], 1)
        self.assertEqual(m["clearHead"], 1)
        self.assertEqual(m["questPacing"], 1)
        self.assertEqual(m["caffeinatedQuest"], 2)
        self.assertEqual(m["onTarget"], 1)               # 3 h of focus, goal 2 h
        self.assertEqual(m["rainyBrew"], 1)                # the 9:00 cup came before the session
        self.assertEqual(m["rainyList"], 1)
        self.assertGreaterEqual(m["sessionXp"], 15)
        self.assertEqual(m["questSeason"], 1)


if __name__ == "__main__":
    unittest.main()
