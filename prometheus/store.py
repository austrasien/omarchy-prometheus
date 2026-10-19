"""SQLite storage: sessions, focus spans, settings.

A focus span is one stretch of time spent in one application. It is written
when it opens (ended_at = started_at) and its end is moved forward on every
checkpoint, so a crash loses at most one checkpoint interval.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path

SCHEMA_VERSION = 10

# Abandoning an accepted extension challenge costs this much XP.
ABANDON_PENALTY = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id               TEXT PRIMARY KEY,
  task             TEXT,
  started_at       INTEGER NOT NULL,
  ended_at         INTEGER,
  total_pause_ms   INTEGER NOT NULL DEFAULT 0,
  pause_started_at INTEGER,
  end_reason       TEXT,
  source           TEXT NOT NULL DEFAULT 'prometheus'
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_ended ON sessions(ended_at);

CREATE TABLE IF NOT EXISTS focus_spans (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  app        TEXT NOT NULL,
  title      TEXT,
  started_at INTEGER NOT NULL,
  ended_at   INTEGER NOT NULL,
  source     TEXT NOT NULL DEFAULT 'prometheus'
);
CREATE INDEX IF NOT EXISTS idx_spans_started ON focus_spans(started_at);
CREATE INDEX IF NOT EXISTS idx_spans_session ON focus_spans(session_id);
CREATE INDEX IF NOT EXISTS idx_spans_ended ON focus_spans(ended_at);

CREATE TABLE IF NOT EXISTS tasks (
  id                   TEXT PRIMARY KEY,
  text                 TEXT NOT NULL,
  source               TEXT NOT NULL DEFAULT 'manual',
  created_at           INTEGER NOT NULL,
  done_at              INTEGER,
  done_session_id      TEXT,
  xp                   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done_at);

CREATE TABLE IF NOT EXISTS challenges (
  id           TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL,
  offered_at   INTEGER NOT NULL,
  answered_at  INTEGER,
  start_focus  INTEGER,            -- session focus seconds when accepted
  minutes      INTEGER NOT NULL,
  state        TEXT NOT NULL,      -- offered, active, won, declined, abandoned, expired
  ended_at     INTEGER,
  xp           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_challenges_session ON challenges(session_id);

CREATE TABLE IF NOT EXISTS achievements (
  id          TEXT PRIMARY KEY,
  unlocked_at INTEGER NOT NULL,
  xp          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS medals (
  id          TEXT NOT NULL,
  period_key  TEXT NOT NULL,      -- 2026-10-18, 2026-W42 or 2026-10
  awarded_at  INTEGER NOT NULL,
  xp          INTEGER NOT NULL,
  PRIMARY KEY (id, period_key)
);

CREATE TABLE IF NOT EXISTS events (
  kind       TEXT NOT NULL,      -- e.g. absent: paused for not answering "Still there?"
  at         INTEGER NOT NULL,
  session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, at);

-- Tokens burned by coding agents (agents.py): per device, minute (ten
-- minutes for other machines), conversation and model. estimated: spread
-- over a gap between two snapshots.
CREATE TABLE IF NOT EXISTS agent_usage (
  device       TEXT NOT NULL,
  slot         INTEGER NOT NULL,
  conversation TEXT NOT NULL DEFAULT '',
  project      TEXT NOT NULL DEFAULT '',
  model        TEXT NOT NULL DEFAULT '',
  tokens       INTEGER NOT NULL DEFAULT 0,
  input        INTEGER NOT NULL DEFAULT 0,
  output       INTEGER NOT NULL DEFAULT 0,
  cache_read   INTEGER NOT NULL DEFAULT 0,
  cache_write  INTEGER NOT NULL DEFAULT 0,
  prompts      INTEGER NOT NULL DEFAULT 0,
  cost         REAL NOT NULL DEFAULT 0,
  estimated    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (device, slot, conversation, model)
);
CREATE INDEX IF NOT EXISTS idx_agent_slot ON agent_usage(slot);
-- How far each transcript was read, and the replies already counted.
CREATE TABLE IF NOT EXISTS agent_files (path TEXT PRIMARY KEY, offset INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS agent_messages (id TEXT PRIMARY KEY) WITHOUT ROWID;

-- Quests: goals that span days. Only one is active at a time. Deleting one
-- only hides it, so the XP it earned stays in the profile.
CREATE TABLE IF NOT EXISTS quests (
  id           TEXT PRIMARY KEY,
  title        TEXT NOT NULL,
  kind         TEXT NOT NULL,      -- daily, short, long
  created_at   INTEGER NOT NULL,
  active       INTEGER NOT NULL DEFAULT 0,
  done_at      INTEGER,            -- short and long only
  xp           INTEGER,            -- short and long: what completing it earned
  deleted_at   INTEGER,
  color        TEXT,               -- from the medal palette; unique among open quests
  board_hidden INTEGER NOT NULL DEFAULT 0   -- taken off the leaderboard
);

-- A logical day on which a session ran while the quest was active.
CREATE TABLE IF NOT EXISTS quest_work (
  quest_id TEXT NOT NULL,
  day      TEXT NOT NULL,
  PRIMARY KEY (quest_id, day)
);

-- When each quest was the active one. A quest's activity (time, sessions,
-- tasks, XP) is what happened in sessions during these periods.
CREATE TABLE IF NOT EXISTS quest_active (
  quest_id   TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  ended_at   INTEGER                -- NULL while it is still active
);
CREATE INDEX IF NOT EXISTS idx_quest_active ON quest_active(quest_id);

-- Daily quests: one row per day they were completed.
CREATE TABLE IF NOT EXISTS quest_done (
  quest_id TEXT NOT NULL,
  day      TEXT NOT NULL,
  done_at  INTEGER NOT NULL,
  xp       INTEGER NOT NULL,
  PRIMARY KEY (quest_id, day)
);

-- Season medals: won once, kept for good, each with its own random colors.
CREATE TABLE IF NOT EXISTS season_medals (
  season     TEXT PRIMARY KEY,     -- 2026-Q4
  number     INTEGER NOT NULL,     -- Season 1, 2, ...
  bars       INTEGER NOT NULL,     -- 1: goal reached, 2: hard goal reached
  bg         TEXT NOT NULL,
  dot        TEXT NOT NULL,
  edge       TEXT NOT NULL,
  awarded_at INTEGER NOT NULL,
  xp         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def default_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "prometheus" / "prometheus.db"


def session_seconds(row: sqlite3.Row | dict, until: int | None = None) -> int:
    """Worked seconds of a session, pauses deducted. `until` closes an open one."""
    end = row["ended_at"] if row["ended_at"] is not None else until
    if end is None:
        return 0
    paused = row["total_pause_ms"] or 0
    if row["pause_started_at"] is not None and row["ended_at"] is None:
        paused += max(0, end - row["pause_started_at"])
    return max(0, (end - row["started_at"] - paused) // 1000)


def clipped_seconds(row, start: int, end: int, now: int) -> int:
    """Worked seconds of a session inside [start, end); pauses spread evenly."""
    s_end = row["ended_at"] if row["ended_at"] is not None else now
    lo, hi = max(row["started_at"], start), min(s_end, end)
    if hi <= lo or s_end <= row["started_at"]:
        return 0
    worked = session_seconds(row, until=now)
    return int(worked * (hi - lo) / (s_end - row["started_at"]))


class Store:
    def __init__(self, path: Path | str | None = None):
        if path is None:
            path = default_path()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _migrate(self) -> None:
        # The agents' Night shift once shared the quests' family id.
        self.db.execute("UPDATE achievements SET id = 'agentnight:' || substr(id, 12) "
                        "WHERE id GLOB 'nightshift:1e+*'")
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(tasks)")}
        if "xp" not in cols:  # v1 -> v2: XP a task was worth when it was done
            self.db.execute("ALTER TABLE tasks ADD COLUMN xp INTEGER")
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(sessions)")}
        for name, kind in (("on_battery", "INTEGER"), ("weather", "TEXT"), ("temp_c", "REAL"),
                           ("battery_pct", "REAL")):
            if name not in cols:  # v2 -> v3 (v4: battery_pct): the world around a session
                self.db.execute(f"ALTER TABLE sessions ADD COLUMN {name} {kind}")

        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(quests)")}
        if "color" not in cols:  # v5 -> v6: each quest has its own color
            self.db.execute("ALTER TABLE quests ADD COLUMN color TEXT")
        if "board_hidden" not in cols:  # v8 -> v9: quests taken off the leaderboard
            self.db.execute("ALTER TABLE quests ADD COLUMN board_hidden INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ settings

    def get_setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    # ------------------------------------------------------------ sessions

    def open_session(self) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

    def create_session(self, task: str | None, at: int) -> str:
        sid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO sessions(id, task, started_at) VALUES(?, ?, ?)", (sid, task, at)
        )
        return sid

    def set_pause(self, sid: str, pause_started_at: int | None, total_pause_ms: int) -> None:
        self.db.execute(
            "UPDATE sessions SET pause_started_at=?, total_pause_ms=? WHERE id=?",
            (pause_started_at, total_pause_ms, sid),
        )

    def finish_session(self, sid: str, at: int, total_pause_ms: int, reason: str) -> None:
        self.db.execute(
            "UPDATE sessions SET ended_at=?, pause_started_at=NULL, total_pause_ms=?, "
            "end_reason=? WHERE id=?",
            (at, total_pause_ms, reason, sid),
        )

    def overlapping_sessions(self, start: int, end: int) -> list[sqlite3.Row]:
        """Sessions with any time in [start, end), open ones included."""
        return self.db.execute(
            "SELECT * FROM sessions WHERE started_at < ? AND (ended_at IS NULL OR ended_at > ?)",
            (end, start),
        ).fetchall()

    def get_session(self, sid: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()

    def closed_sessions(self, start: int, end: int) -> list[sqlite3.Row]:
        """Sessions that ended within [start, end)."""
        return self.db.execute(
            "SELECT * FROM sessions WHERE ended_at IS NOT NULL AND ended_at >= ? AND ended_at < ? "
            "ORDER BY started_at",
            (start, end),
        ).fetchall()

    # --------------------------------------------------------------- tasks

    def open_tasks(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM tasks WHERE done_at IS NULL ORDER BY created_at"
        ).fetchall()

    def open_task_by_text(self, text: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM tasks WHERE done_at IS NULL AND text = ? LIMIT 1", (text,)
        ).fetchone()

    def add_task(self, text: str, source: str, at: int) -> str:
        tid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO tasks(id, text, source, created_at) VALUES(?, ?, ?, ?)",
            (tid, text, source, at),
        )
        return tid

    def complete_task(self, tid: str, at: int, session_id: str | None, xp: int) -> bool:
        cur = self.db.execute(
            "UPDATE tasks SET done_at=?, done_session_id=?, xp=? WHERE id=? AND done_at IS NULL",
            (at, session_id, xp, tid),
        )
        return cur.rowcount > 0

    # ----------------------------------------------------------- challenges

    def last_challenge(self, session_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM challenges WHERE session_id=? ORDER BY offered_at DESC LIMIT 1", (session_id,)
        ).fetchone()

    def session_challenge_states(self, session_id: str) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT state FROM challenges WHERE session_id=?", (session_id,))]

    def add_challenge(self, session_id: str, at: int, minutes: int, xp: int) -> str:
        """`xp` is what the challenge is worth if won; only won ones are summed."""
        cid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO challenges(id, session_id, offered_at, minutes, state, xp) VALUES(?, ?, ?, ?, 'offered', ?)",
            (cid, session_id, at, minutes, xp),
        )
        return cid

    def won_challenges(self, session_id: str) -> int:
        return int(self.db.execute(
            "SELECT COUNT(*) FROM challenges WHERE session_id=? AND state='won'", (session_id,)
        ).fetchone()[0])

    def update_challenge(self, cid: str, **fields) -> None:
        keys = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE challenges SET {keys} WHERE id=?", (*fields.values(), cid))

    def session_bonus_xp(self, session_id: str) -> int:
        """XP earned in a session besides focus: tasks checked in it, challenges won in it."""
        tasks = self.db.execute(
            "SELECT COALESCE(SUM(xp), 0) FROM tasks WHERE done_session_id=? AND done_at IS NOT NULL", (session_id,)
        ).fetchone()[0]
        won = self.db.execute(
            "SELECT COALESCE(SUM(xp), 0) FROM challenges WHERE session_id=? AND state='won'", (session_id,)
        ).fetchone()[0]
        abandoned = self.db.execute(
            "SELECT COUNT(*) FROM challenges WHERE session_id=? AND state='abandoned'", (session_id,)
        ).fetchone()[0]
        return int(tasks) + int(won) - ABANDON_PENALTY * int(abandoned)

    def challenge_xp_total(self) -> int:
        won = self.db.execute("SELECT COALESCE(SUM(xp), 0) FROM challenges WHERE state='won'").fetchone()[0]
        abandoned = self.db.execute("SELECT COUNT(*) FROM challenges WHERE state='abandoned'").fetchone()[0]
        return int(won) - ABANDON_PENALTY * int(abandoned)

    def set_session_env(self, sid: str, **fields) -> None:
        keys = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE sessions SET {keys} WHERE id=?", (*fields.values(), sid))

    def add_event(self, kind: str, at: int, session_id: str | None) -> None:
        self.db.execute("INSERT INTO events(kind, at, session_id) VALUES(?, ?, ?)", (kind, at, session_id))

    def sessions_with_event(self, kind: str) -> set[str]:
        return {r[0] for r in self.db.execute(
            "SELECT DISTINCT session_id FROM events WHERE kind=? AND session_id IS NOT NULL", (kind,))}

    def set_achievement_xp(self, aid: str, xp: int) -> None:
        self.db.execute("UPDATE achievements SET xp=? WHERE id=?", (xp, aid))

    def count_events(self, kind: str) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM events WHERE kind=?", (kind,)).fetchone()[0])

    def unlocked_achievements(self) -> dict[str, sqlite3.Row]:
        return {r["id"]: r for r in self.db.execute("SELECT * FROM achievements")}

    def unlock(self, aid: str, at: int, xp: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO achievements(id, unlocked_at, xp) VALUES(?, ?, ?)", (aid, at, xp))

    def medal_awards(self) -> set[tuple[str, str]]:
        return {(r[0], r[1]) for r in self.db.execute("SELECT id, period_key FROM medals")}

    def award_medal(self, mid: str, key: str, at: int, xp: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO medals(id, period_key, awarded_at, xp) VALUES(?, ?, ?, ?)",
                        (mid, key, at, xp))

    def medal_counts(self) -> dict:
        out = {}
        for r in self.db.execute(
            "SELECT id, COUNT(*) AS n, MAX(period_key) AS last_key FROM medals GROUP BY id"
        ):
            out[r["id"]] = {"count": r["n"], "last_key": r["last_key"]}
        return out

    def medal_xp_total(self) -> int:
        return int(self.db.execute("SELECT COALESCE(SUM(xp), 0) FROM medals").fetchone()[0])

    def achievement_xp_total(self) -> int:
        return int(self.db.execute("SELECT COALESCE(SUM(xp), 0) FROM achievements").fetchone()[0])

    def all_sessions(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM sessions").fetchall()

    def done_tasks(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM tasks WHERE done_at IS NOT NULL").fetchall()

    def done_tasks_between(self, start: int, end: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM tasks WHERE done_at >= ? AND done_at < ? ORDER BY done_at DESC", (start, end)
        ).fetchall()

    def delete_open_task(self, tid: str) -> bool:
        return self.db.execute("DELETE FROM tasks WHERE id=? AND done_at IS NULL", (tid,)).rowcount > 0

    def reopen_task(self, tid: str) -> bool:
        cur = self.db.execute(
            "UPDATE tasks SET done_at=NULL, done_session_id=NULL, xp=NULL WHERE id=? AND done_at IS NOT NULL", (tid,)
        )
        return cur.rowcount > 0

    def tasks_done_between(self, start: int, end: int) -> int:
        return int(self.db.execute(
            "SELECT COUNT(*) FROM tasks WHERE done_at >= ? AND done_at < ?", (start, end)
        ).fetchone()[0])

    # --------------------------------------------------------------- spans

    def open_span(self, app: str, title: str | None, session_id: str | None, at: int) -> int:
        cur = self.db.execute(
            "INSERT INTO focus_spans(session_id, app, title, started_at, ended_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (session_id, app, title, at, at),
        )
        return int(cur.lastrowid)

    def extend_span(self, span_id: int, at: int) -> None:
        self.db.execute(
            "UPDATE focus_spans SET ended_at=MAX(ended_at, ?) WHERE id=?", (at, span_id)
        )

    def cut_span(self, span_id: int, at: int) -> None:
        """End the span exactly at `at`, earlier than its last checkpoint if need be."""
        self.db.execute(
            "UPDATE focus_spans SET ended_at=MAX(started_at, ?) WHERE id=?", (at, span_id)
        )

    def drop_empty_span(self, span_id: int) -> None:
        self.db.execute(
            "DELETE FROM focus_spans WHERE id=? AND ended_at - started_at < 1000", (span_id,)
        )

    def app_seconds(self, start: int, end: int, session_id: str | None = None) -> list[dict]:
        """Seconds per app within [start, end), clipped to the window."""
        sql = (
            "SELECT app, SUM(MIN(ended_at, :end) - MAX(started_at, :start)) / 1000 AS seconds "
            "FROM focus_spans WHERE ended_at > :start AND started_at < :end"
        )
        params: dict = {"start": start, "end": end}
        if session_id is not None:
            sql += " AND session_id = :sid"
            params["sid"] = session_id
        sql += " GROUP BY app HAVING seconds > 0 ORDER BY seconds DESC"
        return [{"app": r["app"], "seconds": int(r["seconds"])} for r in self.db.execute(sql, params)]

    def spans_between(self, start: int, end: int) -> list[sqlite3.Row]:
        """Spans overlapping [start, end), clipped to it, in time order."""
        return self.db.execute(
            "SELECT app, MAX(started_at, :start) AS s, MIN(ended_at, :end) AS e, session_id "
            "FROM focus_spans WHERE ended_at > :start AND started_at < :end ORDER BY started_at",
            {"start": start, "end": end},
        ).fetchall()

    def span_count(self, start: int, end: int, in_session: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM focus_spans WHERE started_at >= ? AND started_at < ?"
        if in_session:
            sql += " AND session_id IS NOT NULL"
        return int(self.db.execute(sql, (start, end)).fetchone()[0])
