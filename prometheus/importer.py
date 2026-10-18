"""One-shot import of Promethee's history into Prometheus.

Reads ~/.config/Promethee/promethee.db read-only. Sessions are copied as-is
(same ids, so a second run adds nothing). Window samples, taken every ~10 s
during sessions, become focus spans: consecutive samples of the same app
merge, and a span ends at the next sample, or one interval after the last
one when the gap is too long to be the same stretch.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
from pathlib import Path

from .store import Store, default_path

SAMPLE_MS = 10_000
MAX_GAP_MS = 3 * SAMPLE_MS


def to_ms(value) -> int | None:
    """Promethee's columns mix integers and ISO strings."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v * 1000 if v < 10**11 else v
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return int(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def merge_samples(samples: list[tuple[int, str, str | None, str | None]]) -> list[dict]:
    """[(recorded_at, app, title, session_id)] sorted -> spans."""
    spans: list[dict] = []
    cur = None
    for i, (at, app, title, sid) in enumerate(samples):
        nxt = samples[i + 1][0] if i + 1 < len(samples) else None
        end = nxt if nxt is not None and nxt - at <= MAX_GAP_MS else at + SAMPLE_MS
        if cur and cur["app"] == app and cur["session_id"] == sid and cur["ended_at"] >= at:
            cur["ended_at"] = end
            continue
        cur = {"app": app, "title": title, "session_id": sid, "started_at": at, "ended_at": end}
        spans.append(cur)
    return spans


def run(source: Path, store: Store) -> dict:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    db = store.db
    sessions = 0
    db.execute("BEGIN")
    try:
        for r in src.execute("SELECT * FROM sessions WHERE deleted = 0"):
            started = to_ms(r["started_at"])
            if started is None:
                continue
            ended = to_ms(r["ended_at"])
            cur = db.execute(
                "INSERT OR IGNORE INTO sessions(id, task, started_at, ended_at, total_pause_ms, "
                "pause_started_at, end_reason, source) VALUES(?, ?, ?, ?, ?, NULL, ?, 'promethee')",
                (r["id"], r["task"], started, ended if ended is not None else started,
                 r["total_pause_ms"] or 0, r["end_reason"] or "imported"),
            )
            sessions += cur.rowcount

        already = db.execute(
            "SELECT COUNT(*) FROM focus_spans WHERE source = 'promethee'"
        ).fetchone()[0]
        spans = 0
        if not already:
            samples = []
            for r in src.execute(
                "SELECT recorded_at, app_name, window_title, session_id FROM window_events "
                "WHERE COALESCE(paused, 0) = 0 AND COALESCE(idle_seconds, 0) < 60 "
                "ORDER BY recorded_at"
            ):
                at = to_ms(r["recorded_at"])
                if at is not None and r["app_name"]:
                    samples.append((at, r["app_name"], r["window_title"], r["session_id"]))
            for s in merge_samples(samples):
                db.execute(
                    "INSERT INTO focus_spans(session_id, app, title, started_at, ended_at, source) "
                    "VALUES(?, ?, ?, ?, ?, 'promethee')",
                    (s["session_id"], s["app"], s["title"], s["started_at"], s["ended_at"]),
                )
                spans += 1
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        src.close()
    return {"sessions": sessions, "spans": spans}


def main() -> None:
    ap = argparse.ArgumentParser(description="Import Promethee's history into Prometheus.")
    ap.add_argument("--source", type=Path, default=Path(os.path.expanduser("~/.config/Promethee/promethee.db")))
    ap.add_argument("--db", type=Path, default=None, help=f"default: {default_path()}")
    args = ap.parse_args()
    result = run(args.source, Store(args.db) if args.db else Store())
    print(f"{result['sessions']} sessions, {result['spans']} focus spans imported")
