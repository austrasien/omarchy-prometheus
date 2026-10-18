"""Quests: goals that take more than one sitting.

Three kinds:
- daily: done again every logical day; each day's completion is kept.
- short: something to come back to over a few days.
- long: something to follow for more than a week.

One quest at a time is active: it is shown under the title of the panel, and
every logical day on which a session runs while it is active counts as a day
worked on it. Short and long quests pay more for each day worked, up to a cap,
so the reward follows the effort actually put in, not the calendar.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid

from . import timeutil as T
from .store import clipped_seconds
from .medals import AZURE, CYAN, GREEN, INDIGO, LIME, ORANGE, PINK, RED, SPRING, VIOLET

KINDS = ("daily", "short", "long")
TITLE_MAX = 300

# XP: base + per day worked, capped. A daily quest earns DAILY_XP, plus 1 for
# each consecutive day it was already done before today, up to DAILY_STREAK_MAX.
DAILY_XP = 5
DAILY_STREAK_MAX = 5
SHORT_BASE, SHORT_PER_DAY, SHORT_CAP = 10, 5, 40
LONG_BASE, LONG_PER_DAY, LONG_CAP = 30, 5, 150

# Each open quest has its own color, from the medals' ten vivid hues. The
# first quest is red, and so is any new quest while no open one is red; the
# others draw one of the colors left. So no two open quests share a color,
# and there can be at most ten of them.
FIRST_COLOR = RED
SWEEP_MIN = 3

COLORS = (RED, ORANGE, LIME, GREEN, SPRING, CYAN, AZURE, INDIGO, VIOLET, PINK)


class QuestError(Exception):
    pass


def worth(kind: str, days_worked: int, streak: int = 0) -> int:
    if kind == "daily":
        return DAILY_XP + min(DAILY_STREAK_MAX, max(0, streak))
    base, per, cap = (SHORT_BASE, SHORT_PER_DAY, SHORT_CAP) if kind == "short" else (LONG_BASE, LONG_PER_DAY, LONG_CAP)
    return min(cap, base + per * max(1, days_worked))


class Quests:
    def __init__(self, store):
        self.store = store
        self.db = store.db

    # ------------------------------------------------------------ reading

    def _row(self, qid):
        if not isinstance(qid, str):
            return None
        return self.db.execute("SELECT * FROM quests WHERE id=? AND deleted_at IS NULL", (qid,)).fetchone()

    def days_worked(self, qid: str) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM quest_work WHERE quest_id=?", (qid,)).fetchone()[0])

    def _done_days(self, qid: str) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT day FROM quest_done WHERE quest_id=?", (qid,))}

    def streak(self, qid: str, at: int) -> int:
        """Consecutive days the daily quest was done, ending yesterday."""
        days = self._done_days(qid)
        n, day = 0, T.add_days(T.day_start(at), -1)
        while T.date_str(day) in days:
            n += 1
            day = T.add_days(day, -1)
        return n

    def _view(self, r, at: int) -> dict:
        out = {"id": r["id"], "title": r["title"], "kind": r["kind"], "color": r["color"] or FIRST_COLOR,
               "active": bool(r["active"]),
               "createdAt": r["created_at"], "daysWorked": self.days_worked(r["id"])}
        out["activity"] = self.activity(r["id"], at)
        if r["kind"] == "daily":
            today = self.db.execute("SELECT xp FROM quest_done WHERE quest_id=? AND day=?",
                                    (r["id"], T.date_str(at))).fetchone()
            out["streak"] = self.streak(r["id"], at)
            out["doneToday"] = today is not None
            out["xp"] = today["xp"] if today is not None else worth("daily", 0, out["streak"])
            out["timesDone"] = len(self._done_days(r["id"]))
        elif r["done_at"] is not None:
            out["doneAt"] = r["done_at"]
            out["xp"] = r["xp"]
        else:
            out["xp"] = worth(r["kind"], out["daysWorked"])
        return out

    # ----------------------------------------------------------- activity

    def periods(self, qid: str, at: int) -> list[tuple[int, int]]:
        return [(r["started_at"], r["ended_at"] if r["ended_at"] is not None else at)
                for r in self.db.execute("SELECT * FROM quest_active WHERE quest_id=? ORDER BY started_at", (qid,))]

    def activity(self, qid: str, at: int, focus_seconds_per_xp: int = 600) -> dict:
        """What happened in sessions while the quest was active: focus time,
        sessions, focus minutes per hour of the day, tasks checked, XP earned
        (focus, tasks and the quest's own rewards)."""
        seconds, sessions, tasks, task_xp = 0, set(), 0, 0
        hours = [0] * 24
        for start, end in self.periods(qid, at):
            if end <= start:
                continue
            for s in self.store.overlapping_sessions(start, end):
                sec = clipped_seconds(s, start, end, at)
                if sec > 0:
                    seconds += sec
                    sessions.add(s["id"])
            for sp in self.store.spans_between(start, end):
                if sp["session_id"] is None:
                    continue
                t, e = sp["s"], sp["e"]
                while t < e:  # split at the hour boundaries, local time
                    local = dt.datetime.fromtimestamp(t / 1000)
                    nxt = int((local.replace(minute=0, second=0, microsecond=0)
                               + dt.timedelta(hours=1)).timestamp() * 1000)
                    hours[local.hour] += min(e, nxt) - t
                    t = min(e, nxt)
            for r in self.db.execute(
                "SELECT created_at, done_at, xp FROM tasks WHERE done_at >= ? AND done_at < ? "
                "AND done_session_id IS NOT NULL", (start, end)
            ):
                tasks += 1
                task_xp += r["xp"] if r["xp"] is not None else 1 + max(0, (r["done_at"] - r["created_at"]) // 86_400_000)
        reward = self.db.execute("SELECT COALESCE(xp, 0) FROM quests WHERE id=?", (qid,)).fetchone()
        reward = int(reward[0]) if reward else 0
        reward += int(self.db.execute("SELECT COALESCE(SUM(xp), 0) FROM quest_done WHERE quest_id=?",
                                      (qid,)).fetchone()[0])
        return {"seconds": int(seconds), "sessions": len(sessions), "tasks": tasks,
                "hours": [round(ms / 60000) for ms in hours],
                "xp": int(seconds) // focus_seconds_per_xp + task_xp + reward,
                "rewardXp": reward}

    def summary(self, at: int) -> list[dict]:
        """Every quest ever made, deleted ones included, with its activity: what
        the achievements are measured on."""
        out = []
        for r in self.db.execute("SELECT * FROM quests ORDER BY created_at").fetchall():
            periods = self.periods(r["id"], at)
            out.append({
                "id": r["id"], "kind": r["kind"], "color": r["color"] or FIRST_COLOR,
                "created": r["created_at"], "done": r["done_at"], "deleted": r["deleted_at"],
                "first_active": periods[0][0] if periods else None,
                "days_worked": self.days_worked(r["id"]),
                "done_days": sorted(self._done_days(r["id"])),
                "activity": self.activity(r["id"], at),
            })
        return out

    def active(self, at: int) -> dict | None:
        r = self.db.execute("SELECT * FROM quests WHERE active=1 AND deleted_at IS NULL LIMIT 1").fetchone()
        return self._view(r, at) if r is not None else None

    def listing(self, at: int) -> dict:
        rows = self.db.execute(
            "SELECT * FROM quests WHERE deleted_at IS NULL AND done_at IS NULL ORDER BY created_at"
        ).fetchall()
        done = self.db.execute(
            "SELECT * FROM quests WHERE deleted_at IS NULL AND done_at IS NOT NULL ORDER BY done_at DESC LIMIT 20"
        ).fetchall()
        return {"success": True,
                "quests": [self._view(r, at) for r in rows],
                "done": [self._view(r, at) for r in done],
                "xp": self.xp_total()}

    def xp_total(self) -> int:
        once = self.db.execute("SELECT COALESCE(SUM(xp), 0) FROM quests WHERE done_at IS NOT NULL").fetchone()[0]
        daily = self.db.execute("SELECT COALESCE(SUM(xp), 0) FROM quest_done").fetchone()[0]
        return int(once) + int(daily)

    # ------------------------------------------------------------ changes

    def add(self, title, kind, at: int) -> dict:
        title = title.strip() if isinstance(title, str) else ""
        if not title:
            raise QuestError("Empty quest")
        if len(title) > TITLE_MAX:
            raise QuestError("Quest too long")
        if kind not in KINDS:
            raise QuestError("Invalid quest duration (daily, short or long)")
        color = self._free_color()
        qid = str(uuid.uuid4())
        self.db.execute("INSERT INTO quests(id, title, kind, created_at, color) VALUES(?, ?, ?, ?, ?)",
                        (qid, title, kind, at, color))
        if len(self._taken_colors()) == len(COLORS):
            self.store.add_event("quests_full", at, None)    # all ten colors open at once
        return {"success": True, "quest": self._view(self._row(qid), at)}

    def _taken_colors(self) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT color FROM quests WHERE deleted_at IS NULL AND done_at IS NULL AND color IS NOT NULL")}

    def _free_color(self) -> str:
        taken = self._taken_colors()
        if FIRST_COLOR not in taken:
            return FIRST_COLOR
        left = [c for c in COLORS if c not in taken]
        if not left:
            raise QuestError("Ten quests at most: finish or delete one first")
        return random.choice(left)

    def activate(self, qid, at: int, working: bool) -> dict:
        r = self._row(qid)
        if r is None or r["done_at"] is not None:
            raise QuestError("Quest not found or already done")
        self._set_active(qid, at)
        if working:
            self.mark_work(at)
        return {"success": True}

    def deactivate(self, qid, at: int) -> dict:
        """Put the active quest aside (any given id must be that quest)."""
        if qid is not None and self._row(qid) is None:
            raise QuestError("Quest not found")
        r = self.db.execute("SELECT id FROM quests WHERE active=1").fetchone()
        if r is not None and (qid is None or r["id"] == qid):
            self._set_active(None, at)
        return {"success": True}

    def _set_active(self, qid: str | None, at: int) -> None:
        """Make `qid` the only active quest (None: no quest), closing and
        opening the activity periods to match."""
        self.db.execute("UPDATE quest_active SET ended_at=? WHERE ended_at IS NULL", (at,))
        self.db.execute("UPDATE quests SET active=0 WHERE active=1")
        if qid is not None:
            self.db.execute("UPDATE quests SET active=1 WHERE id=?", (qid,))
            self.db.execute("INSERT INTO quest_active(quest_id, started_at) VALUES(?, ?)", (qid, at))

    def repair(self, at: int) -> None:
        """An active quest without an open period (made before periods existed)."""
        for r in self.db.execute("SELECT id FROM quests WHERE active=1").fetchall():
            if self.db.execute("SELECT 1 FROM quest_active WHERE quest_id=? AND ended_at IS NULL",
                               (r["id"],)).fetchone() is None:
                self.db.execute("INSERT INTO quest_active(quest_id, started_at) VALUES(?, ?)", (r["id"], at))

    def delete(self, qid, at: int) -> dict:
        if self._row(qid) is None:
            raise QuestError("Quest not found")
        if self._row(qid)["active"]:
            self._set_active(None, at)
        self.db.execute("UPDATE quests SET deleted_at=? WHERE id=?", (at, qid))
        if self._open_multiday() == 0:     # emptied by deleting, not by finishing
            self.store.set_setting("questSweepRun", 0)
        return {"success": True}

    def complete(self, qid, at: int) -> dict:
        """Daily: done for today. Short or long: done for good, and no longer active."""
        r = self._row(qid)
        if r is None or r["done_at"] is not None:
            raise QuestError("Quest not found or already done")
        if r["kind"] == "daily":
            day = T.date_str(at)
            xp = worth("daily", 0, self.streak(qid, at))
            if self.db.execute("INSERT OR IGNORE INTO quest_done(quest_id, day, done_at, xp) VALUES(?, ?, ?, ?)",
                               (qid, day, at, xp)).rowcount == 0:
                raise QuestError("Already done today")
        else:
            xp = worth(r["kind"], self.days_worked(qid))
            if r["active"]:
                self._set_active(None, at)
            self.db.execute("UPDATE quests SET done_at=?, xp=? WHERE id=?", (at, xp, qid))
            # Clean sweep: finishing the last open short or long quest, after
            # finishing at least SWEEP_MIN of them since the list was last empty.
            run = int(self.store.get_setting("questSweepRun", 0) or 0) + 1
            if self._open_multiday() == 0:
                if run >= SWEEP_MIN:
                    self.store.add_event("quest_sweep", at, None)
                run = 0
            self.store.set_setting("questSweepRun", run)
        return {"success": True, "xp": xp, "title": r["title"], "kind": r["kind"]}

    def _open_multiday(self) -> int:
        return int(self.db.execute(
            "SELECT COUNT(*) FROM quests WHERE kind != 'daily' AND deleted_at IS NULL AND done_at IS NULL"
        ).fetchone()[0])

    def uncomplete(self, qid, at: int) -> dict:
        """Undo a completion made by mistake: today's for a daily quest."""
        if not isinstance(qid, str):
            raise QuestError("Quest not found")
        r = self.db.execute("SELECT * FROM quests WHERE id=? AND deleted_at IS NULL", (qid,)).fetchone()
        if r is None:
            raise QuestError("Quest not found")
        if r["kind"] == "daily":
            n = self.db.execute("DELETE FROM quest_done WHERE quest_id=? AND day=?", (qid, T.date_str(at))).rowcount
        else:
            if r["done_at"] is None:
                raise QuestError("Quest not done")
            color = r["color"] if r["color"] and r["color"] not in self._taken_colors() else self._free_color()
            n = self.db.execute("UPDATE quests SET done_at=NULL, xp=NULL, color=? WHERE id=? AND done_at IS NOT NULL",
                                (color, qid)).rowcount
        if n == 0:
            raise QuestError("Quest not done")
        return {"success": True}

    def mark_work(self, at: int) -> None:
        """Count today as a day worked on the active quest (a session is running)."""
        self.db.execute(
            "INSERT OR IGNORE INTO quest_work(quest_id, day) "
            "SELECT id, ? FROM quests WHERE active=1 AND deleted_at IS NULL AND done_at IS NULL",
            (T.date_str(at),),
        )
