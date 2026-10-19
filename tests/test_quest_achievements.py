import unittest

from prometheus import achievements as A
from prometheus import quests as Q
from prometheus import timeutil as T
from prometheus.core import Core
from prometheus.store import Store

MIN = 60_000


class QuestAchievementTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        self.t0 = T.day_start(T.now_ms()) + 10 * 60 * MIN

    def day(self, n, minutes=0):
        return T.add_days(T.day_start(self.t0), n) + 10 * 60 * MIN + minutes * MIN

    def unlocked(self, at):
        self.core.check_achievements(at)
        return set(self.store.unlocked_achievements())

    def add(self, kind, title="Q"):
        return self.core.quest_add(title, kind, self.day(0))["quest"]["id"]

    def test_first_quest_closer_red_thread_speedrun(self):
        q = self.add("short")
        self.core.quest_activate(q, self.day(0))
        self.core.start(None, self.day(0))
        self.core.end(self.day(0, 30))
        self.core.quest_complete(q, self.day(0, 40))
        got = self.unlocked(self.day(0, 41))
        for aid in ("questfirst:1", "closer:1", "redthread:1", "speedrunner:1"):
            self.assertIn(aid, got)
        self.assertNotIn("longgame:1", got)

    def test_rituals_and_unbroken(self):
        q = self.add("daily")
        for n in range(10):
            self.core.quest_complete(q, self.day(n))
        got = self.unlocked(self.day(9, 1))
        self.assertIn("rituals:10", got)
        self.assertIn("unbroken:7", got)

    def test_full_spectrum_and_clean_sweep(self):
        ids = [self.add("short", f"Q{i}") for i in range(10)]
        self.assertIn("fullspectrum:1", self.unlocked(self.day(0, 1)))
        for qid in ids[:7]:
            self.core.quest_delete(qid, self.day(0, 2))
        for qid in ids[7:]:
            self.core.quest_complete(qid, self.day(0, 3))
        self.assertIn("cleansweep:1", self.unlocked(self.day(0, 4)))

    def test_no_sweep_with_two(self):
        a, b = self.add("short", "A"), self.add("long", "B")
        self.core.quest_complete(a, self.day(0, 1))
        self.core.quest_complete(b, self.day(0, 2))
        self.assertNotIn("cleansweep:1", self.unlocked(self.day(0, 3)))

    def test_deep_quest_attrition_and_pivot(self):
        q = self.add("long")
        self.core.quest_activate(q, self.day(0))
        for n in range(5):
            self.core.start(None, self.day(n))
            self.core.end(self.day(n, 70))
        self.core.quest_delete(q, self.day(5))
        got = self.unlocked(self.day(5, 1))
        self.assertIn("deepquest:18000", got)
        self.assertIn("attrition:5", got)
        self.assertIn("pivot:1", got)

    def test_marathoner(self):
        q = self.add("long")
        self.core.quest_activate(q, self.day(0))
        self.core.quest_complete(q, self.day(31))
        got = self.unlocked(self.day(31, 1))
        self.assertIn("marathoner:1", got)
        self.assertIn("longgame:1", got)

    def test_unstarted_families_and_far_tiers_are_dots(self):
        fam = lambda: {f["id"]: f for f in self.core.achievements_list(self.day(0, 5))["families"]}
        closer = fam()["closer"]
        self.assertTrue(closer["masked"])
        self.assertNotIn("Closer", closer["title"] + closer["tiers"][0]["name"] + closer["tiers"][0]["desc"])
        self.assertIsNone(closer["value"])
        q = self.add("short")
        self.core.quest_complete(q, self.day(0, 1))
        self.unlocked(self.day(0, 2))
        tiers = fam()["closer"]["tiers"]
        self.assertFalse(fam()["closer"]["masked"])
        self.assertEqual(tiers[0]["name"], "Closer ×1")       # unlocked
        self.assertEqual(tiers[1]["name"], "Closer ×3")       # next: readable
        self.assertTrue(set(tiers[2]["name"]) <= {"•", " "})   # after: dots
        self.assertIsNone(tiers[2]["threshold"])

    def test_weights(self):
        fam = {f.id: f for f in A.FAMILIES}
        self.assertEqual(fam["longgame"].xp(0), 15)
        self.assertEqual(fam["marathoner"].xp(0), 40)
        self.assertEqual(fam["pivot"].xp(0), 25)


if __name__ == "__main__":
    unittest.main()
