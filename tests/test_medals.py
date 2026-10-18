import datetime as dt
import unittest

from prometheus import medals as M
from prometheus import timeutil as T
from prometheus.core import Core
from prometheus.store import Store

MIN = 60_000
H = 60 * MIN


def at(y, m, d, hh=12, mm=0):
    return int(dt.datetime(y, m, d, hh, mm).astimezone().timestamp() * 1000)


class MedalsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.battery_percent = lambda: 50.0
        self.core.weather_now = lambda t: (None, None)

    def tearDown(self):
        T.set_day_start_hour(T.DEFAULT_DAY_START_HOUR)

    def session(self, start, minutes):
        self.core.start("x", start)
        self.core.end(start + minutes * MIN)

    def awards(self):
        return self.store.medal_awards()

    def test_daily_medal_once_per_day_and_again_next_day(self):
        self.session(at(2030, 3, 4, 9), 130)                    # Monday, 2 h 10 from 9:00
        self.core.check_medals(at(2030, 3, 4, 20))
        self.core.check_medals(at(2030, 3, 4, 21))              # no double award
        self.assertIn(("dayshift", "2030-03-04"), self.awards())
        self.assertNotIn(("earlybird", "2030-03-04"), self.awards())   # 9:00 is not before 8:00
        self.assertNotIn(("deepday", "2030-03-04"), self.awards())
        self.session(at(2030, 3, 5, 9), 130)
        self.core.check_medals(at(2030, 3, 5, 20))
        self.assertIn(("dayshift", "2030-03-05"), self.awards())
        placard = {p["id"]: p for p in M.placard(self.store, at(2030, 3, 5, 20))}
        self.assertEqual(placard["dayshift"]["count"], 2)
        self.assertTrue(placard["dayshift"]["current"])
        self.assertEqual(placard["dayshift"]["dots"], 1)

    def test_weekly_seven_for_seven_and_history(self):
        for d in range(4, 11):                                   # Mon 4 to Sun 10 March 2030
            self.session(at(2030, 3, d, 14), 20)
        new = self.core.check_medals(at(2030, 3, 20), history=True)
        ids = {(m["id"], m["key"]) for m in new}
        self.assertIn(("sevenforseven", "2030-W10"), ids)
        self.assertIn(("weekendwarrior", "2030-W10"), ids)
        self.assertEqual(M.BY_ID["sevenforseven"].ribbon()["dots"], 2)

    def test_xp_and_profile(self):
        self.assertEqual([M.BY_ID[i].xp for i in ("dayshift", "deepday", "ironday")], [5, 7, 10])
        self.assertEqual(M.BY_ID["centurion"].xp, 120)
        self.session(at(2030, 3, 4, 9), 130)
        self.core.check_medals(at(2030, 3, 4, 20))
        self.assertEqual(self.core.profile(at(2030, 3, 4, 20))["medalXp"], 5)       # Day Shift only

    def test_record_week_needs_floor_and_previous(self):
        self.session(at(2030, 3, 4, 10), 11 * 60)                 # 11 h in week 10
        self.core.check_medals(at(2030, 3, 9), history=True)
        self.assertIn(("recordweek", "2030-W10"), self.awards())
        self.session(at(2030, 3, 11, 10), 5 * 60)                 # 5 h in week 11: no record
        self.core.check_medals(at(2030, 3, 16))
        self.assertNotIn(("recordweek", "2030-W11"), self.awards())


if __name__ == "__main__":
    unittest.main()
