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

import uuid

from . import timeutil as T

KINDS = ("daily", "short", "long")
TITLE_MAX = 300

# XP: base + per day worked, capped. A daily quest earns DAILY_XP, plus 1 for
# each consecutive day it was already done before today, up to DAILY_STREAK_MAX.
DAILY_XP = 5
DAILY_STREAK_MAX = 5
SHORT_BASE, SHORT_PER_DAY, SHORT_CAP = 10, 5, 40
LONG_BASE, LONG_PER_DAY, LONG_CAP = 30, 5, 150


class QuestError(Exception):
    pass


def worth(kind: str, days_worked: int, streak: int = 0) -> int:
    if kind == "daily":
        return DAILY_XP + min(DAILY_STREAK_MAX, max(0, streak))
    base, per, cap = (SHORT_BASE, SHORT_PER_DAY, SHORT_CAP) if kind == "short" else (LONG_BASE, LONG_PER_DAY, LONG_CAP)
    return min(cap, base + per * max(1, days_worked))


class Quests:
    def __init__(self, store):
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
        out = {"id": r["id"], "title": r["title"], "kind": r["kind"], "active": bool(r["active"]),
               "createdAt": r["created_at"], "daysWorked": self.days_worked(r["id"])}
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

    def active(self, at: int) -> dict | None:
        r = self.db.execute("SELECT * FROM quests WHERE active=1 AND deleted_at IS NULL LIMIT 1").fetchone()
        return self._view(r, at) if r is not None else None

    def listing(self, at: int) -> dict:
        rows = self.db.execute(
            "SELECT * FROM quests WHERE deleted_at IS NULL AND done_at IS NULL ORDER BY active DESC, created_at"
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
        qid = str(uuid.uuid4())
        self.db.execute("INSERT INTO quests(id, title, kind, created_at) VALUES(?, ?, ?, ?)", (qid, title, kind, at))
        return {"success": True, "quest": self._view(self._row(qid), at)}

    def activate(self, qid, at: int, working: bool) -> dict:
        r = self._row(qid)
        if r is None or r["done_at"] is not None:
            raise QuestError("Quest not found or already done")
        self.db.execute("UPDATE quests SET active=0 WHERE active=1")
        self.db.execute("UPDATE quests SET active=1 WHERE id=?", (qid,))
        if working:
            self.mark_work(at)
        return {"success": True}

    def deactivate(self, qid=None) -> dict:
        if qid is None:
            self.db.execute("UPDATE quests SET active=0 WHERE active=1")
        elif self.db.execute("UPDATE quests SET active=0 WHERE id=?", (qid,)).rowcount == 0:
            raise QuestError("Quest not found")
        return {"success": True}

    def delete(self, qid, at: int) -> dict:
        if self._row(qid) is None:
            raise QuestError("Quest not found")
        self.db.execute("UPDATE quests SET deleted_at=?, active=0 WHERE id=?", (at, qid))
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
            self.db.execute("UPDATE quests SET done_at=?, xp=?, active=0 WHERE id=?", (at, xp, qid))
        return {"success": True, "xp": xp, "title": r["title"], "kind": r["kind"]}

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
            n = self.db.execute("UPDATE quests SET done_at=NULL, xp=NULL WHERE id=? AND done_at IS NOT NULL",
                                (qid,)).rowcount
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
