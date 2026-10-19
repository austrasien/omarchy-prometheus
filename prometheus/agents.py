"""Tokens burned by coding agents, as a sign of work.

Two sources:
- this machine: Claude Code's transcripts (~/.claude/projects/**/*.jsonl),
  read incrementally, one row per minute, conversation and model, with the
  input / output / cache split, the prompts typed and an estimated cost;
- other machines (forge): the snapshots the agents panel pulls every ten
  minutes (<syncDir>/<host>.json, `remoteHosts` in its settings). Only the
  day's total per model is known there, so each snapshot is compared with
  the one before; a gap (this laptop asleep) is spread evenly over it and
  marked estimated. The pull service's journal gives the snapshots taken
  before Prometheus read them.

Only counts are read, never what was said.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import subprocess
from pathlib import Path

from . import timeutil as T

log = logging.getLogger(__name__)

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
SHELL_JSON = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "omarchy" / "shell.json"
AGENTS_WIDGET = "austraz.agents"
DEFAULT_SYNC_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state")) / "omarchy" / "agents" / "sync"
PULL_UNIT = "agents-remote-usage.service"

LOCAL_DEVICE = "laptop"
MINUTE_MS = 60_000
REMOTE_SLOT_MS = 600_000          # remote tokens land in ten-minute slots
GAP_MS = 15 * MINUTE_MS           # longer between two snapshots: spread, estimated
READ_BUDGET = 8 * 1024 * 1024     # transcript bytes read per poll (the first import takes a few)

# XP: 1 per 75,000 tokens, at most 10 a day.
TOKENS_PER_XP = 75_000
DAILY_XP_CAP = 10

# $ per million tokens: input, output, cache read; first substring match
# wins. Cache writes bill 1.25x input (5-minute TTL) or 2x (1-hour TTL).
# From the agents panel's forecast.py.
PRICES = (
    ("fable", 10.0, 50.0, 0.25),
    ("mythos", 10.0, 50.0, 0.25),
    ("opus-5-5", 4.0, 20.0, 0.20),
    ("opus", 5.0, 25.0, 0.50),
    ("sonnet-5", 2.0, 10.0, 0.20),
    ("sonnet", 3.0, 15.0, 0.30),
    ("haiku-5", 0.10, 0.50, 0.01),
    ("haiku", 1.0, 5.0, 0.10),
)


def _n(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def message_cost(model: str, usage: dict) -> float:
    price = next((p for p in PRICES if p[0] in model), None)
    if price is None:
        return 0.0
    _, p_in, p_out, p_read = price
    created = usage.get("cache_creation")
    if isinstance(created, dict) and ("ephemeral_5m_input_tokens" in created or "ephemeral_1h_input_tokens" in created):
        write = _n(created.get("ephemeral_5m_input_tokens")) * 1.25 + _n(created.get("ephemeral_1h_input_tokens")) * 2.0
    else:
        write = _n(usage.get("cache_creation_input_tokens")) * 1.25
    return (_n(usage.get("input_tokens")) * p_in + write * p_in + _n(usage.get("output_tokens")) * p_out
            + _n(usage.get("cache_read_input_tokens")) * p_read) / 1e6


def family(model: str) -> str:
    for f in ("fable", "mythos", "opus", "sonnet", "haiku"):
        if f in model:
            return f
    return model or "other"


def _iso_ms(text) -> int | None:
    try:
        return int(dt.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _midnight(date: str) -> int:
    return int(dt.datetime.fromisoformat(date).timestamp() * 1000)


def _is_prompt(entry: dict) -> bool:
    """A message typed by the person (not a tool result, not injected)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return not content.startswith("<")      # command output, reminders...
    if isinstance(content, list):
        kinds = {c.get("type") for c in content if isinstance(c, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def agents_settings() -> dict:
    try:
        bar = json.loads(SHELL_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    def find(o):
        if isinstance(o, dict):
            if o.get("id") == AGENTS_WIDGET:
                return o
            o = list(o.values())
        if isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
        return None
    return find(bar) or {}


class AgentUsage:
    def __init__(self, store, projects: Path = PROJECTS, sync_dir: Path | None = None,
                 remote_hosts: list[str] | None = None, journal: bool = True):
        self.store = store
        self.projects = projects
        settings = agents_settings() if sync_dir is None or remote_hosts is None else {}
        self.sync_dir = sync_dir or Path(os.path.expanduser(settings.get("syncDir") or str(DEFAULT_SYNC_DIR)))
        if remote_hosts is None:
            remote_hosts = [h for h in re.split(r"[\s,]+", settings.get("remoteHosts") or "") if h]
        self.remote_hosts = remote_hosts
        self.journal = journal
        self.backlog = True          # transcripts left to read

    # ------------------------------------------------------------ this machine

    def _add(self, device, slot, conversation, project, model, tokens, inp=0, out=0, read=0, write=0,
             prompts=0, cost=0.0, estimated=0) -> None:
        self.store.agent_version = getattr(self.store, "agent_version", 0) + 1
        self.store.db.execute(
            "INSERT INTO agent_usage(device, slot, conversation, project, model, tokens, input, output, "
            "cache_read, cache_write, prompts, cost, estimated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(device, slot, conversation, model) DO UPDATE SET tokens=tokens+excluded.tokens, "
            "input=input+excluded.input, output=output+excluded.output, cache_read=cache_read+excluded.cache_read, "
            "cache_write=cache_write+excluded.cache_write, prompts=prompts+excluded.prompts, "
            "cost=cost+excluded.cost, estimated=MAX(estimated, excluded.estimated), "
            "project=CASE WHEN project='' THEN excluded.project ELSE project END",
            (device, slot, conversation, project, model, tokens, inp, out, read, write, prompts, cost, estimated))

    def _read_line(self, entry: dict, path: Path) -> None:
        conversation = str(entry.get("sessionId") or path.stem)
        project = os.path.basename(str(entry.get("cwd") or "").rstrip("/"))
        at = _iso_ms(entry.get("timestamp"))
        if at is None:
            return
        slot = at - at % MINUTE_MS
        if _is_prompt(entry):
            self._add(LOCAL_DEVICE, slot, conversation, project, "", 0, prompts=1)
            return
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        usage = message.get("usage") or entry.get("usage")
        if entry.get("type") != "assistant" or not isinstance(usage, dict):
            return
        mid = str(message.get("id") or entry.get("requestId") or entry.get("uuid") or "")
        if mid:
            # Each content block of a reply is a line carrying the same usage.
            if self.store.db.execute("INSERT OR IGNORE INTO agent_messages(id) VALUES (?)", (mid,)).rowcount == 0:
                return
        inp, out = _n(usage.get("input_tokens")), _n(usage.get("output_tokens"))
        read, write = _n(usage.get("cache_read_input_tokens")), _n(usage.get("cache_creation_input_tokens"))
        total = inp + out + read + write
        if total <= 0:
            return
        model = str(message.get("model") or entry.get("model") or "claude")
        if model.startswith("<"):            # <synthetic>
            return
        self._add(LOCAL_DEVICE, slot, conversation, project, model, total, inp, out, read, write,
                  cost=message_cost(model, usage))

    def ingest_local(self, budget: int = READ_BUDGET) -> int:
        """Reads what was appended to the transcripts since last time, up to
        `budget` bytes. Returns the bytes read."""
        if not self.projects.is_dir():
            self.backlog = False
            return 0
        db = self.store.db
        offsets = {r[0]: r[1] for r in db.execute("SELECT path, offset FROM agent_files")}
        files = []
        for path in self.projects.rglob("*.jsonl"):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            done = offsets.get(str(path), 0)
            if size < done:                   # rewritten: read again (messages are deduplicated)
                done = 0
            if size > done:
                files.append((path, done, size))
        files.sort(key=lambda f: f[1] > 0)    # files already started first: today's work
        used, left = 0, False
        db.execute("BEGIN")
        try:
            for path, start, size in files:
                if used >= budget:
                    left = True
                    break
                with open(path, "rb") as fh:
                    fh.seek(start)
                    chunk = fh.read(min(size - start, max(budget - used, 1 << 20)))
                end = chunk.rfind(b"\n") + 1  # whole lines only
                for raw in chunk[:end].splitlines():
                    if b'"usage"' not in raw and b'"user"' not in raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(entry, dict):
                        self._read_line(entry, path)
                used += end
                left = left or start + end < size - 1 and end > 0
                db.execute("INSERT INTO agent_files(path, offset) VALUES (?, ?) "
                           "ON CONFLICT(path) DO UPDATE SET offset=excluded.offset", (str(path), start + end))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        self.backlog = left
        return used

    # ------------------------------------------------------------ other machines

    def _spread(self, device: str, start: int, end: int, by_model: dict[str, int]) -> None:
        """Tokens burned between two snapshots, in ten-minute slots; spread
        evenly when the snapshots are far apart (estimated)."""
        if not by_model:
            return
        end = max(end, start + 1)
        if end - start <= GAP_MS:
            slot = end - end % REMOTE_SLOT_MS
            for model, tokens in by_model.items():
                self._add(device, slot, "", "", model, tokens, cost=self._remote_cost(model, tokens))
            return
        first = start - start % REMOTE_SLOT_MS
        slots = list(range(first, end, REMOTE_SLOT_MS))
        for model, tokens in by_model.items():
            given = 0
            for i, slot in enumerate(slots):
                lo, hi = max(slot, start), min(slot + REMOTE_SLOT_MS, end)
                # The last slot takes the rounding rest.
                part = tokens - given if i == len(slots) - 1 else tokens * (hi - lo) // (end - start)
                given += part
                if part > 0:
                    self._add(device, slot, "", "", model, part, cost=self._remote_cost(model, part), estimated=1)

    def _remote_cost(self, model: str, tokens: int) -> float:
        """Forge only tells the total per model: priced at the average cost
        per token of the same model here, else at its cache read price."""
        rates = getattr(self, "_rates", {})
        rate = rates.get(model, rates.get("") if not model else None)
        if rate is None:
            price = next((p for p in PRICES if p[0] in model), None)
            rate = price[3] / 1e6 if price else 0.0
        return tokens * rate

    def _load_rates(self) -> None:
        self._rates = {r[0]: r[1] / r[2] for r in self.store.db.execute(
            "SELECT model, SUM(cost), SUM(tokens) FROM agent_usage WHERE device=? AND tokens > 0 "
            "GROUP BY model", (LOCAL_DEVICE,)) if r[2]}
        # Model unknown (older snapshots): the average over everything here.
        row = self.store.db.execute("SELECT SUM(cost), SUM(tokens) FROM agent_usage WHERE device=?",
                                    (LOCAL_DEVICE,)).fetchone()
        if row[1]:
            self._rates[""] = row[0] / row[1]

    def _snapshot_state(self, device: str) -> dict | None:
        return self.store.get_setting(f"agentSnapshot:{device}")

    def _take(self, device: str, at: int, date: str, by_model: dict[str, int], day_totals: dict[str, int]) -> None:
        """One snapshot: the day's tokens per model, at `at` (ms), for `date`
        (the remote's calendar day)."""
        prev = self._snapshot_state(device)
        if prev is not None and at <= prev["at"]:
            return
        if prev is None:
            # The first one: the earlier days the remote still lists, whole,
            # then this day from midnight; spread, so estimated.
            for day, total in sorted(day_totals.items()):
                if day and day < date and total > 0:
                    lo = _midnight(day)
                    self._spread(device, lo, lo + 86_400_000, {"": total})
            delta = {}
            self._spread(device, _midnight(date), at, {m: v for m, v in by_model.items() if v > 0})
        elif prev["date"] == date and set(prev["models"]) == {""} and set(by_model) != {""}:
            # From the journal's totals to per-model snapshots: the total only.
            rest = sum(by_model.values()) - prev["models"][""]
            delta = {"": rest} if rest > 0 else {}
        elif prev["date"] == date:
            delta = {m: v - _n(prev["models"].get(m)) for m, v in by_model.items()}
            delta = {m: v for m, v in delta.items() if v > 0}
        else:
            # A new day: what the old day burned after the last snapshot,
            # from its final total if known, until midnight; then the new day.
            final = day_totals.get(prev["date"])
            rest = (final - sum(prev["models"].values())) if final else 0
            midnight = _midnight(date)
            if rest > 0:
                self._spread(device, prev["at"], midnight, {"": rest})
            delta = {m: v for m, v in by_model.items() if v > 0}
            if delta:
                self._spread(device, midnight, at, delta)
            delta = {}
        if delta:
            self._spread(device, prev["at"], at, delta)
        self.store.set_setting(f"agentSnapshot:{device}", {"at": at, "date": date, "models": by_model})

    def ingest_remote(self) -> None:
        self._load_rates()
        for host in self.remote_hosts:
            try:
                snap = json.loads((self.sync_dir / f"{host}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            claude = (snap.get("providers") or {}).get("claude") or {}
            at = _iso_ms(snap.get("updatedAt"))
            if at is None or not claude:
                continue
            models = {m: _n(v) for m, v in (claude.get("todayTokensByModel") or {}).items()}
            if not models and _n(claude.get("todayTotalTokens")):
                models = {"": _n(claude.get("todayTotalTokens"))}
            days = {d.get("date"): _n(d.get("messageCount")) for d in claude.get("recentDays") or []}
            local = dt.datetime.fromtimestamp(at / 1000)
            self.store.db.execute("BEGIN")
            try:
                self._take(host, at, local.date().isoformat(), models, days)
                self.store.db.execute("COMMIT")
            except BaseException:
                self.store.db.execute("ROLLBACK")
                raise

    def backfill_journal(self) -> None:
        """Once: the snapshots the pull service logged before Prometheus read
        them (its journal line has the day's total)."""
        if not self.journal or self.store.get_setting("agentJournalRead", False):
            return
        try:
            out = subprocess.run(["journalctl", "--user", "-u", PULL_UNIT, "--no-pager", "-o", "short-iso"],
                                 capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return
        pat = re.compile(r"^(\S+) .*?: (\S+): \d+ records, claude today ([\d,]+) tokens")
        days = {}
        for host in self.remote_hosts:
            try:
                claude = json.loads((self.sync_dir / f"{host}.json").read_text())["providers"]["claude"]
                days[host] = {d.get("date"): _n(d.get("messageCount")) for d in claude.get("recentDays") or []}
            except (OSError, ValueError, KeyError, TypeError):
                days[host] = {}
        self._load_rates()
        self.store.db.execute("BEGIN")
        try:
            for line in out.splitlines():
                m = pat.match(line)
                if not m or m.group(2) not in self.remote_hosts:
                    continue
                at = _iso_ms(m.group(1))
                if at is None:
                    continue
                local = dt.datetime.fromtimestamp(at / 1000)
                self._take(m.group(2), at, local.date().isoformat(), {"": int(m.group(3).replace(",", ""))},
                           days.get(m.group(2), {}))
            self.store.set_setting("agentJournalRead", True)
            self.store.db.execute("COMMIT")
        except BaseException:
            self.store.db.execute("ROLLBACK")
            raise

    def poll(self) -> None:
        self.ingest_local()
        self.backfill_journal()
        self.ingest_remote()


# ---------------------------------------------------------------- reading
#
# Everything below reads agent_usage, for the ledger, stats, achievements.


def short(n: float) -> str:
    """12.3k, 4.5M, 1.2B."""
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            v = n / size
            return (f"{v:.1f}".rstrip("0").rstrip(".") if v < 100 else f"{v:.0f}") + unit
    return str(int(n))


def tokens_by_day(store) -> dict[str, int]:
    """Tokens per logical day (the day start applies), every device. Kept
    until new tokens come in or the day start moves (read every push)."""
    key = (getattr(store, "agent_version", 0), T.day_start_hour())
    cached = getattr(store, "_tokens_by_day", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    out: dict[str, int] = {}
    for slot, tokens in store.db.execute("SELECT slot, SUM(tokens) FROM agent_usage GROUP BY slot"):
        d = T.date_str(slot)
        out[d] = out.get(d, 0) + tokens
    store._tokens_by_day = (key, out)
    return out


def xp_for(tokens: int) -> int:
    return min(DAILY_XP_CAP, tokens // TOKENS_PER_XP)


def tokens_between(store, start: int, end: int) -> int:
    return int(store.db.execute("SELECT COALESCE(SUM(tokens), 0) FROM agent_usage WHERE slot >= ? AND slot < ?",
                                (start, end)).fetchone()[0])


def window(store, start: int, end: int) -> dict:
    """Totals over [start, end): tokens, the local split, prompts, cost."""
    r = store.db.execute(
        "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(input),0), COALESCE(SUM(output),0), "
        "COALESCE(SUM(cache_read),0), COALESCE(SUM(cache_write),0), COALESCE(SUM(prompts),0), "
        "COALESCE(SUM(cost),0), COUNT(DISTINCT CASE WHEN conversation != '' AND tokens > 0 THEN conversation END) "
        "FROM agent_usage WHERE slot >= ? AND slot < ?", (start, end)).fetchone()
    return {"tokens": r[0], "input": r[1], "output": r[2], "cacheRead": r[3], "cacheWrite": r[4],
            "prompts": r[5], "cost": round(r[6], 2), "conversations": r[7]}


def _prefix(store) -> tuple[list[int], list[int]]:
    """Slots in order and the running total of tokens up to each one, to sum
    any window with two bisections."""
    slots, sums, acc = [], [0], 0
    for slot, tokens in store.db.execute("SELECT slot, SUM(tokens) FROM agent_usage GROUP BY slot ORDER BY slot"):
        slots.append(slot)
        acc += tokens
        sums.append(acc)
    return slots, sums


def _sum(slots, sums, start: int, end: int) -> int:
    import bisect
    return sums[bisect.bisect_left(slots, end)] - sums[bisect.bisect_left(slots, start)]


def session_tokens(store, sessions: list[tuple[int, int]]) -> list[int]:
    """Tokens burned during each (start, end) window."""
    slots, sums = _prefix(store)
    return [_sum(slots, sums, s, e) for s, e in sessions]


def measures(store, sessions: list[dict]) -> dict:
    """For the achievements. `sessions`: dicts with start, end, focus (s)."""
    db = store.db
    out = {"maxParallel": 0, "maxModels": 0, "remoteDays": 0, "cacheDays": 0, "bestNight": 0,
           "deepPairs": 0, "streak": 0, "lifetime": 0, "bestOutside": 0, "bestCost": 0.0}
    row = db.execute("SELECT MAX(n) FROM (SELECT COUNT(DISTINCT conversation) AS n FROM agent_usage "
                     "WHERE device=? AND tokens > 0 AND conversation != '' GROUP BY slot)", (LOCAL_DEVICE,)).fetchone()
    out["maxParallel"] = row[0] or 0
    models, per_device, cache, night, cost = {}, {}, {}, {}, {}
    for slot, device, model, tokens, read, c, est in db.execute(
            "SELECT slot, device, model, tokens, cache_read, cost, estimated FROM agent_usage WHERE tokens > 0"):
        d = T.date_str(slot)
        if model:
            models.setdefault(d, set()).add(family(model))
        per_device.setdefault(d, {}).setdefault(device, 0)
        per_device[d][device] += tokens
        if device == LOCAL_DEVICE:
            t, r = cache.get(d, (0, 0))
            cache[d] = (t + tokens, r + read)
        cost[d] = cost.get(d, 0.0) + c
        hour = dt.datetime.fromtimestamp(slot / 1000).hour
        if hour < 6 and not est:         # the night before the day starts; spread time is a guess
            night[d] = night.get(d, 0) + tokens
        out["lifetime"] += tokens
    out["maxModels"] = max((len(v) for v in models.values()), default=0)
    out["remoteDays"] = sum(1 for v in per_device.values()
                            if sum(t for dev, t in v.items() if dev != LOCAL_DEVICE) > v.get(LOCAL_DEVICE, 0))
    out["cacheDays"] = sum(1 for t, r in cache.values() if t >= 1_000_000 and r / t >= 0.97)
    out["bestNight"] = max(night.values(), default=0)
    out["bestCost"] = round(max(cost.values(), default=0.0), 2)
    # Days with tokens in a row.
    days = sorted(dt.date.fromisoformat(d) for d, v in per_device.items() if sum(v.values()) > 0)
    run = best = 0
    for i, day in enumerate(days):
        run = run + 1 if i and (day - days[i - 1]).days == 1 else 1
        best = max(best, run)
    out["streak"] = best
    # Focus sessions with agents at work, and tokens outside any session.
    windows = [(s["start"], s["end"]) for s in sessions]
    inside = session_tokens(store, windows)
    out["deepPairs"] = sum(1 for s, t in zip(sessions, inside) if s["focus"] >= 7200 and t >= 10_000_000)
    by_day_inside = {}
    for s, t in zip(sessions, inside):
        d = T.date_str(s["start"])
        by_day_inside[d] = by_day_inside.get(d, 0) + t
    out["bestOutside"] = max((sum(v.values()) - by_day_inside.get(d, 0) for d, v in per_device.items()), default=0)
    return out


def stats(store, now: int, sessions: list[tuple[int, int]]) -> dict:
    """The Agents view: 30 days by day, today, devices, model families,
    projects, a weekday x hour heatmap, and how the tokens are made."""
    db = store.db
    today = T.day_start(now)
    since = T.add_days(today, -29)
    days = []
    for i in range(30):
        lo = T.add_days(since, i)
        hi = T.add_days(lo, 1)
        r = db.execute("SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(cost),0) FROM agent_usage "
                       "WHERE slot >= ? AND slot < ?", (lo, hi)).fetchone()
        days.append({"date": T.date_str(lo), "tokens": r[0], "cost": round(r[1], 2)})

    def grouped(col, where=""):
        rows = db.execute(f"SELECT {col}, SUM(tokens), SUM(cost) FROM agent_usage WHERE slot >= ? {where} "
                          f"GROUP BY {col} ORDER BY 2 DESC", (since,)).fetchall()
        return rows

    fams = {}
    for model, tokens, cost in grouped("model", "AND model != ''"):
        f = fams.setdefault(family(model), {"key": family(model), "tokens": 0, "cost": 0.0})
        f["tokens"] += tokens
        f["cost"] += cost
    known = sum(f["tokens"] for f in fams.values())
    total30 = sum(d["tokens"] for d in days)
    if total30 > known:
        fams["?"] = {"key": "unknown", "tokens": total30 - known, "cost": 0.0}
    families = sorted(({**f, "cost": round(f["cost"], 2)} for f in fams.values()), key=lambda f: -f["tokens"])
    devices = [{"key": d, "tokens": t, "cost": round(c, 2)} for d, t, c in grouped("device")]
    projects = [{"key": p, "tokens": t, "cost": round(c, 2)}
                for p, t, c in grouped("project", f"AND device = '{LOCAL_DEVICE}' AND project != ''")][:8]

    # Weekday (Sunday first) x hour, 8 weeks, measured slots only.
    grid = [[0] * 24 for _ in range(7)]
    for slot, tokens in db.execute("SELECT slot, SUM(tokens) FROM agent_usage WHERE slot >= ? AND estimated = 0 "
                                   "GROUP BY slot", (now - 56 * 86_400_000,)):
        local = dt.datetime.fromtimestamp(slot / 1000)
        grid[(local.weekday() + 1) % 7][local.hour] += tokens

    local30 = window(store, since, now + 1)
    here = db.execute("SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(cache_read),0), COALESCE(SUM(prompts),0), "
                      "COALESCE(SUM(output),0) FROM agent_usage WHERE device=? AND slot >= ?", (LOCAL_DEVICE, since)).fetchone()
    inside = sum(session_tokens(store, [(max(s, since), e) for s, e in sessions if e > since]))
    lifetime = db.execute("SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(cost),0) FROM agent_usage").fetchone()
    peak = db.execute("SELECT MAX(n) FROM (SELECT COUNT(DISTINCT conversation) AS n FROM agent_usage "
                      "WHERE device=? AND tokens > 0 AND conversation != '' AND slot >= ? GROUP BY slot)",
                      (LOCAL_DEVICE, since)).fetchone()[0] or 0
    return {
        "success": True,
        "days": days,
        "today": window(store, today, now + 1),
        "last30": local30,
        "lifetime": {"tokens": lifetime[0], "cost": round(lifetime[1], 2)},
        "families": families,
        "devices": devices,
        "projects": projects,
        "heatmap": grid,
        "cacheShare": round(100 * here[1] / here[0]) if here[0] else None,
        "tokensPerPrompt": round(here[0] / here[2]) if here[2] else None,
        "outputPerPrompt": round(here[3] / here[2]) if here[2] else None,
        "parallelPeak": peak,
        "outsideShare": round(100 * (total30 - inside) / total30) if total30 else None,
        "xpPerDay": {"tokensPerXp": TOKENS_PER_XP, "cap": DAILY_XP_CAP},
    }


def _longest_run(days: list[str]) -> int:
    """Longest run of consecutive dates among `days` (ISO strings)."""
    ds = sorted({dt.date.fromisoformat(d) for d in days})
    run = best = 0
    for i, d in enumerate(ds):
        run = run + 1 if i and (d - ds[i - 1]).days == 1 else 1
        best = max(best, run)
    return best


def _longest_same(per_day: dict[str, set]) -> int:
    """Longest run of consecutive active days all on the same single value."""
    best = run = 0
    prev_day, prev_value = None, None
    for d in sorted(per_day):
        values = per_day[d]
        day = dt.date.fromisoformat(d)
        value = next(iter(values)) if len(values) == 1 else None
        if value is not None and value == prev_value and prev_day is not None and (day - prev_day).days == 1:
            run += 1
        else:
            run = 1 if value is not None else 0
        best = max(best, run)
        prev_day, prev_value = day, value
    return best


def more_measures(store, sessions: list[dict], quest_days: set[str], medal_days: set[str]) -> dict:
    """The second wave of agent achievements: rhythm, records, how you
    work with them, and how they meet the rest of the app."""
    from .competition import records
    db = store.db
    by_day = tokens_by_day(store)
    hour0 = T.day_start_hour()

    # Measured slots only for anything about the time of day.
    quarter, blocks, early = {}, {}, set()
    prompts_day, here_day, projects_week, project_day, family_day = {}, {}, {}, {}, {}
    for slot, device, project, model, tokens, prompts, est in db.execute(
            "SELECT slot, device, project, model, tokens, prompts, estimated FROM agent_usage"):
        d = T.date_str(slot)
        if device == LOCAL_DEVICE:
            prompts_day[d] = prompts_day.get(d, 0) + prompts
            here_day[d] = here_day.get(d, 0) + tokens
            if project and tokens > 0:
                projects_week.setdefault(T.week_key(dt.date.fromisoformat(d)), set()).add(project)
                project_day.setdefault(d, set()).add(project)
            if model and tokens > 0:
                family_day.setdefault(d, set()).add(family(model))
        if est or tokens <= 0:
            continue
        q = slot - slot % 900_000
        quarter[q] = quarter.get(q, 0) + tokens
        hour = dt.datetime.fromtimestamp(slot / 1000).hour
        blocks.setdefault(d, set()).add(((hour - hour0) % 24) // 4)
        if hour0 <= hour < 7:
            early.add(d)

    # Weeks run Sunday to Saturday: a Sunday and the Saturday six days later.
    sundays = {d for d, t in by_day.items() if t > 0 and dt.date.fromisoformat(d).weekday() == 6}
    warriors = sum(1 for d in sundays
                   if by_day.get((dt.date.fromisoformat(d) + dt.timedelta(days=6)).isoformat(), 0) > 0)

    # Thirty-day rolling cost.
    cost_day = {}
    for slot, c in db.execute("SELECT slot, SUM(cost) FROM agent_usage GROUP BY slot"):
        d = T.date_str(slot)
        cost_day[d] = cost_day.get(d, 0.0) + c
    best_month, total, lo = 0.0, 0.0, 0
    days = sorted(dt.date.fromisoformat(d) for d in cost_day)
    for hi, day in enumerate(days):           # a sliding 30-day window
        total += cost_day[day.isoformat()]
        while (day - days[lo]).days >= 30:
            total -= cost_day[days[lo].isoformat()]
            lo += 1
        best_month = max(best_month, total)

    windows = [(s["start"], s["end"]) for s in sessions]
    per_session = session_tokens(store, windows)
    silent = 0
    for r in db.execute("SELECT answered_at, ended_at FROM challenges WHERE state='won' "
                        "AND answered_at IS NOT NULL AND ended_at IS NOT NULL"):
        if tokens_between(store, r["answered_at"], r["ended_at"]) >= 20_000_000:
            silent += 1

    return {
        "weekendWarriors": warriors,
        "alwaysOn": sum(1 for b in blocks.values() if len(b) == 6),
        "earlyBird": len(early),
        "steadyBurn": _longest_run([d for d, t in by_day.items() if t >= 50_000_000]),
        "spike": max(quarter.values(), default=0),
        "personalBest": records(sorted(by_day.items())),
        "monsterSession": max(per_session, default=0),
        "bestMonthCost": round(best_month, 2),
        "prompts": sum(prompts_day.values()),
        "laconic": sum(1 for d, t in here_day.items() if t >= 10_000_000 and prompts_day.get(d, 0) < 10),
        "chatterbox": max(prompts_day.values(), default=0),
        "sprawl": max((len(v) for v in projects_week.values()), default=0),
        "monogamous": _longest_same(project_day),
        "loyalist": _longest_same(family_day),
        "questFuel": sum(1 for d in quest_days if by_day.get(d, 0) >= 100_000_000),
        "synergy": sum(1 for d in medal_days if by_day.get(d, 0) >= 250_000_000),
        "silentPartner": silent,
    }


def _best_window(points: list[tuple[int, int]], width: int) -> int:
    """Most tokens in any `width` ms window; `points` (slot, tokens) sorted."""
    best = total = lo = 0
    for hi in range(len(points)):
        total += points[hi][1]
        while points[hi][0] - points[lo][0] >= width:
            total -= points[lo][1]
            lo += 1
        best = max(best, total)
    return best


def third_measures(store, sessions: list[dict], quest_periods: list[tuple[str, int, int]]) -> dict:
    """Third wave: peaks over an hour or two, the biggest quest, week, month
    and season, day and night, and the conditions of each session (weather,
    temperature, battery)."""
    from .competition import _season, _season_key
    db = store.db
    measured = [(r[0], r[1]) for r in db.execute(
        "SELECT slot, SUM(tokens) FROM agent_usage WHERE estimated = 0 GROUP BY slot ORDER BY slot")]
    by_day = tokens_by_day(store)

    weeks, months, seasons = {}, {}, {}
    for d, t in by_day.items():
        day = dt.date.fromisoformat(d)
        sunday = day - dt.timedelta(days=(day.weekday() + 1) % 7)
        weeks[sunday] = weeks.get(sunday, 0) + t
        months[d[:7]] = months.get(d[:7], 0) + t
        key = _season_key(*_season(day))
        seasons[key] = seasons.get(key, 0) + t

    daylight, night = {}, {}
    for slot, t in measured:
        hour = dt.datetime.fromtimestamp(slot / 1000).hour
        d = T.date_str(slot)
        if 8 <= hour < 20:
            daylight[d] = daylight.get(d, 0) + t
        elif hour < 6:
            night[d] = night.get(d, 0) + t

    slots, sums = _prefix(store)
    quests: dict[str, int] = {}
    for qid, start, end in quest_periods:
        quests[qid] = quests.get(qid, 0) + _sum(slots, sums, start, end)

    burnt = session_tokens(store, [(s["start"], s["end"]) for s in sessions])
    rain = battery = 0
    storm = snow = heat = cold = sunny = 0
    for s, t in zip(sessions, burnt):
        w, temp = s.get("weather"), s.get("temp")
        if w == "rain":
            rain += t
        if s.get("battery") == 1:
            battery += t
        if t >= 10_000_000:
            storm += w == "storm"
            snow += w == "snow"
            heat += temp is not None and temp >= 30
            cold += temp is not None and temp <= 0
            sunny += w == "clear" and temp is not None and temp >= 20
    return {
        "bestHour": _best_window(measured, 3_600_000),
        "bestTwoHours": _best_window(measured, 7_200_000),
        "bestQuest": max(quests.values(), default=0),
        "bestWeek": max(weeks.values(), default=0),
        "bestMonth": max(months.values(), default=0),
        "bestSeason": max(seasons.values(), default=0),
        "bestDaylight": max(daylight.values(), default=0),
        "dayAndNight": sum(1 for d in daylight if daylight[d] >= 10_000_000 and night.get(d, 0) >= 10_000_000),
        "rainTokens": rain,
        "batteryTokens": battery,
        "storms": storm, "snowDays": snow, "heat": heat, "cold": cold, "sunny": sunny,
    }
