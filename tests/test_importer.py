import sqlite3
import tempfile
import unittest
from pathlib import Path

from prometheus.importer import merge_samples, run, to_ms
from prometheus.store import Store

S = 10_000


class ImporterTest(unittest.TestCase):
    def test_to_ms(self):
        self.assertEqual(to_ms(1792240206900), 1792240206900)
        self.assertEqual(to_ms(1792240206), 1792240206000)
        self.assertEqual(to_ms("2026-08-25T04:57:15.000Z"), 1787633835000)
        self.assertIsNone(to_ms(None))

    def test_merge(self):
        samples = [
            (0, "Foot", "~", "s"), (S, "Foot", "vim", "s"), (2 * S, "Brave", "x", "s"),
            (3 * S, "Brave", "y", "s"),
            (10 * S, "Brave", "z", "s"),   # long gap: a new stretch
        ]
        spans = merge_samples(samples)
        self.assertEqual(
            [(s["app"], s["started_at"], s["ended_at"]) for s in spans],
            [("Foot", 0, 2 * S), ("Brave", 2 * S, 4 * S), ("Brave", 10 * S, 11 * S)],
        )

    def test_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "p.db"
            con = sqlite3.connect(src)
            con.executescript("""
              CREATE TABLE sessions (id TEXT, task TEXT, started_at INTEGER, ended_at INTEGER,
                total_pause_ms INTEGER, end_reason TEXT, deleted INTEGER);
              CREATE TABLE window_events (recorded_at INTEGER, app_name TEXT, window_title TEXT,
                session_id TEXT, paused INTEGER, idle_seconds INTEGER);
              INSERT INTO sessions VALUES ('a', 'Deep', 1792240000000, 1792240600000, 0, NULL, 0);
              INSERT INTO sessions VALUES ('b', 'gone', 1792240000000, 1792240600000, 0, NULL, 1);
              INSERT INTO window_events VALUES (1792240000000, 'Foot', '~', 'a', 0, 0);
              INSERT INTO window_events VALUES (1792240010000, 'Foot', '~', 'a', 0, 0);
              INSERT INTO window_events VALUES (1792240020000, 'Foot', '~', 'a', 1, 0);
            """)
            con.commit()
            con.close()
            store = Store(Path(d) / "out.db")
            self.assertEqual(run(src, store), {"sessions": 1, "spans": 1})
            self.assertEqual(run(src, store), {"sessions": 0, "spans": 0})
            row = store.db.execute("SELECT * FROM sessions").fetchone()
            self.assertEqual((row["id"], row["task"], row["source"]), ("a", "Deep", "promethee"))


if __name__ == "__main__":
    unittest.main()
