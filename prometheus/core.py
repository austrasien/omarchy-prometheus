"""Sessions, focus tracking and the state object the bar renders.

Pure logic over a Store and an injectable clock, so it can be tested without
Hyprland or a socket. Every public method takes `at` (epoch ms) when it
records time; the daemon passes now_ms().
"""

from __future__ import annotations

from dataclasses import dataclass

from . import achievements as A
from . import competition as C
from . import env
from . import medals as M
from . import quests as Q
from . import timeutil as T
from . import agents as A_
from .agents import AgentUsage
from .coffee import Coffee
from .store import Store, clipped_seconds, session_seconds

CHECKPOINT_GAP_MS = 90_000      # a checkpoint later than this means the machine slept
DEEP_SESSION_SECONDS = 2 * 3600
FOCUS_SECONDS_PER_XP = 600          # 1 XP per 10 minutes of session, pauses excluded
FIRST_LEVEL_COST = 100              # XP from level 1 to 2
LEVEL_COST_STEP = 50                # each next level costs this much more

# Extension challenge: offered once a session has this much focus; once
# accepted, the session cannot be ended before CHALLENGE_MINUTES more focus.
CHALLENGE_OFFER_AFTER_SECONDS = 60 * 60
CHALLENGE_MINUTES = 20
CHALLENGE_BASE_XP = 2               # bonus of the first challenge of a session
CHALLENGE_XP_GROWTH = 1.5           # each chained challenge is worth 1.5x the previous
CHALLENGE_MAX_PER_SESSION = 3
CHALLENGE_OFFER_TTL_MS = 5 * 60 * 1000

# Presence check: a running session asks "still there?" every so often (a
# playing video keeps idle away, so idle alone cannot tell). Unanswered, the
# pill flashes, then the session pauses, backdated to when it asked.
PRESENCE_EVERY_MINUTES = 20        # default; a setting (5 to 120)
BREAK_EVERY_MINUTES = 90           # default; a setting (0 = off, 30 to 180)
BREAK_MINUTES_RANGE = (30, 180)
BREAK_RESET_MS = 5 * 60 * 1000     # a pause this long counts as a break
BREAK_SNOOZE_MS = 20 * 60 * 1000
PRESENCE_MINUTES_RANGE = (5, 120)
PRESENCE_FLASH_AFTER_MS = 3 * 60 * 1000
PRESENCE_TIMEOUT_MS = 4 * 60 * 1000
GOAL_LIMITS = {"day": (0.5, 16), "week": (1, 80), "month": (1, 368)}


@dataclass
class Window:
    app: str
    title: str | None = None
    wm_class: str | None = None


class Refused(Exception):
    """An action that cannot apply now; replied as {success: false, error}."""


class Core:
    def __init__(self, store: Store):
        self.store = store
        self.quests = Q.Quests(store)
        self.quests.repair(T.now_ms())
        self.agents = AgentUsage(store)      # polled by the daemon
        self.coffee = Coffee(store)
        self.health = None                   # health.Health when a watch is linked
        T.set_day_start_hour(self.store.get_setting("dayStartHour", T.DEFAULT_DAY_START_HOUR))
        self.window: Window | None = None
        self.idle = False
        self.locked = False
        self.last_resume_at = 0       # a backdated auto-pause never reaches before this
        self.presence_since = None    # last proof of presence for the running session
        self.presence_asked_at = None
        self._load_presence()
        # The world around a session; replaced in tests.
        self.on_battery = env.on_battery
        self.battery_percent = env.battery_percent
        self.weather_now = env.weather_now
        self.span_id: int | None = None
        self.span_app: str | None = None
        self.last_tick: int | None = None

    # ------------------------------------------------------------- helpers

    @property
    def hidden_apps(self) -> list[str]:
        return list(self.store.get_setting("hiddenApps", []))

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self.store.get_setting("aliases", {}))

    def alias(self, app: str) -> str:
        return self.aliases.get(app, app)

    @property
    def hidden_words(self) -> list[str]:
        return list(self.store.get_setting("hiddenTitleWords", []))

    def _title_hidden(self, window: "Window | None") -> bool:
        """A window whose title contains a forbidden word is never recorded."""
        if window is None or not window.title:
            return False
        title = window.title.casefold()
        return any(w.casefold() in title for w in self.hidden_words)

    def _hidden(self, app: str) -> bool:
        hidden = self.hidden_apps
        return app in hidden or self.alias(app) in hidden

    def _apps(self, start: int, end: int, session_id: str | None = None) -> list[dict]:
        """Seconds per app in [start, end), aliases applied (merged apps add up)."""
        names = self.aliases
        totals: dict[str, int] = {}
        for row in self.store.app_seconds(start, end, session_id=session_id):
            name = names.get(row["app"], row["app"])
            totals[name] = totals.get(name, 0) + row["seconds"]
        return [{"app": a, "seconds": s} for a, s in sorted(totals.items(), key=lambda kv: -kv[1])]

    def _session(self):
        return self.store.open_session()

    def _active_session_id(self) -> str | None:
        s = self._session()
        if s is None or s["pause_started_at"] is not None:
            return None
        return s["id"]

    def _close_span(self, at: int, exact: bool = False) -> None:
        if self.span_id is not None:
            if exact:
                self.store.cut_span(self.span_id, at)
            else:
                self.store.extend_span(self.span_id, at)
            self.store.drop_empty_span(self.span_id)
        self.span_id = None
        self.span_app = None

    def _open_span(self, at: int) -> None:
        w = self.window
        if self.idle or self.locked or w is None or self._hidden(w.app) or self._title_hidden(w):
            return
        self.span_id = self.store.open_span(w.app, w.title, self._active_session_id(), at)
        self.span_app = w.app
        self.last_tick = at  # the suspend check measures from the span's own start

    def _split(self, at: int) -> None:
        """Close the running span and open the next one, e.g. on a session change."""
        self._close_span(at)
        self._open_span(at)

    # ------------------------------------------------------------ tracking

    def on_window(self, window: Window | None, at: int) -> None:
        prev = self.window
        self.window = window
        if (window is not None and prev is not None and window.app == prev.app
                and self.span_id is not None and not self._title_hidden(window)):
            return  # same app, new title: one span per app stretch
        self._split(at)

    def set_idle(self, idle: bool, at: int, idle_seconds: int = 0) -> None:
        if idle == self.idle:
            return
        if idle:
            # The idle notice arrives after the timeout: that time was idle too.
            since = max(0, at - idle_seconds * 1000)
            self._close_span(since, exact=True)
            self.idle = True
            self._auto_pause("idle", since)
        else:
            self.idle = False
            self._auto_resume("idle", at)
            self._split(at)

    def set_locked(self, locked: bool, at: int) -> None:
        """Locked screen: nothing is attributed until it is unlocked."""
        if locked == self.locked:
            return
        self.locked = locked
        if locked:
            self._close_span(at, exact=True)
            self._auto_pause("locked", at)
        else:
            self._auto_resume("locked", at)
            self._split(at)

    def tick(self, at: int) -> None:
        """Checkpoint the running span. A long gap means a suspend: cut there,
        and count the time asleep as a pause of the running session."""
        last = self.last_tick
        self.last_tick = at
        if last is not None and at - last > CHECKPOINT_GAP_MS:
            self._sleep_gap(last, at)
            if self.span_id is not None:
                self._close_span(last)
                self._open_span(at)
            return
        if self.span_id is not None:
            self.store.extend_span(self.span_id, at)
        self._quest_work(at)

    def _working(self) -> bool:
        s = self._session()
        return s is not None and s["pause_started_at"] is None

    def _quest_work(self, at: int) -> None:
        if self._working():
            self.quests.mark_work(at)

    # ---------------------------------------------------------- auto-pause
    # Away from the machine (idle, locked, asleep), the session clock stops
    # by itself. A pause made this way resumes by itself when the user is
    # back; a pause the user made never does. The reasons are kept in the
    # settings, so a daemon restart mid-pause still knows it was automatic.

    def _auto_state(self) -> dict:
        return dict(self.store.get_setting("autoPause", {}) or {})

    def _auto_pause(self, reason: str, since: int) -> None:
        s = self._session()
        if s is None:
            return
        state = self._auto_state()
        if s["pause_started_at"] is None:
            start = max(since, s["started_at"], self.last_resume_at)
            self.store.set_pause(s["id"], start, s["total_pause_ms"])
            self.store.add_event("autopause", start, s["id"])
            state = {"session": s["id"], "reasons": [reason]}
        elif state.get("session") == s["id"] and reason not in state.get("reasons", []):
            state["reasons"] = state.get("reasons", []) + [reason]
        else:
            return  # paused by hand: leave it to the user
        self.store.set_setting("autoPause", state)

    def _auto_resume(self, reason: str, at: int) -> None:
        s = self._session()
        state = self._auto_state()
        if s is None or state.get("session") != s["id"]:
            return
        reasons = [r for r in state.get("reasons", []) if r != reason]
        if reasons:
            self.store.set_setting("autoPause", {"session": s["id"], "reasons": reasons})
            return
        self.store.set_setting("autoPause", {})
        if s["pause_started_at"] is not None:
            total = s["total_pause_ms"] + max(0, at - s["pause_started_at"])
            self.store.set_pause(s["id"], None, total)
            self.last_resume_at = at
            self._present(at)

    def _sleep_gap(self, last: int, at: int) -> None:
        s = self._session()
        if s is None or s["pause_started_at"] is not None:
            return  # already paused: the pause covers the sleep
        self.store.set_pause(s["id"], None, s["total_pause_ms"] + (at - last))
        self.store.add_event("autopause", last, s["id"])

    def auto_paused(self) -> list[str]:
        s = self._session()
        state = self._auto_state()
        return list(state.get("reasons", [])) if s is not None and state.get("session") == s["id"] else []

    # ------------------------------------------------------------ sessions

    def start(self, task: str | None, at: int) -> dict:
        if self._session() is not None:
            raise Refused("A session is already running")
        task = (task or "").strip() or None
        sid = self.store.create_session(task, at)
        self.store.set_session_env(sid, on_battery=1 if self.on_battery() else 0)
        self.store.set_setting("autoPause", {})
        self.last_resume_at = at
        self._present(at)
        self._split(at)
        self._quest_work(at)
        return {"success": True}

    def pause(self, at: int) -> dict:
        s = self._session()
        if s is None:
            raise Refused("No session running")
        if s["pause_started_at"] is not None:
            self.store.set_setting("autoPause", {})  # now the user's pause: no auto-resume
            return {"success": True}
        self.store.set_pause(s["id"], at, s["total_pause_ms"])
        self.store.set_setting("autoPause", {})
        self._split(at)
        return {"success": True}

    def resume(self, at: int) -> dict:
        s = self._session()
        if s is None:
            raise Refused("No session running")
        if s["pause_started_at"] is None:
            return {"success": True}
        total = s["total_pause_ms"] + max(0, at - s["pause_started_at"])
        self.store.set_pause(s["id"], None, total)
        self.store.set_setting("autoPause", {})
        self.last_resume_at = at
        self._present(at)
        self._split(at)
        return {"success": True}

    def end(self, at: int, reason: str = "manual") -> dict:
        s = self._session()
        if s is None:
            raise Refused("No session running")
        ch = self.store.last_challenge(s["id"])
        if ch is not None and ch["state"] == "active":
            left = self._challenge_left(ch, s, at)
            raise Refused(f"Challenge running: {max(1, -(-left // 60))} more min. Abandon it to end the session.")
        if ch is not None and ch["state"] == "offered":
            self.store.update_challenge(ch["id"], state="expired", ended_at=at)
        total = s["total_pause_ms"]
        if s["pause_started_at"] is not None:
            total += max(0, at - s["pause_started_at"])
        self._close_span(at)
        self.store.finish_session(s["id"], at, total, reason)
        self.store.set_setting("autoPause", {})
        weather, temp = self.weather_now(at)
        battery = 1 if (s["on_battery"] or self.on_battery()) else 0  # on battery at either end
        self.store.set_session_env(s["id"], on_battery=battery, weather=weather, temp_c=temp,
                                   battery_pct=self.battery_percent())
        self._open_span(at)
        done = self.store.get_session(s["id"])
        seconds = session_seconds(done)
        apps = self._apps(s["started_at"], at + 1, session_id=s["id"])
        return {
            "success": True,
            "recap": {
                "id": s["id"],
                "task": s["task"],
                "startedAt": s["started_at"],
                "endedAt": at,
                "durationSeconds": seconds,
                "apps": apps[:3],
                "agents": A_.window(self.store, s["started_at"], at + 1),
            },
        }

    # --------------------------------------------------------------- state

    def _session_state(self) -> dict | None:
        s = self._session()
        if s is None:
            return None
        return {
            "id": s["id"],
            "task": s["task"],
            "startedAt": s["started_at"],
            "pausedMs": s["total_pause_ms"],
            "pauseStartedAt": s["pause_started_at"],
            # Focus XP is computed live by the client from the elapsed time
            # (1 per full FOCUS_SECONDS_PER_XP); this is the rest of the session's XP.
            "bonusXp": self.store.session_bonus_xp(s["id"]),
            "secondsPerXp": FOCUS_SECONDS_PER_XP,
            "autoPaused": self.auto_paused(),   # [] or reasons: idle, locked
            "agentTokens": A_.tokens_between(self.store, s["started_at"], T.now_ms() + 1),
        }

    def state(self, at: int) -> dict:
        today = T.day_start(at)
        tomorrow = T.add_days(today, 1)
        closed = self.store.closed_sessions(today, tomorrow)
        apps = self._apps(today, at + 1)

        history = []
        for i in range(6, -1, -1):
            start = T.add_days(today, -i)
            end = T.add_days(start, 1)
            secs = sum(session_seconds(r) for r in self.store.closed_sessions(start, end))
            history.append({"date": T.date_str(start), "minutes": secs // 60,
                            "tokens": A_.tokens_between(self.store, start, end)})

        w = self.window
        return {
            "at": at,
            "authenticated": True,
            "profile": self.profile(at),
            "challenge": self.challenge_state(at),
            "presence": self.presence_state(at),
            "medals": M.placard(self.store, at),
            "quest": self.quests.active(at),
            "seasonMedals": C.season_medals(self.store),
            "handle": self.handle(),
            "session": self._session_state(),
            "today": {"sessions": len(closed), "seconds": sum(session_seconds(r) for r in closed)},
            "window": {"app": self.alias(w.app), "title": w.title} if w else None,
            "idle": self.idle,
            "locked": self.locked,
            "history": history,
            "apps": apps[:5],
            "trackedSeconds": sum(a["seconds"] for a in apps),
            "todayDate": T.date_str(at),
            "dayStartHour": T.day_start_hour(),
            "agents": A_.window(self.store, T.day_start(at), at + 1),
            "coffee": self.coffee.now(at),
            "breakNudge": self.break_state(at),
            "breakNextAt": self.break_next_at(at),
            "coffeeNudge": self.coffee.nudge(at, self._working()),
        }

    # --------------------------------------------------------------- goals

    def goal_get(self, at: int) -> dict:
        goal = self.store.get_setting("hoursGoal")
        progress = None
        if goal:
            start, end = T.period_window(goal["period"], at)
            worked = sum(session_seconds(r) for r in self.store.closed_sessions(start, end + 1))
            progress = {"window": {"fromMs": start, "toMs": end}, "workedSeconds": worked}
        return {"success": True, "goal": goal, "progress": progress}

    def goal_set(self, value) -> dict:
        if value in (None, "off"):
            self.store.set_setting("hoursGoal", None)
            self._used("setting:goal")
            return {"success": True, "goal": None}
        if not isinstance(value, dict) or value.get("period") not in GOAL_LIMITS:
            raise Refused("Invalid goal")
        lo, hi = GOAL_LIMITS[value["period"]]
        hours = round(min(hi, max(lo, float(value.get("hours", 0)))) * 2) / 2
        goal = {"hours": hours, "period": value["period"]}
        self.store.set_setting("hoursGoal", goal)
        self._used("setting:goal")
        return {"success": True, "goal": goal}

    def session_names(self, at: int, top: int = 4, recent: int = 3) -> dict:
        """Names to start again from: the last `recent` used, then the `top`
        ones with the most focus time (not already in the first group). Every
        name used with its focus time, session count and last use, for
        completion while typing."""
        names: dict[str, dict] = {}
        for r in self.store.all_sessions():
            name = (r["task"] or "").strip()
            if not name:
                continue
            e = names.setdefault(name, {"name": name, "seconds": 0, "count": 0, "last": 0})
            e["seconds"] += session_seconds(r, until=at)
            e["count"] += 1
            e["last"] = max(e["last"], r["started_at"])
        all_names = list(names.values())
        last = sorted(all_names, key=lambda e: -e["last"])[:recent]
        taken = {e["name"] for e in last}
        most = [e for e in sorted(all_names, key=lambda e: (-e["seconds"], -e["last"]))
                if e["name"] not in taken][:top]
        return {"success": True, "mostWorked": most, "recent": last, "all": all_names}

    # --------------------------------------------------------------- stats

    def summary(self, window: dict | None, at: int) -> dict:
        """Focus over [fromMs, toMs]: sessions, deep sessions, switches, apps."""
        window = window or {}
        start = int(window.get("fromMs", T.week_start(at)))
        end = int(window.get("toMs", at))
        sessions = self.store.closed_sessions(start, end + 1)
        focus = sum(session_seconds(r) for r in sessions)
        s = self._session()
        if s is not None and s["started_at"] < end:
            focus += session_seconds(s, until=end)
        switches = self.store.span_count(start, end + 1, in_session=True)
        hours = focus / 3600
        return {
            "success": True,
            "fromMs": start,
            "toMs": end,
            "focusSeconds": focus,
            "sessions": len(sessions),
            "deepSessions": sum(1 for r in sessions if session_seconds(r) >= DEEP_SESSION_SECONDS),
            "switchesPerHour": round(switches / hours, 1) if hours >= 0.25 else None,
            "apps": self._apps(start, end + 1)[:8],
        }

    def set_hidden_apps(self, apps, at: int) -> dict:
        if not isinstance(apps, list) or not all(isinstance(a, str) for a in apps):
            raise Refused("Invalid app list")
        clean = sorted({a.strip() for a in apps if a.strip()})
        self.store.set_setting("hiddenApps", clean)
        self._split(at)  # the focused app may have just become hidden, or visible
        self._used("setting:apps")
        return {"success": True, "hiddenApps": clean}

    def set_aliases(self, aliases, at: int) -> dict:
        if not isinstance(aliases, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()
        ):
            raise Refused("Invalid aliases")
        clean = {k.strip(): v.strip() for k, v in aliases.items() if k.strip() and v.strip() and k.strip() != v.strip()}
        self.store.set_setting("aliases", clean)
        self._split(at)  # an alias can make the focused app hidden, or visible
        self._used("setting:aliases")
        return {"success": True, "aliases": clean}

    def known_apps(self, days: int, at: int) -> dict:
        """Raw app names seen over the last `days` days, busiest first."""
        start = T.add_days(T.day_start(at), -max(1, int(days)))
        rows = self.store.app_seconds(start, at + 1)
        return {"success": True, "apps": [{"app": r["app"], "alias": self.alias(r["app"]), "seconds": r["seconds"]} for r in rows]}

    # ------------------------------------------------------------- history

    def _day(self, start: int, until: int | None = None, now: int | None = None) -> dict:
        """Focus (sessions, clipped to the day) and tracked (apps) seconds from `start`."""
        end = T.add_days(start, 1)
        stop = min(end, until) if until is not None else end
        now = now if now is not None else (until if until is not None else stop)
        focus = sum(clipped_seconds(r, start, stop, now) for r in self.store.overlapping_sessions(start, stop))
        tracked = sum(a["seconds"] for a in self.store.app_seconds(start, stop))
        return {"date": T.date_str(start), "fromMs": start, "focusSeconds": focus, "trackedSeconds": tracked}

    def days(self, week_offset: int, at: int) -> dict:
        """Sun-Sat of the week `week_offset` weeks back (0 = this week)."""
        offset = max(0, min(520, int(week_offset or 0)))
        monday = T.add_days(T.week_start(at), -7 * offset)
        today = T.day_start(at)
        out = []
        for i in range(7):
            start = T.add_days(monday, i)
            if start > today:
                out.append({"date": T.date_str(start), "fromMs": start, "focusSeconds": 0, "trackedSeconds": 0, "future": True})
            else:
                out.append(self._day(start, until=at if start == today else None, now=at))
        first = self.store.db.execute(
            "SELECT MIN(started_at) FROM (SELECT started_at FROM sessions UNION ALL SELECT started_at FROM focus_spans)"
        ).fetchone()[0]
        for d in out:                       # agent tokens, every machine
            d["tokens"] = 0 if d.get("future") else A_.tokens_between(self.store, d["fromMs"], T.add_days(d["fromMs"], 1))
        has_older = first is not None and first < monday
        return {"success": True, "weekOffset": offset, "days": out, "hasOlder": has_older,
                "isoWeek": T.iso_week(monday)}

    def insights(self, at: int) -> dict:
        today = T.day_start(at)
        yesterday = T.add_days(today, -1)
        same_time = yesterday + (at - today)  # yesterday, up to this time of day
        now_day = self._day(today, until=at, now=at)
        then_day = self._day(yesterday, until=same_time, now=at)
        apps = self._apps(today, at + 1)
        week = self.days(0, at)["days"]
        past = [d for d in week if not d.get("future")]
        busiest = max(past, key=lambda d: d["trackedSeconds"], default=None)
        return {
            "success": True,
            "today": now_day,
            "yesterdaySameTime": then_day,
            "topApp": apps[0] if apps else None,
            "busiestDay": busiest if busiest and busiest["trackedSeconds"] > 0 else None,
        }

    # --------------------------------------------------------------- tasks
    # Prometheus' own list. Obsidian todos are only offered as suggestions by
    # the bar plugin; nothing here is written back to the journal.

    DAY_MS = 24 * 3600 * 1000

    @classmethod
    def task_xp(cls, created_at: int, at: int) -> int:
        """1 XP, plus 1 for every full 24 h since the task was created."""
        return 1 + max(0, (at - created_at) // cls.DAY_MS)

    def _task(self, row, at: int | None = None) -> dict:
        out = {"id": row["id"], "text": row["text"], "source": row["source"], "createdAt": row["created_at"]}
        if row["done_at"] is not None:
            out["xp"] = row["xp"] if row["xp"] is not None else self.task_xp(row["created_at"], row["done_at"])
        elif at is not None:
            out["xp"] = self.task_xp(row["created_at"], at)
        return out

    def tasks_list(self, at: int) -> dict:
        today = T.day_start(at)
        done = self.store.done_tasks_between(today, T.add_days(today, 1))
        return {
            "success": True,
            "tasks": [self._task(r, at) for r in self.store.open_tasks()],
            "doneToday": len(done),
            "done": [dict(self._task(r), doneAt=r["done_at"]) for r in done],
            "xpToday": sum(self._task(r)["xp"] for r in done),
        }

    def task_add(self, text, source, at: int) -> dict:
        text = (text or "").strip() if isinstance(text, str) else ""
        if not text:
            raise Refused("Empty task")
        if len(text) > 500:
            raise Refused("Task too long")
        source = source if source in ("manual", "obsidian", "procrastinated") else "manual"
        existing = self.store.open_task_by_text(text)
        if existing is not None:  # the same open task twice is never useful
            return {"success": True, "task": self._task(existing, at), "existed": True}
        tid = self.store.add_task(text, source, at)
        return {"success": True, "task": self._task(self.store.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), at), "existed": False}

    def task_complete(self, tid, at: int) -> dict:
        if self._session() is None:
            raise Refused("Start a session to check a task")
        row = self.store.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone() if isinstance(tid, str) else None
        xp = self.task_xp(row["created_at"], at) if row is not None else 0
        if row is None or not self.store.complete_task(tid, at, self._session()["id"], xp):
            raise Refused("Task not found or already done")
        if not self.store.open_tasks():  # the list just went empty by finishing, not deleting
            self.store.add_event("inbox_zero", at, self._session()["id"])
        return {"success": True, "xp": xp}

    def task_reopen(self, tid) -> dict:
        """Back to the to-do list. Refused if the same text is already open."""
        if self._session() is None:
            raise Refused("Start a session to change a task")
        row = self.store.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone() if isinstance(tid, str) else None
        if row is None or row["done_at"] is None:
            raise Refused("Task not found or already to do")
        if self.store.open_task_by_text(row["text"]) is not None:
            # Already back in the list (e.g. procrastinated): drop the done copy.
            self.store.db.execute("DELETE FROM tasks WHERE id=?", (tid,))
            return {"success": True, "merged": True}
        self.store.reopen_task(tid)
        return {"success": True, "merged": False}

    def set_hidden_words(self, words, at: int) -> dict:
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise Refused("Invalid word list")
        clean, seen = [], set()
        for w in words:
            w = w.strip()
            if w and w.casefold() not in seen:
                seen.add(w.casefold())
                clean.append(w)
        self.store.set_setting("hiddenTitleWords", clean)
        self._split(at)  # the focused title may contain a word just added, or removed
        self._used("setting:words")
        return {"success": True, "hiddenTitleWords": clean}

    # ------------------------------------------------------------ timeline

    TIMELINE_GAP_MS = 60_000  # shorter gaps between stretches of one app are bridged

    def timeline(self, window, at: int) -> dict:
        """The day as app stretches (aliases applied, merged) and session intervals."""
        window = window or {}
        start = int(window.get("fromMs", T.day_start(at)))
        end = min(int(window.get("toMs", T.add_days(start, 1))), at)
        names = self.aliases
        segments: list[dict] = []
        for r in self.store.spans_between(start, end):
            app = names.get(r["app"], r["app"])
            last = segments[-1] if segments else None
            if last and last["app"] == app and r["s"] - last["end"] <= self.TIMELINE_GAP_MS:
                last["end"] = max(last["end"], r["e"])
            else:
                segments.append({"app": app, "start": r["s"], "end": r["e"]})
        sessions = []
        for r in self.store.overlapping_sessions(start, end):
            s_end = r["ended_at"] if r["ended_at"] is not None else at
            sessions.append({"task": r["task"], "start": max(r["started_at"], start), "end": min(s_end, end)})
        # Agent tokens per quarter hour (estimated ones apart: spread over a gap).
        agents = {}
        for slot, tokens, est in self.store.db.execute(
                "SELECT slot, SUM(tokens), MAX(estimated) FROM agent_usage WHERE slot >= ? AND slot < ? "
                "GROUP BY slot", (start, end)):
            q = slot - (slot - start) % 900_000
            a = agents.setdefault(q, {"start": q, "tokens": 0, "estimated": False})
            a["tokens"] += tokens
            a["estimated"] = a["estimated"] or bool(est)
        return {"success": True, "fromMs": start, "toMs": end, "segments": segments, "sessions": sessions,
                "agents": sorted(agents.values(), key=lambda a: a["start"])}

    # ------------------------------------------------------------ day start

    # What the player did with the tool itself (settings changed, cards
    # generated, tabs opened...): recorded as events, for the achievements
    # that reward exploring it.
    UI_EVENTS = {"bio"} | {f"tab:{t}" for t in ("session", "tasks", "quests", "leagues", "seasons",
                                                 "achievements", "stats", "leaderboard", "settings")}

    def _used(self, kind: str) -> None:
        self.store.add_event(kind, T.now_ms(), None)

    def ui_event(self, kind) -> dict:
        """A UI action worth remembering (a tab opened once, a bio read)."""
        if kind not in self.UI_EVENTS:
            raise Refused("Unknown UI event")
        if kind.startswith("tab:") and self.store.count_events(kind) > 0:
            return {"success": True}           # a tab counts once
        self._used(kind)
        return {"success": True}

    HANDLE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")

    def handle(self) -> str:
        return self.store.get_setting("handle", "") or ""

    def set_handle(self, handle) -> dict:
        """The player's @handle, shown on the share card. Letters, digits, _ . -"""
        h = handle.strip().lstrip("@") if isinstance(handle, str) else None
        if h is None or len(h) > 32 or not set(h) <= self.HANDLE_CHARS:
            raise Refused("Invalid handle: up to 32 letters, digits, _ . -")
        self.store.set_setting("handle", h)
        self._used("setting:handle")
        return {"success": True, "handle": h}

    SHARE_FORMATS = ("gif", "apng")

    def share_format(self) -> str:
        f = self.store.get_setting("shareFormat", "gif")
        return f if f in self.SHARE_FORMATS else "gif"

    def set_share_format(self, fmt) -> dict:
        if fmt not in self.SHARE_FORMATS:
            raise Refused("Invalid export format (gif or apng)")
        self.store.set_setting("shareFormat", fmt)
        self._used("setting:export:" + fmt)
        return {"success": True, "format": fmt}

    def share(self, at: int) -> dict:
        """Everything the share card shows."""
        self._used("share_card")
        ledger = C.Ledger(self.store, at)
        leagues = C.leagues(ledger)
        league = leagues["current"]
        # A stamp for each shining league, inked once per round finished in it.
        # Only leagues with at least one round finished in them, the rarest
        # (highest) first.
        stamps = [{"index": i, "name": C.LEAGUES[i], "color": C.LEAGUE_COLORS[i],
                   "count": sum(1 for w in leagues["history"] if w["before"] == i)}
                  for i in reversed(range(C.SHINING_FROM, len(C.LEAGUES)))]
        stamps = [st for st in stamps if st["count"] > 0]
        seasons = C.seasons(ledger)
        first = ledger.first_day
        return {
            "success": True, "handle": self.handle(), "profile": self.profile(at),
            "league": dict({k: league[k] for k in ("name", "color", "shining")}, index=league["league"]),
            "seasons": [{k: s[k] for k in ("label", "grade", "xp", "goal", "hardGoal", "running")}
                        for s in reversed(seasons)],
            "firstDay": first.isoformat() if first else None,
            "medals": M.placard(self.store, at), "seasonMedals": C.season_medals(self.store),
            "legendary": self._legendary_unlocked(),
            "format": self.share_format(),
            "stamps": stamps,
            "serviceNumber": self._service_number(first),
            "agents": A_.window(self.store, 0, at + 1),
        }

    def _legendary_unlocked(self) -> list[str]:
        """Names of the legendary achievement tiers unlocked, best first."""
        unlocked = self.store.unlocked_achievements()
        out = []
        for f in A.FAMILIES:
            for i, t in enumerate(f.thresholds):
                if f.tier_id(i) in unlocked and f.rarity(i) == "legendary":
                    out.append((f.xp(i), f.name(t)))
        return [name for _, name in sorted(out, reverse=True)]

    def _service_number(self, first) -> str:
        """A stable service number, from the handle and the enlistment day."""
        import hashlib
        h = hashlib.sha1(f"{self.handle()}|{first}".encode()).hexdigest().upper()
        return f"PRM-{h[:4]}-{h[4:8]}"

    def set_day_start(self, hour, at: int) -> dict:
        if not isinstance(hour, (int, float)) or not 0 <= int(hour) <= 12:
            raise Refused("Invalid day start hour (0 to 12)")
        self.store.set_setting("dayStartHour", int(hour))
        T.set_day_start_hour(int(hour))
        self._used("setting:daystart")
        return {"success": True, "dayStartHour": T.day_start_hour()}

    # -------------------------------------------------------------- profile

    @staticmethod
    def level_for(xp: int) -> dict:
        """Level 1 at 0 XP; level 2 costs 100, then each level 50 more than the last."""
        level, cost, left = 1, FIRST_LEVEL_COST, max(0, int(xp))
        while left >= cost:
            left -= cost
            level += 1
            cost += LEVEL_COST_STEP
        return {"level": level, "levelXp": left, "levelCost": cost}

    def challenge_xp(self) -> int:
        return self.store.challenge_xp_total()

    # ----------------------------------------------------------- challenges

    @staticmethod
    def challenge_bonus(index: int) -> int:
        """Bonus of the challenge at `index` (0 = first): 2, 3, 5 (rounded up from .5)."""
        return int(CHALLENGE_BASE_XP * CHALLENGE_XP_GROWTH ** index + 0.5)

    def _offer_challenge(self, s, at: int, chained: bool) -> tuple[str, dict]:
        index = self.store.won_challenges(s["id"])
        xp = self.challenge_bonus(index)
        cid = self.store.add_challenge(s["id"], at, CHALLENGE_MINUTES, xp)
        return ("offer", {"id": cid, "minutes": CHALLENGE_MINUTES, "xp": xp, "chained": chained,
                          "index": index + 1, "max": CHALLENGE_MAX_PER_SESSION})

    def _challenge_left(self, ch, s, at: int) -> int:
        """Focus seconds still owed to an active challenge."""
        done = session_seconds(s, until=at) - (ch["start_focus"] or 0)
        return max(0, ch["minutes"] * 60 - done)

    def challenge_state(self, at: int) -> dict | None:
        s = self._session()
        if s is None:
            return None
        ch = self.store.last_challenge(s["id"])
        if ch is None or ch["state"] not in ("offered", "active"):
            return None
        won = self.store.won_challenges(s["id"])
        out = {"id": ch["id"], "state": ch["state"], "minutes": ch["minutes"], "xp": ch["xp"],
               "index": won + 1, "max": CHALLENGE_MAX_PER_SESSION}
        if ch["state"] == "active":
            out["remainingSeconds"] = self._challenge_left(ch, s, at)
        return out

    def update_challenge(self, at: int) -> list[tuple[str, dict]]:
        """Advance the challenge of the open session; returns events to announce."""
        s = self._session()
        if s is None:
            return []
        ch = self.store.last_challenge(s["id"])
        if ch is not None and ch["state"] == "active" and self._challenge_left(ch, s, at) <= 0:
            self.store.update_challenge(ch["id"], state="won", ended_at=at)
            events = [("won", {"minutes": ch["minutes"], "xp": ch["xp"]})]
            # A won challenge chains into the next, worth more, up to the max.
            if s["pause_started_at"] is None and self.store.won_challenges(s["id"]) < CHALLENGE_MAX_PER_SESSION:
                events.append(self._offer_challenge(s, at, chained=True))
            return events
        if ch is not None and ch["state"] == "offered" and at - ch["offered_at"] > CHALLENGE_OFFER_TTL_MS:
            self.store.update_challenge(ch["id"], state="expired", ended_at=at)
            return [("expired", {"id": ch["id"]})]
        if ch is None and s["pause_started_at"] is None and session_seconds(s, until=at) >= CHALLENGE_OFFER_AFTER_SECONDS:
            return [self._offer_challenge(s, at, chained=False)]
        return []

    def _offered(self, cid=None):
        s = self._session()
        ch = self.store.last_challenge(s["id"]) if s is not None else None
        if ch is None or ch["state"] != "offered" or (cid is not None and ch["id"] != cid):
            raise Refused("No challenge offered")
        return s, ch

    def challenge_accept(self, cid, at: int) -> dict:
        s, ch = self._offered(cid)
        self.store.update_challenge(ch["id"], state="active", answered_at=at, start_focus=session_seconds(s, until=at))
        return {"success": True, "minutes": ch["minutes"]}

    def challenge_decline(self, cid, at: int) -> dict:
        _, ch = self._offered(cid)
        self.store.update_challenge(ch["id"], state="declined", answered_at=at, ended_at=at)
        return {"success": True}

    def challenge_abandon(self, at: int) -> dict:
        s = self._session()
        ch = self.store.last_challenge(s["id"]) if s is not None else None
        if ch is None or ch["state"] != "active":
            raise Refused("No challenge running")
        self.store.update_challenge(ch["id"], state="abandoned", ended_at=at)
        from .store import ABANDON_PENALTY
        return {"success": True, "penalty": ABANDON_PENALTY}

    def profile(self, at: int) -> dict:
        # Per session, so a session's own counter adds up to the total.
        focus_xp = sum(session_seconds(r, until=at) // FOCUS_SECONDS_PER_XP for r in self.store.all_sessions())
        task_xp = sum(self._task(r)["xp"] for r in self.store.done_tasks())
        bonus = self.challenge_xp()
        trophies = self.store.achievement_xp_total()
        decorations = self.store.medal_xp_total() + C.season_xp_total(self.store)
        quest_xp = self.quests.xp_total()
        agent_xp = sum(A_.xp_for(t) for t in A_.tokens_by_day(self.store).values())
        total = focus_xp + task_xp + bonus + trophies + decorations + quest_xp + agent_xp
        return dict(self.level_for(total), xp=total, focusXp=focus_xp, taskXp=task_xp,
                    challengeXp=bonus, achievementXp=trophies, medalXp=decorations, questXp=quest_xp,
                    agentXp=agent_xp)

    # --------------------------------------------------------------- quests

    def _quest(self, fn, *args):
        try:
            return fn(*args)
        except Q.QuestError as e:
            raise Refused(str(e)) from None

    def quests_list(self, at: int) -> dict:
        return self.quests.listing(at)

    def quest_add(self, title, kind, at: int) -> dict:
        return self._quest(self.quests.add, title, kind, at)

    def quest_activate(self, qid, at: int) -> dict:
        return self._quest(self.quests.activate, qid, at, self._working())

    def quest_deactivate(self, qid, at: int) -> dict:
        return self._quest(self.quests.deactivate, qid, at)

    def quest_delete(self, qid, at: int) -> dict:
        return self._quest(self.quests.delete, qid, at)

    def quest_complete(self, qid, at: int) -> dict:
        return self._quest(self.quests.complete, qid, at)

    def quest_uncomplete(self, qid, at: int) -> dict:
        return self._quest(self.quests.uncomplete, qid, at)

    # ---------------------------------------------------------------- medals

    def check_medals(self, at: int, history: bool = False) -> list[dict]:
        return M.evaluate(self.store, at, history=history) + C.check_season_medals(self.store, C.Ledger(self.store, at), at)

    # ---------------------------------------------- leagues, seasons, boards

    def leagues(self, at: int) -> dict:
        out = C.leagues(C.Ledger(self.store, at))
        return dict(out, success=True, leagues=[{"name": n, "color": c, "floor": f} for n, c, f in
                                                zip(C.LEAGUES, C.LEAGUE_COLORS, C.PROMOTION_MIN + [None])])

    def seasons(self, at: int) -> dict:
        seasons = C.seasons(C.Ledger(self.store, at))
        for s in seasons:      # the medal's colors, won or still to win
            s["colors"] = C.pending_colors(self.store, s["key"])
        return {"success": True, "seasons": seasons, "medals": C.season_medals(self.store)}

    def agents_stats(self, at: int) -> dict:
        sessions = [(r["started_at"], r["ended_at"] if r["ended_at"] is not None else at)
                    for r in self.store.all_sessions()]
        return A_.stats(self.store, at, sessions)

    def leaderboard_remove_quest(self, qid, at: int) -> dict:
        row = self.store.db.execute("SELECT done_at FROM quests WHERE id=?", (qid,)).fetchone() if isinstance(qid, str) else None
        if row is not None and row["done_at"] is not None:
            self._used("board_remove_done")
        return self._quest(self.quests.remove_from_board, qid, at)

    def leaderboard(self, board, at: int) -> dict:
        board = board if board in C.BOARDS else "days"
        quests = self.quests.summary(at) if board == "quests" else None
        return C.leaderboard(self.store, C.Ledger(self.store, at), board, quests)

    def medals_list(self, at: int) -> dict:
        return M.catalogue(self.store, at)

    # ---------------------------------------------------------- achievements

    def check_achievements(self, at: int) -> list[dict]:
        """Unlock what the records now justify; returns the new ones."""
        p = self.profile(at)
        base = p["xp"] - p["achievementXp"]
        return A.evaluate(self.store, at, lambda xp: self.level_for(xp)["level"], base)

    def achievements_list(self, at: int) -> dict:
        return A.catalogue(self.store, at, self.profile(at)["level"])

    def task_delete(self, tid) -> dict:
        """Remove an open task, without checking it (so without its XP)."""
        if not isinstance(tid, str) or not self.store.delete_open_task(tid):
            raise Refused("Task not found or already done")
        return {"success": True}

    # ------------------------------------------------------------- presence

    # The presence clock is kept in the settings, tied to the session, so a
    # daemon restart does not start the 20 minutes over again.

    def _load_presence(self) -> None:
        saved = self.store.get_setting("presence") or {}
        s = self._session()
        if s is not None and saved.get("session") == s["id"]:
            self.presence_since = saved.get("since")
            self.presence_asked_at = saved.get("asked")

    def _save_presence(self) -> None:
        s = self._session()
        self.store.set_setting("presence", {
            "session": s["id"] if s is not None else None,
            "since": self.presence_since, "asked": self.presence_asked_at})

    def _present(self, at: int) -> None:
        self.presence_since = at
        self.presence_asked_at = None
        self._save_presence()

    def presence_state(self, at: int) -> dict | None:
        if self.presence_asked_at is None:
            return None
        waited = at - self.presence_asked_at
        return {"askedAt": self.presence_asked_at, "flashing": waited >= PRESENCE_FLASH_AFTER_MS,
                "pauseAt": self.presence_asked_at + PRESENCE_TIMEOUT_MS}

    def update_presence(self, at: int) -> list[tuple[str, dict]]:
        """Ask, then pause after the timeout. Returns events to announce."""
        s = self._session()
        if s is None or s["pause_started_at"] is not None:
            self.presence_asked_at = None
            return []
        if self.presence_since is None:
            self.presence_since = at
            self._save_presence()
        if self.presence_asked_at is None:
            if at - self.presence_since >= self.presence_every_minutes() * 60 * 1000:
                self.presence_asked_at = at
                self.store.add_event("presence_asked", at, s["id"])
                self._save_presence()
                return [("presence", {})]
            return []
        if at - self.presence_asked_at >= PRESENCE_TIMEOUT_MS:
            start = max(self.presence_asked_at, s["started_at"], self.last_resume_at)
            self.store.set_pause(s["id"], start, s["total_pause_ms"])
            self.store.set_setting("autoPause", {})   # a plain pause: resumed by hand
            self.presence_asked_at = None
            self._save_presence()
            self.store.add_event("absent", at, s["id"])
            self._split(at)
            return [("absent", {})]
        return []

    # ---------------------------------------------------------------- breaks
    #
    # Time worked without a break: a pause of 5 minutes or more (by hand,
    # idle, away) resets it. Past the setting, a "Break?" pill: Pause pauses
    # the session, Later asks again in 20 minutes. Other reasons (sitting
    # still, a racing heart) come from health.py when a watch is linked.

    def _breaks(self) -> dict:
        return self.store.get_setting("breaks") or {}

    def update_coffee(self, at: int) -> list[tuple[str, dict]]:
        self.coffee.update(at, self._working())
        return []

    def update_breaks(self, at: int) -> list[tuple[str, dict]]:
        s = self._session()
        st = self._breaks()
        if s is None:
            if st:
                self.store.set_setting("breaks", {})
            return []
        if st.get("session") != s["id"]:
            st = {"session": s["id"], "since": s["started_at"]}
        if s["pause_started_at"] is not None:
            if at - s["pause_started_at"] >= BREAK_RESET_MS:
                st.update(since=None, asked=None, reason=None)
            self.store.set_setting("breaks", st)
            return []
        if st.get("since") is None:
            st["since"] = at
        out = []
        if st.get("asked") is None and at >= (st.get("snoozed") or 0):
            reason = None
            every = self.break_every_minutes()
            worked = (at - st["since"]) // 60_000
            if every and worked >= every:
                reason = f"{worked} min without a break"
            elif self.health is not None:
                reason = self.health.nudge(at)
            if reason:
                st.update(asked=at, reason=reason)
                self.store.add_event("break_asked", at, s["id"])
                out.append(("break", {"reason": reason}))
        self.store.set_setting("breaks", st)
        return out

    def break_state(self, at: int) -> dict | None:
        st = self._breaks()
        if not st.get("asked"):
            return None
        return {"askedAt": st["asked"], "reason": st.get("reason") or "",
                "workedMinutes": (at - st["since"]) // 60_000 if st.get("since") else 0}

    def break_next_at(self, at: int) -> int | None:
        """When "Break?" is due in the running session (None: paused, off)."""
        s = self._session()
        st = self._breaks()
        every = self.break_every_minutes()
        if s is None or s["pause_started_at"] is not None or not every or st.get("session") != s["id"]:
            return None
        since = st.get("since") or at
        return max(since + every * 60_000, st.get("snoozed") or 0)

    def break_take(self, at: int) -> dict:
        st = self._breaks()
        st.update(asked=None, reason=None, snoozed=None)
        self.store.set_setting("breaks", st)
        self.store.add_event("break_taken", at, None)
        return self.pause(at)

    def break_later(self, at: int) -> dict:
        st = self._breaks()
        st.update(asked=None, reason=None, snoozed=at + BREAK_SNOOZE_MS)
        self.store.set_setting("breaks", st)
        self.store.add_event("break_snoozed", at, None)
        return {"success": True}

    def break_every_minutes(self) -> int:
        return int(self.store.get_setting("breakEveryMinutes", BREAK_EVERY_MINUTES))

    def set_break_every(self, minutes) -> dict:
        try:
            m = int(minutes)
        except (TypeError, ValueError):
            raise Refused("Invalid minutes") from None
        lo, hi = BREAK_MINUTES_RANGE
        m = 0 if m <= 0 else max(lo, min(hi, m))
        self.store.set_setting("breakEveryMinutes", m)
        return {"success": True, "minutes": m}

    def presence_every_minutes(self) -> int:
        return int(self.store.get_setting("presenceEveryMinutes", PRESENCE_EVERY_MINUTES))

    def set_presence_every(self, minutes) -> dict:
        lo, hi = PRESENCE_MINUTES_RANGE
        if not isinstance(minutes, (int, float)) or not lo <= int(minutes) <= hi:
            raise Refused(f"Invalid presence interval ({lo} to {hi} min)")
        self.store.set_setting("presenceEveryMinutes", int(minutes))
        self._used("setting:presence")
        return {"success": True, "minutes": int(minutes)}

    REFLEX_MS = 10_000

    def presence_confirm(self, at: int) -> dict:
        asked = self.presence_asked_at
        if asked is not None:
            s0 = self._session()
            self.store.add_event("presence_answered", at, s0["id"] if s0 is not None else None)
        if asked is not None and at - asked < self.REFLEX_MS:
            s = self._session()
            self.store.add_event("reflex", at, s["id"] if s is not None else None)
        self._present(at)
        return {"success": True}
