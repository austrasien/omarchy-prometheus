"""Sessions, focus tracking and the state object the bar renders.

Pure logic over a Store and an injectable clock, so it can be tested without
Hyprland or a socket. Every public method takes `at` (epoch ms) when it
records time; the daemon passes now_ms().
"""

from __future__ import annotations

from dataclasses import dataclass

from . import timeutil as T
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
PRESENCE_EVERY_MS = 45 * 60 * 1000
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
        T.set_day_start_hour(self.store.get_setting("dayStartHour", T.DEFAULT_DAY_START_HOUR))
        self.window: Window | None = None
        self.idle = False
        self.locked = False
        self.last_resume_at = 0       # a backdated auto-pause never reaches before this
        self.presence_since = None    # last proof of presence for the running session
        self.presence_asked_at = None
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

    def auto_paused(self) -> list[str]:
        s = self._session()
        state = self._auto_state()
        return list(state.get("reasons", [])) if s is not None and state.get("session") == s["id"] else []

    # ------------------------------------------------------------ sessions

    def start(self, task: str | None, at: int) -> dict:
        if self._session() is not None:
            raise Refused("Une session est déjà en cours")
        task = (task or "").strip() or None
        self.store.create_session(task, at)
        self.store.set_setting("autoPause", {})
        self.last_resume_at = at
        self._present(at)
        self._split(at)
        return {"success": True}

    def pause(self, at: int) -> dict:
        s = self._session()
        if s is None:
            raise Refused("Aucune session en cours")
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
            raise Refused("Aucune session en cours")
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
            raise Refused("Aucune session en cours")
        ch = self.store.last_challenge(s["id"])
        if ch is not None and ch["state"] == "active":
            left = self._challenge_left(ch, s, at)
            raise Refused(f"Défi en cours : encore {max(1, -(-left // 60))} min. Abandonne-le pour terminer.")
        if ch is not None and ch["state"] == "offered":
            self.store.update_challenge(ch["id"], state="expired", ended_at=at)
        total = s["total_pause_ms"]
        if s["pause_started_at"] is not None:
            total += max(0, at - s["pause_started_at"])
        self._close_span(at)
        self.store.finish_session(s["id"], at, total, reason)
        self.store.set_setting("autoPause", {})
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
            history.append({"date": T.date_str(start), "minutes": secs // 60})

        w = self.window
        return {
            "at": at,
            "authenticated": True,
            "profile": self.profile(at),
            "challenge": self.challenge_state(at),
            "presence": self.presence_state(at),
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
            return {"success": True, "goal": None}
        if not isinstance(value, dict) or value.get("period") not in GOAL_LIMITS:
            raise Refused("Objectif invalide")
        lo, hi = GOAL_LIMITS[value["period"]]
        hours = round(min(hi, max(lo, float(value.get("hours", 0)))) * 2) / 2
        goal = {"hours": hours, "period": value["period"]}
        self.store.set_setting("hoursGoal", goal)
        return {"success": True, "goal": goal}

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
            raise Refused("Liste d'apps invalide")
        clean = sorted({a.strip() for a in apps if a.strip()})
        self.store.set_setting("hiddenApps", clean)
        self._split(at)  # the focused app may have just become hidden, or visible
        return {"success": True, "hiddenApps": clean}

    def set_aliases(self, aliases, at: int) -> dict:
        if not isinstance(aliases, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()
        ):
            raise Refused("Alias invalides")
        clean = {k.strip(): v.strip() for k, v in aliases.items() if k.strip() and v.strip() and k.strip() != v.strip()}
        self.store.set_setting("aliases", clean)
        self._split(at)  # an alias can make the focused app hidden, or visible
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
        """Mon-Sun of the week `week_offset` weeks back (0 = this week)."""
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
            raise Refused("Tâche vide")
        if len(text) > 500:
            raise Refused("Tâche trop longue")
        source = source if source in ("manual", "obsidian", "procrastinated") else "manual"
        existing = self.store.open_task_by_text(text)
        if existing is not None:  # the same open task twice is never useful
            return {"success": True, "task": self._task(existing, at), "existed": True}
        tid = self.store.add_task(text, source, at)
        return {"success": True, "task": self._task(self.store.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone(), at), "existed": False}

    def task_complete(self, tid, at: int) -> dict:
        if self._session() is None:
            raise Refused("Lance une session pour cocher une tâche")
        row = self.store.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone() if isinstance(tid, str) else None
        xp = self.task_xp(row["created_at"], at) if row is not None else 0
        if row is None or not self.store.complete_task(tid, at, self._session()["id"], xp):
            raise Refused("Tâche introuvable ou déjà faite")
        return {"success": True, "xp": xp}

    def task_reopen(self, tid) -> dict:
        """Back to the to-do list. Refused if the same text is already open."""
        if self._session() is None:
            raise Refused("Lance une session pour modifier une tâche")
        row = self.store.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone() if isinstance(tid, str) else None
        if row is None or row["done_at"] is None:
            raise Refused("Tâche introuvable ou déjà à faire")
        if self.store.open_task_by_text(row["text"]) is not None:
            # Already back in the list (e.g. procrastinated): drop the done copy.
            self.store.db.execute("DELETE FROM tasks WHERE id=?", (tid,))
            return {"success": True, "merged": True}
        self.store.reopen_task(tid)
        return {"success": True, "merged": False}

    def set_hidden_words(self, words, at: int) -> dict:
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise Refused("Liste de mots invalide")
        clean, seen = [], set()
        for w in words:
            w = w.strip()
            if w and w.casefold() not in seen:
                seen.add(w.casefold())
                clean.append(w)
        self.store.set_setting("hiddenTitleWords", clean)
        self._split(at)  # the focused title may contain a word just added, or removed
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
        return {"success": True, "fromMs": start, "toMs": end, "segments": segments, "sessions": sessions}

    # ------------------------------------------------------------ day start

    def set_day_start(self, hour, at: int) -> dict:
        if not isinstance(hour, (int, float)) or not 0 <= int(hour) <= 12:
            raise Refused("Heure de début de journée invalide (0 à 12)")
        self.store.set_setting("dayStartHour", int(hour))
        T.set_day_start_hour(int(hour))
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
            raise Refused("Aucun défi proposé")
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
            raise Refused("Aucun défi en cours")
        self.store.update_challenge(ch["id"], state="abandoned", ended_at=at)
        return {"success": True}

    def profile(self, at: int) -> dict:
        # Per session, so a session's own counter adds up to the total.
        focus_xp = sum(session_seconds(r, until=at) // FOCUS_SECONDS_PER_XP for r in self.store.all_sessions())
        task_xp = sum(self._task(r)["xp"] for r in self.store.done_tasks())
        bonus = self.challenge_xp()
        total = focus_xp + task_xp + bonus
        return dict(self.level_for(total), xp=total, focusXp=focus_xp, taskXp=task_xp, challengeXp=bonus)

    def task_delete(self, tid) -> dict:
        """Remove an open task, without checking it (so without its XP)."""
        if not isinstance(tid, str) or not self.store.delete_open_task(tid):
            raise Refused("Tâche introuvable ou déjà faite")
        return {"success": True}

    # ------------------------------------------------------------- presence

    def _present(self, at: int) -> None:
        self.presence_since = at
        self.presence_asked_at = None

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
        if self.presence_asked_at is None:
            if at - self.presence_since >= PRESENCE_EVERY_MS:
                self.presence_asked_at = at
                return [("presence", {})]
            return []
        if at - self.presence_asked_at >= PRESENCE_TIMEOUT_MS:
            start = max(self.presence_asked_at, s["started_at"], self.last_resume_at)
            self.store.set_pause(s["id"], start, s["total_pause_ms"])
            self.store.set_setting("autoPause", {})   # a plain pause: resumed by hand
            self.presence_asked_at = None
            self._split(at)
            return [("absent", {})]
        return []

    def presence_confirm(self, at: int) -> dict:
        self._present(at)
        return {"success": True}
