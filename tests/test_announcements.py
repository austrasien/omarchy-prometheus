import unittest
from unittest import mock

from prometheus import competition as C
from prometheus import timeutil as T
from prometheus.core import Core, Refused
from prometheus.store import Store

MIN = 60_000


def rounds(*weeks):
    return {"history": [{"week": w, "end": w, "before": 2, "after": 3, "xp": 900, "rank": 1, "outcome": "up"}
                        for w in weeks], "current": {"league": 3}}


def season(start, bars=1):
    return {"key": start[:4] + "-summer", "label": "Summer " + start[:4], "start": start, "running": False,
            "bars": bars, "grade": "B", "xp": 3300, "goal": 3250, "hardGoal": 4550}


class AnnouncementTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.at = T.day_start(T.now_ms()) + 10 * 60 * MIN

    def state(self, league_weeks, seasons):
        self.core._announce_day = None
        with mock.patch.object(C, "leagues", return_value=rounds(*league_weeks)), \
             mock.patch.object(C, "seasons", return_value=seasons):
            return self.core.announcements(self.at)

    def test_first_look_records_without_announcing(self):
        self.assertEqual(self.state(["2026-09-27"], [season("2026-06-01")]), [])
        self.assertEqual(self.store.get_setting("announced:league"), "2026-09-27")
        self.assertEqual(self.store.get_setting("announced:season"), "2026-06-01")

    def test_next_ends_are_announced_until_seen(self):
        self.state(["2026-09-27"], [season("2026-06-01")])
        out = self.state(["2026-09-27", "2026-10-11"], [season("2026-06-01"), season("2026-09-01", bars=2)])
        self.assertEqual([a["kind"] for a in out], ["league", "season"])
        league, autumn = out
        self.assertEqual((league["outcome"], league["before"]["name"], league["after"]["name"]), ("up", "Gold", "Sapphire"))
        self.assertEqual(autumn["bars"], 2)
        self.assertIn("bg", autumn["colors"])
        self.core.announce_seen(league["id"])
        self.core.announce_seen(autumn["id"])
        self.assertEqual(self.state(["2026-09-27", "2026-10-11"], [season("2026-09-01", bars=2)]), [])

    def test_preview(self):
        self.core.announce_preview("league", "down", self.at)
        self.core.announce_preview("season", "0", self.at)
        demos = self.core.announcements(self.at)
        self.assertEqual([(d["kind"], d.get("outcome"), d.get("bars")) for d in demos],
                         [("league", "down", None), ("season", None, 0)])
        self.assertLess(C.LEAGUES.index(demos[0]["after"]["name"]), C.LEAGUES.index(demos[0]["before"]["name"]))
        for d in demos:
            self.core.announce_seen(d["id"])
        self.assertEqual(self.core.announcements(self.at), [])
        with self.assertRaises(Refused):
            self.core.announce_seen("nope")


if __name__ == "__main__":
    unittest.main()
