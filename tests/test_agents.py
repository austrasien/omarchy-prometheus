import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from prometheus.agents import AgentUsage, message_cost
from prometheus.store import Store


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat().replace("+00:00", "Z")


class AgentUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.projects = root / "projects" / "-home-x-src-app"
        self.projects.mkdir(parents=True)
        self.sync = root / "sync"
        self.sync.mkdir()
        self.store = Store(":memory:")
        self.agents = AgentUsage(self.store, projects=root / "projects", sync_dir=self.sync,
                                 remote_hosts=["forge"], journal=False)
        self.t0 = int(dt.datetime(2026, 10, 19, 10, 0).timestamp() * 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def reply(self, at, mid, out=100, read=1000, model="claude-opus-5-5", session="s1"):
        return {"type": "assistant", "sessionId": session, "cwd": "/home/x/src/app", "timestamp": iso(at),
                "message": {"id": mid, "role": "assistant", "model": model,
                            "usage": {"input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": read,
                                      "cache_creation_input_tokens": 0}}}

    def prompt(self, at, text="do it", session="s1"):
        return {"type": "user", "sessionId": session, "cwd": "/home/x/src/app", "timestamp": iso(at),
                "message": {"role": "user", "content": text}}

    def write(self, name, entries, mode="w"):
        with open(self.projects / name, mode) as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def total(self, device=None):
        q = "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(prompts),0) FROM agent_usage"
        return tuple(self.store.db.execute(q + (" WHERE device=?" if device else ""), (device,) if device else ()).fetchone())

    def test_transcripts_incremental_and_deduplicated(self):
        t = self.t0
        self.write("a.jsonl", [self.prompt(t), self.reply(t + 1000, "m1"), self.reply(t + 1000, "m1"),
                               {"type": "user", "timestamp": iso(t + 2000), "sessionId": "s1",
                                "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]}}])
        self.agents.ingest_local()
        self.assertEqual(self.total("laptop"), (1101, 1))           # the repeated block counted once
        self.write("a.jsonl", [self.reply(t + 70_000, "m2", out=50, read=0)], mode="a")
        self.agents.ingest_local()
        self.assertEqual(self.total("laptop"), (1152, 1))
        row = self.store.db.execute("SELECT project, conversation FROM agent_usage WHERE tokens > 0 LIMIT 1").fetchone()
        self.assertEqual((row["project"], row["conversation"]), ("app", "s1"))
        cost = self.store.db.execute("SELECT SUM(cost) FROM agent_usage").fetchone()[0]
        self.assertAlmostEqual(cost, message_cost("claude-opus-5-5", {"input_tokens": 2, "output_tokens": 150,
                                                                       "cache_read_input_tokens": 1000}), places=9)

    def test_partial_line_waits(self):
        line = json.dumps(self.reply(self.t0, "m1"))
        (self.projects / "b.jsonl").write_text(line[:40])
        self.agents.ingest_local()
        self.assertEqual(self.total(), (0, 0))
        (self.projects / "b.jsonl").write_text(line + "\n")
        self.agents.ingest_local()
        self.assertEqual(self.total()[0], 1101)

    def snap(self, at, models, days=None):
        (self.sync / "forge.json").write_text(json.dumps({
            "updatedAt": iso(at), "providers": {"claude": {
                "todayTokensByModel": models, "todayTotalTokens": sum(models.values()),
                "recentDays": [{"date": d, "messageCount": v} for d, v in (days or {}).items()]}}}))
        self.agents.ingest_remote()

    def test_remote_snapshots(self):
        t = self.t0
        self.snap(t, {"opus": 1000}, {"2026-10-18": 5000})
        self.assertEqual(self.total("forge")[0], 6000)              # yesterday, then this morning
        self.snap(t + 600_000, {"opus": 1500, "haiku": 10})
        self.assertEqual(self.total("forge")[0], 6510)
        self.snap(t + 600_000, {"opus": 9999})                      # same snapshot again: ignored
        self.assertEqual(self.total("forge")[0], 6510)
        # Laptop asleep for 3 hours: spread over the gap, estimated.
        self.snap(t + 600_000 + 3 * 3_600_000, {"opus": 4500, "haiku": 10})
        rows = self.store.db.execute("SELECT COUNT(*) FROM agent_usage WHERE device='forge' "
                                     "AND estimated=1 AND slot >= ?", (t + 600_000,)).fetchone()
        self.assertGreaterEqual(rows[0], 18)
        self.assertEqual(self.total("forge")[0], 6510 + 3000)
        # Past midnight: the old day's rest from its final total, then the new day.
        nxt = int(dt.datetime(2026, 10, 20, 0, 20).timestamp() * 1000)
        self.snap(nxt, {"opus": 200}, {"2026-10-19": 5000})
        self.assertEqual(self.total("forge")[0], 5000 + 5000 + 200)   # the 18th, the 19th whole, the 20th so far


    def test_xp_capped_per_day(self):
        from prometheus import competition as C
        from prometheus.agents import xp_for
        self.assertEqual([xp_for(t) for t in (74_999, 75_000, 600_000, 10**9)], [0, 1, 8, 10])
        t = self.t0
        self.write("c.jsonl", [self.reply(t, "x1", out=0, read=10**8)])
        self.agents.ingest_local()
        ledger = C.Ledger(self.store, t + 60_000)
        self.assertEqual(sum(ledger.xp.values()), 10)
        self.assertEqual(sum(ledger.tokens.values()), 10**8 + 1)


if __name__ == "__main__":
    unittest.main()
