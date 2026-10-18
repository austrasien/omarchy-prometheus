import unittest

from prometheus import quests as Q
from prometheus import timeutil as T
from prometheus.core import Core, Refused
from prometheus.store import Store

MIN = 60_000
DAY = 24 * 60 * MIN


class QuestTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        self.t0 = T.day_start(T.now_ms()) + 10 * 60 * MIN   # 10:00 today

    def day(self, n, minutes=0):
        return T.add_days(T.day_start(self.t0), n) + 10 * 60 * MIN + minutes * MIN

    def work(self, n):
        """A session on day n."""
        self.core.start(None, self.day(n))
        self.core.end(self.day(n, 60))

    def add(self, kind, title="Write the report"):
        return self.core.quest_add(title, kind, self.day(0))["quest"]["id"]

    def test_worth(self):
        self.assertEqual(Q.worth("short", 0), 15)
        self.assertEqual(Q.worth("short", 3), 25)
        self.assertEqual(Q.worth("short", 30), 40)
        self.assertEqual(Q.worth("long", 10), 80)
        self.assertEqual(Q.worth("long", 100), 150)
        self.assertEqual(Q.worth("daily", 0, 2), 7)
        self.assertEqual(Q.worth("daily", 0, 30), 10)

    def test_only_one_active_and_shown_in_state(self):
        a, b = self.add("short", "A"), self.add("long", "B")
        self.core.quest_activate(a, self.day(0))
        self.core.quest_activate(b, self.day(0))
        self.assertEqual(self.core.state(self.day(0))["quest"]["title"], "B")
        self.core.quest_deactivate(b, self.day(0))
        self.assertIsNone(self.core.state(self.day(0))["quest"])

    def test_days_worked_count_only_while_active(self):
        q = self.add("short")
        self.work(0)                      # not active yet
        self.core.quest_activate(q, self.day(1))
        self.work(1)
        self.work(1)                      # same day counts once
        self.work(2)
        self.core.quest_deactivate(q, self.day(2, 90))
        self.work(3)
        self.assertEqual(self.core.quests.days_worked(q), 2)
        reply = self.core.quest_complete(q, self.day(4))
        self.assertEqual(reply["xp"], 20)
        self.assertEqual(self.core.profile(self.day(4))["questXp"], 20)
        self.assertIsNone(self.core.state(self.day(4))["quest"])

    def test_activating_during_a_session_counts_the_day(self):
        q = self.add("long")
        self.core.start(None, self.day(0))
        self.core.quest_activate(q, self.day(0, 5))
        self.assertEqual(self.core.quests.days_worked(q), 1)

    def test_daily_resets_every_day_and_keeps_history(self):
        q = self.add("daily", "Inbox zero")
        self.assertEqual(self.core.quest_complete(q, self.day(0))["xp"], 5)
        with self.assertRaises(Refused):
            self.core.quest_complete(q, self.day(0, 30))
        listed = self.core.quests_list(self.day(1))["quests"][0]
        self.assertFalse(listed["doneToday"])
        self.assertEqual(listed["streak"], 1)
        self.assertEqual(self.core.quest_complete(q, self.day(1))["xp"], 6)
        self.assertEqual(self.core.quests_list(self.day(1))["quests"][0]["timesDone"], 2)
        self.assertEqual(self.core.profile(self.day(1))["questXp"], 11)

    def test_delete_keeps_earned_xp(self):
        q = self.add("daily")
        self.core.quest_complete(q, self.day(0))
        self.core.quest_delete(q, self.day(0))
        self.assertEqual(self.core.quests_list(self.day(0))["quests"], [])
        self.assertEqual(self.core.profile(self.day(0))["questXp"], 5)

    def test_uncomplete(self):
        q = self.add("short")
        self.core.quest_complete(q, self.day(0))
        self.core.quest_uncomplete(q, self.day(0))
        self.assertEqual(self.core.profile(self.day(0))["questXp"], 0)
        self.assertEqual(len(self.core.quests_list(self.day(0))["quests"]), 1)

    def test_colors_first_red_then_unique(self):
        ids = [self.add("short", f"Q{i}") for i in range(10)]
        colors = [r["color"] for r in self.core.quests_list(self.day(0))["quests"]]
        self.assertEqual(colors[0], Q.RED)
        self.assertEqual(len(set(colors)), 10)
        self.assertEqual(set(colors), set(Q.COLORS))
        with self.assertRaises(Refused):
            self.add("short", "Eleventh")
        # Red gone: the next quest is red again.
        self.core.quest_delete(ids[0], self.day(0))
        q = self.core.quest_add("New", "short", self.day(0))["quest"]
        self.assertEqual(q["color"], Q.RED)
        # A done quest frees its color.
        self.core.quest_complete(ids[1], self.day(0))
        q = self.core.quest_add("Another", "daily", self.day(0))["quest"]
        self.assertNotEqual(q["color"], Q.RED)

    def test_list_order_does_not_follow_activation(self):
        a, b = self.add("short", "A"), self.add("short", "B")
        self.core.quest_activate(b, self.day(0))
        self.assertEqual([q["title"] for q in self.core.quests_list(self.day(0))["quests"]], ["A", "B"])

    def test_activity_counts_only_while_active(self):
        q = self.add("short")
        self.core.task_add("Before", "manual", self.day(0))
        self.work(0)                                  # not active: not counted
        c = self.core
        c.start(None, self.day(1))
        c.quest_activate(q, self.day(1, 10))          # 50 min of this session count
        tid = c.task_add("Draft", "manual", self.day(1, 20))["task"]["id"]
        c.task_complete(tid, self.day(1, 30))
        c.end(self.day(1, 60))
        c.start(None, self.day(2))
        c.end(self.day(2, 60))                        # a full hour
        c.quest_deactivate(q, self.day(2, 90))
        self.work(3)                                  # put aside: not counted
        act = c.quests_list(self.day(3))["quests"][0]["activity"]
        self.assertEqual(act["sessions"], 2)
        self.assertEqual(act["seconds"], 110 * 60)
        self.assertEqual(act["tasks"], 1)
        self.assertEqual(act["xp"], 110 // 10 + 1)
        self.assertEqual(len(act["hours"]), 24)

    def test_deactivate_other_quest_is_a_no_op(self):
        a, b = self.add("short", "A"), self.add("short", "B")
        self.core.quest_activate(a, self.day(0))
        self.core.quest_deactivate(b, self.day(0))
        self.assertEqual(self.core.state(self.day(0))["quest"]["title"], "A")

    def test_refusals(self):
        with self.assertRaises(Refused):
            self.core.quest_add("  ", "short", self.day(0))
        with self.assertRaises(Refused):
            self.core.quest_add("x", "weekly", self.day(0))
        with self.assertRaises(Refused):
            self.core.quest_activate("nope", self.day(0))


if __name__ == "__main__":
    unittest.main()
