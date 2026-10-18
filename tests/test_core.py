import unittest

from prometheus import timeutil as T
from prometheus.core import Core, Refused, Window
from prometheus.store import Store

MIN = 60_000


class CoreTest(unittest.TestCase):
    def tearDown(self):
        T.set_day_start_hour(T.DEFAULT_DAY_START_HOUR)

    def setUp(self):
        self.store = Store(":memory:")
        self.core = Core(self.store)
        self.core.on_battery = lambda: False
        self.core.weather_now = lambda at: (None, None)
        # 10:00 today, local: far from midnight so day maths stay simple.
        self.t0 = T.day_start(T.now_ms()) + 10 * 60 * MIN

    def at(self, minutes):
        return self.t0 + int(minutes * MIN)

    def ticks(self, start, end):
        """Checkpoint every 30 s, as the daemon does."""
        m = start
        while m <= end:
            self.core.tick(self.at(m))
            m += 0.5

    def apps(self, until):
        return {a["app"]: a["seconds"] for a in self.store.app_seconds(T.day_start(self.t0), until)}

    def test_spans_follow_app_changes_not_titles(self):
        c = self.core
        c.on_window(Window("Foot", "~"), self.at(0))
        c.on_window(Window("Foot", "vim"), self.at(5))     # same app: same span
        c.on_window(Window("Brave", "mail"), self.at(10))
        c.tick(self.at(10.5))
        c.on_window(None, self.at(12))                       # nothing focused
        self.assertEqual(self.apps(self.at(20)), {"Foot": 600, "Brave": 120})
        rows = self.store.db.execute("SELECT app, title FROM focus_spans ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Foot", "~"), ("Brave", "mail")])

    def test_session_pause_resume_end(self):
        c = self.core
        c.on_window(Window("Code"), self.at(0))
        c.start("Écrire", self.at(0))
        with self.assertRaises(Refused):
            c.start("encore", self.at(1))
        c.pause(self.at(20))
        c.resume(self.at(30))
        reply = c.end(self.at(50))
        recap = reply["recap"]
        self.assertEqual(recap["task"], "Écrire")
        self.assertEqual(recap["durationSeconds"], 40 * 60)      # 50 min minus 10 paused
        self.assertEqual(recap["apps"], [{"app": "Code", "seconds": 40 * 60}])  # paused time is not session time
        state = c.state(self.at(51))
        self.assertIsNone(state["session"])
        self.assertEqual(state["today"], {"sessions": 1, "seconds": 2400})
        self.assertEqual(state["history"][-1], {"date": T.date_str(self.t0), "minutes": 40})
        self.assertEqual(len(state["history"]), 7)

    def test_end_while_paused_counts_the_pause(self):
        c = self.core
        c.start(None, self.at(0))
        c.pause(self.at(10))
        recap = c.end(self.at(25))["recap"]
        self.assertEqual(recap["durationSeconds"], 600)
        self.assertIsNone(recap["task"])

    def test_state_session_shape(self):
        c = self.core
        c.start("  x  ", self.at(0))
        c.pause(self.at(3))
        s = c.state(self.at(4))["session"]
        self.assertEqual(s["task"], "x")
        self.assertEqual(s["startedAt"], self.at(0))
        self.assertEqual(s["pauseStartedAt"], self.at(3))
        self.assertEqual(s["pausedMs"], 0)

    def test_idle_backdates_and_excludes(self):
        c = self.core
        c.on_window(Window("Foot"), self.at(0))
        self.ticks(0, 15)
        c.set_idle(True, self.at(15), idle_seconds=300)   # idle since minute 10
        self.ticks(15.5, 40)
        c.set_idle(False, self.at(40))
        self.ticks(40.5, 45)
        self.assertEqual(self.apps(self.at(50)), {"Foot": 15 * 60})

    def test_suspend_gap_is_not_counted(self):
        c = self.core
        c.on_window(Window("Foot"), self.at(0))
        c.tick(self.at(0.5))
        c.tick(self.at(1))
        c.tick(self.at(180))      # three hours later: the machine slept
        c.tick(self.at(181))
        self.assertEqual(self.apps(self.at(200)), {"Foot": 2 * 60})

    def test_hidden_apps_are_not_recorded(self):
        c = self.core
        c.set_hidden_apps(["Signal"], self.at(0))
        c.on_window(Window("Signal"), self.at(0))
        c.on_window(Window("Foot"), self.at(5))
        c.tick(self.at(6))
        self.assertEqual(self.apps(self.at(10)), {"Foot": 60})

    def test_goal(self):
        c = self.core
        self.assertIsNone(c.goal_get(self.at(0))["goal"])
        self.assertEqual(c.goal_set({"hours": 99, "period": "day"})["goal"], {"hours": 16, "period": "day"})
        c.start("a", self.at(0))
        c.end(self.at(90))
        g = c.goal_get(self.at(91))
        self.assertEqual(g["progress"]["workedSeconds"], 5400)
        self.assertIsNone(c.goal_set("off")["goal"])
        with self.assertRaises(Refused):
            c.goal_set({"hours": 3, "period": "year"})

    def test_summary(self):
        c = self.core
        c.on_window(Window("Code"), self.at(0))
        c.start("deep", self.at(0))
        c.on_window(Window("Foot"), self.at(60))
        c.on_window(Window("Code"), self.at(90))
        c.end(self.at(150))
        s = c.summary({"fromMs": T.day_start(self.t0), "toMs": self.at(151)}, self.at(151))
        self.assertEqual(s["sessions"], 1)
        self.assertEqual(s["deepSessions"], 1)
        self.assertEqual(s["focusSeconds"], 150 * 60)
        self.assertEqual(s["switchesPerHour"], round(3 / 2.5, 1))

    def test_lock_cuts_at_once(self):
        c = self.core
        c.on_window(Window("Foot"), self.at(0))
        self.ticks(0, 10)
        c.set_locked(True, self.at(10))
        c.on_window(Window("Foot", "x"), self.at(11))   # events still arrive under lock
        self.ticks(10.5, 13)
        c.set_locked(False, self.at(13))
        self.ticks(13.5, 15)
        self.assertEqual(self.apps(self.at(20)), {"Foot": 12 * 60})
        self.assertTrue(c.state(self.at(14))["locked"] is False)

    def test_aliases_merge_and_rename(self):
        c = self.core
        c.on_window(Window("Brave Origin"), self.at(0))
        c.on_window(Window("YouTube"), self.at(10))
        c.on_window(Window("Foot"), self.at(15))
        c.tick(self.at(15.5))
        c.set_aliases({"Brave Origin": "Navigateur", "YouTube": "Navigateur", "x": " "}, self.at(16))
        self.assertEqual(c.aliases, {"Brave Origin": "Navigateur", "YouTube": "Navigateur"})
        st = c.state(self.at(16))
        self.assertEqual(st["apps"][0], {"app": "Navigateur", "seconds": 15 * 60})
        known = {a["app"]: a["alias"] for a in c.known_apps(30, self.at(16))["apps"]}
        self.assertEqual(known["YouTube"], "Navigateur")
        # Hiding the alias hides every app it covers.
        c.set_hidden_apps(["Navigateur"], self.at(16))
        c.on_window(Window("YouTube"), self.at(17))
        c.tick(self.at(18))
        self.assertEqual(self.apps(self.at(20))["YouTube"], 5 * 60)

    def test_days_and_insights(self):
        c = self.core
        yday = self.t0 - 24 * 60 * MIN
        c.on_window(Window("Code"), yday)
        c.start("hier", yday)
        c.end(yday + 30 * MIN)
        c.on_window(Window("Code"), self.at(0))
        c.start("aujourd'hui", self.at(0))
        c.on_window(Window("Foot"), self.at(20))
        c.tick(self.at(20.5))
        week = c.days(0, self.at(21))
        self.assertEqual(len(week["days"]), 7)
        today = [d for d in week["days"] if d["date"] == T.date_str(self.t0)][0]
        self.assertEqual(today["focusSeconds"], 21 * 60)   # the running session counts today
        self.assertGreaterEqual(today["trackedSeconds"], 20 * 60)
        ins = c.insights(self.at(21))
        self.assertEqual(ins["topApp"]["app"], "Code")
        # Yesterday's session ran 10:00-10:30; at 10:21 it had 21 minutes in.
        self.assertEqual(ins["yesterdaySameTime"]["focusSeconds"], 21 * 60)
        self.assertIsNotNone(ins["busiestDay"])
        older = c.days(1, self.at(21))
        self.assertEqual(older["weekOffset"], 1)

    def test_tasks(self):
        c = self.core
        a = c.task_add("  Écrire le README ", "obsidian", self.at(0))
        self.assertFalse(a["existed"])
        self.assertTrue(c.task_add("Écrire le README", "manual", self.at(1))["existed"])
        with self.assertRaises(Refused):
            c.task_add("   ", "manual", self.at(1))
        with self.assertRaises(Refused):   # no session: cannot check
            c.task_complete(a["task"]["id"], self.at(2))
        c.start("x", self.at(2))
        c.task_complete(a["task"]["id"], self.at(3))
        with self.assertRaises(Refused):
            c.task_complete(a["task"]["id"], self.at(4))
        listed = c.tasks_list(self.at(5))
        self.assertEqual(listed["tasks"], [])
        self.assertEqual(listed["doneToday"], 1)
        # Done tasks can come back as new open ones (procrastinate).
        self.assertFalse(c.task_add("Écrire le README", "procrastinated", self.at(6))["existed"])
        self.assertEqual(c.tasks_list(self.at(7))["tasks"][0]["source"], "procrastinated")

    def test_reopen_done_task(self):
        c = self.core
        c.start("s", self.at(0))
        t = c.task_add("Relire", "manual", self.at(0))["task"]
        c.task_complete(t["id"], self.at(1))
        listed = c.tasks_list(self.at(2))
        self.assertEqual([d["text"] for d in listed["done"]], ["Relire"])
        self.assertEqual(c.task_reopen(t["id"]), {"success": True, "merged": False})
        listed = c.tasks_list(self.at(3))
        self.assertEqual([x["text"] for x in listed["tasks"]], ["Relire"])
        self.assertEqual(listed["done"], [])
        with self.assertRaises(Refused):
            c.task_reopen(t["id"])
        # A done copy whose text is already open again merges into it.
        c.task_complete(t["id"], self.at(4))
        c.task_add("Relire", "procrastinated", self.at(5))
        self.assertTrue(c.task_reopen(t["id"])["merged"])
        self.assertEqual(len(c.tasks_list(self.at(6))["tasks"]), 1)

    def test_hidden_title_words(self):
        c = self.core
        c.set_hidden_words([" Banque ", "banque", ""], self.at(0))
        self.assertEqual(c.hidden_words, ["Banque"])
        c.on_window(Window("Brave Origin", "Docs"), self.at(0))
        self.ticks(0, 10)
        c.on_window(Window("Brave Origin", "Ma BANQUE en ligne"), self.at(10))  # same app, forbidden title
        self.ticks(10.5, 15)
        c.on_window(Window("Brave Origin", "Docs encore"), self.at(15))
        self.ticks(15.5, 20)
        self.assertEqual(self.apps(self.at(30)), {"Brave Origin": 15 * 60})
        titles = [r["title"] for r in self.store.db.execute("SELECT title FROM focus_spans")]
        self.assertNotIn("Ma BANQUE en ligne", titles)

    def test_timeline_merges_and_aliases(self):
        c = self.core
        c.on_window(Window("Code"), self.at(0))
        c.on_window(Window("Foot"), self.at(10))
        c.on_window(Window("Code"), self.at(10.5))   # 30 s away: bridged
        c.start("s", self.at(12))
        c.on_window(Window("YouTube"), self.at(20))
        c.tick(self.at(25))
        c.set_aliases({"YouTube": "Vidéo"}, self.at(25))
        t = c.timeline(None, self.at(30))
        # Foot lasted 30 s and stays a segment; the alias applies to YouTube.
        self.assertEqual([x["app"] for x in t["segments"]], ["Code", "Foot", "Code", "Vidéo"])
        self.assertEqual(len(t["sessions"]), 1)
        self.assertEqual(t["sessions"][0]["start"], self.at(12))

    def test_day_starts_at_five_by_default(self):
        midnight = T.day_start(self.t0) - 5 * 60 * MIN       # calendar midnight of t0's date
        two_am = midnight + 2 * 60 * MIN                     # 02:00 belongs to the day before
        self.assertEqual(T.date_str(two_am), T.date_str(midnight - 1))
        self.assertEqual(T.day_start(two_am), T.add_days(T.day_start(self.t0), -1))
        c = self.core
        c.start("nuit", two_am - 60 * MIN)                    # 01:00 to 02:00
        c.end(two_am)
        st = c.state(self.at(0))
        self.assertEqual(st["today"]["sessions"], 0)          # yesterday's night, not today
        self.assertEqual(st["history"][-2]["minutes"], 60)
        self.assertEqual(st["dayStartHour"], 5)

    def test_change_day_start(self):
        c = self.core
        self.assertEqual(c.set_day_start(0, self.at(0))["dayStartHour"], 0)
        midnight = T.day_start(self.t0)
        self.assertEqual(T.date_str(midnight + 2 * 60 * MIN), T.date_str(self.t0))
        with self.assertRaises(Refused):
            c.set_day_start(13, self.at(0))
        # Persisted: a new core over the same store picks it up.
        T.set_day_start_hour(5)
        Core(self.store)
        self.assertEqual(T.day_start_hour(), 0)

    def test_task_xp_grows_each_day_and_freezes(self):
        c = self.core
        day = 24 * 60 * MIN
        t = c.task_add("Vieille tâche", "manual", self.at(0))["task"]
        self.assertEqual(t["xp"], 1)
        self.assertEqual(c.tasks_list(self.at(0) + 3 * day)["tasks"][0]["xp"], 4)
        c.start("s", self.at(0) + 3 * day)
        done = c.task_complete(t["id"], self.at(1) + 3 * day)
        self.assertEqual(done["xp"], 4)
        later = c.tasks_list(self.at(2) + 3 * day)
        self.assertEqual(later["done"][0]["xp"], 4)
        self.assertEqual(later["xpToday"], 4)
        # The task's own age counts, not day starts: 23 h later it is still 1 XP.
        u = c.task_add("Soir", "manual", self.at(10))["task"]
        self.assertEqual(c.tasks_list(self.at(10) + day - MIN)["tasks"][-1]["xp"], 1)
        self.assertEqual(c.tasks_list(self.at(10) + day)["tasks"][-1]["xp"], 2)

    def test_levels(self):
        lf = Core.level_for
        self.assertEqual(lf(0), {"level": 1, "levelXp": 0, "levelCost": 100})
        self.assertEqual(lf(99)["level"], 1)
        self.assertEqual(lf(100), {"level": 2, "levelXp": 0, "levelCost": 150})
        self.assertEqual(lf(250), {"level": 3, "levelXp": 0, "levelCost": 200})
        self.assertEqual(lf(260)["levelXp"], 10)

    def test_profile_xp(self):
        c = self.core
        c.start("s", self.at(0))
        t = c.task_add("Tâche", "manual", self.at(0))["task"]
        c.task_complete(t["id"], self.at(1))          # 1 XP
        c.pause(self.at(20))
        c.resume(self.at(40))                          # 20 paused minutes earn nothing
        prof = c.state(self.at(65))["profile"]         # 45 min of focus, running session included
        self.assertEqual(prof["focusXp"], 4)
        self.assertEqual(prof["taskXp"], 1)
        self.assertEqual(prof["xp"], 5)
        self.assertEqual(prof["level"], 1)
        sess = c.state(self.at(65))["session"]
        self.assertEqual(sess["bonusXp"], 1)          # the task checked in this session
        self.assertEqual(sess["secondsPerXp"], 600)

    def test_challenge_flow(self):
        from prometheus import core as K
        c = self.core
        c.on_window(Window("Code"), self.at(0))
        c.start("long", self.at(0))
        self.assertEqual(c.update_challenge(self.at(59)), [])
        ev = c.update_challenge(self.at(60))
        self.assertEqual(ev[0][0], "offer")
        cid = ev[0][1]["id"]
        self.assertEqual(c.state(self.at(60))["challenge"]["state"], "offered")
        c.challenge_accept(cid, self.at(61))
        with self.assertRaises(Refused):       # committed: cannot end
            c.end(self.at(70))
        c.pause(self.at(70))
        c.resume(self.at(80))                    # paused time does not count toward it
        st = c.state(self.at(81))["challenge"]
        self.assertEqual(st["state"], "active")
        self.assertEqual(st["remainingSeconds"], (20 - 10) * 60)
        ev = c.update_challenge(self.at(91))     # 61 + 20 + 10 paused
        self.assertEqual([e[0] for e in ev], ["won", "offer"])
        self.assertEqual(c.profile(self.at(91))["challengeXp"], 2)
        self.assertEqual(ev[1][1]["xp"], 3)           # the chained one is worth more
        c.challenge_decline(ev[1][1]["id"], self.at(92))
        self.assertEqual(c.update_challenge(self.at(200)), [])   # declined: no more offers
        self.assertTrue(c.end(self.at(201))["success"])

    def test_challenge_abandon_and_expiry(self):
        c = self.core
        c.start("a", self.at(0))
        cid = c.update_challenge(self.at(60))[0][1]["id"]
        c.challenge_accept(cid, self.at(60))
        c.challenge_abandon(self.at(65))
        self.assertTrue(c.end(self.at(66))["success"])
        self.assertEqual(c.profile(self.at(66))["challengeXp"], -3)   # abandoning costs 3 XP
        c.start("b", self.at(100))
        cid = c.update_challenge(self.at(160))[0][1]["id"]
        self.assertEqual(c.update_challenge(self.at(166))[0][0], "expired")
        with self.assertRaises(Refused):
            c.challenge_accept(cid, self.at(167))

    def test_challenge_chain_of_three(self):
        c = self.core
        self.assertEqual([Core.challenge_bonus(i) for i in range(3)], [2, 3, 5])
        c.start("marathon", self.at(0))
        ev = c.update_challenge(self.at(60))
        t = 60
        for n in range(3):
            self.assertEqual(ev[-1][0], "offer")
            self.assertEqual(ev[-1][1]["index"], n + 1)
            c.challenge_accept(ev[-1][1]["id"], self.at(t))
            t += 20
            ev = c.update_challenge(self.at(t))
        self.assertEqual([e[0] for e in ev], ["won"])  # third won: no fourth offer
        self.assertEqual(c.profile(self.at(t))["challengeXp"], 2 + 3 + 5)
        self.assertEqual(c.update_challenge(self.at(t + 30)), [])

    def test_auto_pause_on_idle_and_lock(self):
        c = self.core
        c.on_window(Window("Code"), self.at(0))
        c.start("s", self.at(0))
        self.ticks(0.5, 30)
        c.set_idle(True, self.at(30), idle_seconds=300)       # idle since 25
        self.assertEqual(c.state(self.at(31))["session"]["autoPaused"], ["idle"])
        self.ticks(30.5, 50)
        c.set_locked(True, self.at(40))
        c.set_locked(False, self.at(50))                       # still idle: stays paused
        self.assertIsNotNone(c.state(self.at(50))["session"]["pauseStartedAt"])
        c.set_idle(False, self.at(55))                         # back: resumes by itself
        st = c.state(self.at(60))["session"]
        self.assertIsNone(st["pauseStartedAt"])
        self.assertEqual(st["autoPaused"], [])
        recap = c.end(self.at(60))["recap"]
        self.assertEqual(recap["durationSeconds"], (25 + 5) * 60)   # 25-55 away

    def test_manual_pause_never_auto_resumes(self):
        c = self.core
        c.start("s", self.at(0))
        c.pause(self.at(10))
        c.set_locked(True, self.at(11))
        c.set_locked(False, self.at(20))
        self.assertIsNotNone(c.state(self.at(21))["session"]["pauseStartedAt"])
        # Auto-paused, then paused by hand: stays paused too.
        c.resume(self.at(30))
        c.set_locked(True, self.at(40))
        c.pause(self.at(41))
        c.set_locked(False, self.at(50))
        self.assertIsNotNone(c.state(self.at(51))["session"]["pauseStartedAt"])

    def test_sleep_counts_as_pause(self):
        c = self.core
        c.on_window(Window("Code"), self.at(0))
        c.start("s", self.at(0))
        self.ticks(0.5, 10)
        c.tick(self.at(130))                                   # two hours asleep
        self.ticks(130.5, 140)
        recap = c.end(self.at(140))["recap"]
        self.assertEqual(recap["durationSeconds"], 20 * 60)

    def test_delete_task(self):
        c = self.core
        t = c.task_add("Erreur", "manual", self.at(0))["task"]
        c.task_delete(t["id"])
        self.assertEqual(c.tasks_list(self.at(1))["tasks"], [])
        with self.assertRaises(Refused):
            c.task_delete(t["id"])

    def test_presence_check(self):
        from prometheus import core as K
        c = self.core
        c.on_window(Window("YouTube"), self.at(0))
        c.start("s", self.at(0))
        self.assertEqual(c.update_presence(self.at(19)), [])
        self.assertEqual(c.update_presence(self.at(20))[0][0], "presence")
        self.assertFalse(c.state(self.at(21))["presence"]["flashing"])
        self.assertTrue(c.state(self.at(23))["presence"]["flashing"])
        c.presence_confirm(self.at(23))                        # still there
        self.assertIsNone(c.state(self.at(23))["presence"])
        self.assertEqual(c.update_presence(self.at(23 + 19)), [])
        self.assertEqual(c.update_presence(self.at(23 + 20))[0][0], "presence")
        ev = c.update_presence(self.at(23 + 24))               # no answer in 4 min
        self.assertEqual(ev[0][0], "absent")
        st = c.state(self.at(60))["session"]
        self.assertEqual(st["pauseStartedAt"], self.at(23 + 20))   # backdated to the question
        self.assertEqual(st["autoPaused"], [])                     # resumed by hand only
        c.resume(self.at(70))
        recap = c.end(self.at(70))["recap"]
        self.assertEqual(recap["durationSeconds"], (23 + 20) * 60)

    def test_presence_interval_setting(self):
        c = self.core
        self.assertEqual(c.presence_every_minutes(), 20)
        c.set_presence_every(10)
        c.start("s", self.at(0))
        self.assertEqual(c.update_presence(self.at(9)), [])
        self.assertEqual(c.update_presence(self.at(10))[0][0], "presence")
        with self.assertRaises(Refused):
            c.set_presence_every(2)
        with self.assertRaises(Refused):
            c.set_presence_every(500)


    def test_presence_clock_survives_a_daemon_restart(self):
        self.core.start(None, self.at(0))
        self.assertEqual(self.core.update_presence(self.at(15)), [])
        restarted = Core(self.store)           # the daemon comes back up
        events = restarted.update_presence(self.at(20))
        self.assertEqual([e[0] for e in events], ["presence"])
        again = Core(self.store)               # and the pending question too
        self.assertIsNotNone(again.presence_state(self.at(21)))


    def test_handle_and_share(self):
        self.assertEqual(self.core.set_handle("@thibault_42")["handle"], "thibault_42")
        with self.assertRaises(Refused):
            self.core.set_handle("bad handle!")
        self.core.start(None, self.at(0))
        self.core.end(self.at(60))
        card = self.core.share(self.at(61))
        self.assertEqual(card["handle"], "thibault_42")
        self.assertEqual(card["league"]["name"], "Bronze")
        self.assertTrue(card["firstDay"])
        self.assertTrue(card["seasons"][0]["running"])
        self.assertEqual(card["format"], "gif")
        self.assertEqual(card["stamps"], [])          # none earned: none shown
        self.core.set_share_format("apng")
        self.assertEqual(self.core.share(self.at(61))["format"], "apng")
        with self.assertRaises(Refused):
            self.core.set_share_format("bmp")
        self.assertEqual(self.core.state(self.at(61))["handle"], "thibault_42")


    def test_abandoning_a_challenge_costs_three_xp(self):
        c = self.core
        c.start(None, self.at(0))
        c.update_challenge(self.at(61))                       # offered after an hour
        ch = c.challenge_state(self.at(61))
        c.challenge_accept(ch["id"], self.at(61))
        before = c.profile(self.at(62))["challengeXp"]
        self.assertEqual(c.challenge_abandon(self.at(62))["penalty"], 3)
        self.assertEqual(c.profile(self.at(62))["challengeXp"], before - 3)


if __name__ == "__main__":
    unittest.main()
