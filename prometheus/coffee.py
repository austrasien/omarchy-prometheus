"""Coffee: cups logged from the bar, caffeine in the blood, the best time for
the next one, and how coffee goes with the rest (focus, tasks, tokens).

Caffeine model: one standard cup (95 mg) per coffee, absorbed with a
half-life of about 10 minutes (peak near 45 minutes), eliminated with a
half-life of 5 hours, spread over 0.6 L/kg of a 90 kg man (54 L).
"""

from __future__ import annotations

import datetime as dt
import math

from . import agents
from . import timeutil as T

MG_PER_CUP = 95
BODY_KG = 90
VOLUME_L = 0.6 * BODY_KG
KA = math.log(2) / (10 / 60)        # absorption per hour
KE = math.log(2) / 5                 # elimination per hour
DAILY_LIMIT_MG = 400                 # the usual safe daily amount for an adult
LOW_MG = 60                          # below this, another cup is worth it (about 4 h after one)
BEDTIME_HOUR = 23                    # the default; the bedtime setting
SLEEP_GAP_H = 8                      # no coffee in the 8 hours before bed
UNDO_MS = 3 * 60_000                 # a cup can be taken back for 3 minutes
HOUR_MS = 3_600_000


def in_body(cups: list[int], at: int, mg: float = MG_PER_CUP) -> float:
    """Caffeine in the body at `at` (mg), from the cups taken at those times."""
    total = 0.0
    for c in cups:
        h = (at - c) / HOUR_MS
        if h <= 0:
            continue
        total += mg * KA / (KA - KE) * (math.exp(-KE * h) - math.exp(-KA * h))
    return total


def concentration(mg: float) -> float:
    """mg/L in the blood (plasma), for the body above."""
    return mg / VOLUME_L


class Coffee:
    def __init__(self, store):
        self.store = store

    def cups(self, start: int = 0, end: int | None = None) -> list[int]:
        q = "SELECT at FROM coffees WHERE at >= ?" + (" AND at < ?" if end is not None else "") + " ORDER BY at"
        return [r[0] for r in self.store.db.execute(q, (start, end) if end is not None else (start,))]

    def add(self, at: int) -> dict:
        ideal = self.ideal(at)["at"]
        self.store.db.execute("INSERT INTO coffees(at, mg) VALUES (?, ?)", (at, MG_PER_CUP))
        if ideal is not None and abs(at - ideal) <= 15 * 60_000:     # right on time
            self.store.add_event("coffee_timed", at, None)
        return {"success": True, **self.now(at)}

    def undo(self, at: int) -> dict:
        row = self.store.db.execute("SELECT rowid, at FROM coffees ORDER BY at DESC LIMIT 1").fetchone()
        if row is None or at - row["at"] > UNDO_MS:
            return {"success": False, "error": "Nothing to take back (10 minutes at most)"}
        self.store.db.execute("DELETE FROM coffees WHERE rowid = ?", (row["rowid"],))
        return {"success": True, **self.now(at)}

    # ------------------------------------------------------------ now

    def bedtime_hour(self) -> int:
        return int(self.store.get_setting("bedtimeHour", BEDTIME_HOUR))

    def set_bedtime(self, hour) -> dict:
        try:
            h = int(hour)
        except (TypeError, ValueError):
            return {"success": False, "error": "Invalid hour"}
        h %= 24
        self.store.set_setting("bedtimeHour", h)
        return {"success": True, "bedtimeHour": h}

    def _bedtime(self, at: int) -> int:
        """Tonight's bedtime: the first bedtime o'clock after the day starts
        (1:00 with a 5:00 day start is the night after)."""
        start = T.day_start(at)
        bed = dt.datetime.fromtimestamp(start / 1000).replace(hour=self.bedtime_hour(), minute=0, second=0, microsecond=0)
        ms = int(bed.timestamp() * 1000)
        return ms if ms > start else ms + 86_400_000

    def ideal(self, at: int) -> dict:
        """When the next cup is worth it: caffeine run low, the day's limit
        not reached, and 8 hours left before bed."""
        start = T.day_start(at)
        cups = self.cups(start - 86_400_000)
        today = [c for c in cups if c >= start]
        cutoff = self._bedtime(at) - SLEEP_GAP_H * HOUR_MS
        if (len(today) + 1) * MG_PER_CUP > DAILY_LIMIT_MG:
            return {"at": None, "reason": f"{len(today)} cups today: that's the {DAILY_LIMIT_MG} mg a day"}
        # Low now and over the next 45 minutes (a cup just drunk is still rising).
        def low(t):
            return in_body(cups, t) <= LOW_MG and in_body(cups, t + 45 * 60_000) <= LOW_MG
        t = at
        while t <= cutoff and not low(t):
            t += 5 * 60_000
        if t > cutoff:
            return {"at": None, "reason": f"Too late for coffee: {self.bedtime_hour()}:00 bedtime, 8 h to clear it"}
        if t == at:
            return {"at": at, "reason": "Now: caffeine is low"}
        return {"at": t, "reason": f"Caffeine falls under {LOW_MG} mg then"}

    def now(self, at: int) -> dict:
        start = T.day_start(at)
        cups = self.cups(start - 86_400_000)
        mg = in_body(cups, at)
        today = [c for c in cups if c >= start]
        last = cups[-1] if cups else None
        return {"cupsToday": len(today), "mgToday": len(today) * MG_PER_CUP, "inBody": round(mg),
                "bedtimeHour": self.bedtime_hour(), "undoMs": UNDO_MS,
                "mgPerL": round(concentration(mg), 2), "lastAt": last,
                "canUndo": last is not None and at - last <= UNDO_MS, "ideal": self.ideal(at)}

    # ------------------------------------------------------------ the day, hour by hour

    def day(self, start: int | None, at: int) -> dict:
        """Hour by hour from the day start: focus minutes, tasks checked,
        quests finished, agent tokens, cups; caffeine every 10 minutes."""
        start = T.day_start(at) if start is None else T.day_start(int(start))
        end = T.add_days(start, 1)
        db = self.store.db
        hours = [{"start": start + h * HOUR_MS, "focus": 0, "tasks": 0, "quests": 0, "tokens": 0, "cups": 0}
                 for h in range(24)]

        def slot(ms):
            i = int((ms - start) // HOUR_MS)
            return hours[i] if 0 <= i < 24 else None

        sessions = []
        for r in db.execute("SELECT task, started_at, ended_at, total_pause_ms FROM sessions "
                            "WHERE started_at < ? AND COALESCE(ended_at, ?) > ?", (end, at, start)):
            s, e = max(r["started_at"], start), min(r["ended_at"] if r["ended_at"] is not None else at, end)
            sessions.append({"task": r["task"], "start": s, "end": e})
            t = s
            while t < e:                      # wall time in session per hour (pauses included)
                nxt = min(e, start + (int((t - start) // HOUR_MS) + 1) * HOUR_MS)
                h = slot(t)
                if h:
                    h["focus"] += (nxt - t) / 60_000
                t = nxt
        for r in db.execute("SELECT done_at FROM tasks WHERE done_at >= ? AND done_at < ?", (start, end)):
            if h := slot(r[0]):
                h["tasks"] += 1
        quests = []
        for r in db.execute("SELECT title, done_at FROM quests WHERE done_at >= ? AND done_at < ? "
                            "UNION ALL SELECT q.title, d.done_at FROM quest_done d JOIN quests q ON q.id = d.quest_id "
                            "WHERE d.done_at >= ? AND d.done_at < ?", (start, end, start, end)):
            quests.append({"title": r[0], "at": r[1]})
            if h := slot(r[1]):
                h["quests"] += 1
        for s, tokens in db.execute("SELECT slot, SUM(tokens) FROM agent_usage WHERE slot >= ? AND slot < ? "
                                    "GROUP BY slot", (start, end)):
            if h := slot(s):
                h["tokens"] += tokens
        cups = self.cups(start - 86_400_000)
        for c in cups:
            if h := slot(c):
                h["cups"] += 1
        for h in hours:
            h["focus"] = round(h["focus"])
        until = min(end, at)
        curve = [{"at": t, "mg": round(in_body(cups, t), 1)} for t in range(start, until + 1, 10 * 60_000)]
        return {"success": True, "fromMs": start, "toMs": end, "now": at, "hours": hours, "sessions": sessions,
                "quests": quests, "cups": [c for c in cups if start <= c < end], "caffeine": curve,
                "lowMg": LOW_MG, "limitMg": DAILY_LIMIT_MG, "mgPerCup": MG_PER_CUP,
                "coffee": self.now(at) if start <= at < end else None}

    # ------------------------------------------------------------ stats

    def stats(self, at: int) -> dict:
        """30 days of cups, the weeks, and how coffee days go."""
        today = T.day_start(at)
        first = T.add_days(today, -29)
        per_day = {}
        for c in self.cups(T.add_days(today, -89)):
            d = T.date_str(c)
            per_day[d] = per_day.get(d, 0) + 1
        days = [{"date": T.date_str(T.add_days(first, i)), "cups": per_day.get(T.date_str(T.add_days(first, i)), 0)}
                for i in range(30)]
        weeks = []
        week0 = T.week_start(at)
        for i in range(7, -1, -1):
            lo = T.add_days(week0, -7 * i)
            hi = T.add_days(lo, 7)
            weeks.append({"from": T.date_str(lo), "cups": len(self.cups(lo, hi))})
        total = self.store.db.execute("SELECT COUNT(*) FROM coffees").fetchone()[0]
        active = [d["cups"] for d in days if d["cups"] > 0]

        # Per day over 90 days: cups next to focus, tasks, tokens.
        from .competition import Ledger
        ledger = Ledger(self.store, at)
        keys = [T.date_str(T.add_days(today, -i)) for i in range(89, -1, -1)]
        keys = [k for k in keys if ledger.focus.get(k) or per_day.get(k) or ledger.tokens.get(k)]
        series = {
            "focus": [ledger.focus.get(k, 0) / 3600 for k in keys],
            "tasks": [ledger.tasks.get(k, 0) for k in keys],
            "tokens": [ledger.tokens.get(k, 0) for k in keys],
            "xp": [ledger.xp.get(k, 0) for k in keys],
        }
        cups = [per_day.get(k, 0) for k in keys]
        correlations = {k: _pearson(cups, v) for k, v in series.items()}
        with_coffee = [i for i, c in enumerate(cups) if c > 0]
        without = [i for i, c in enumerate(cups) if c == 0]

        def mean(idx, name):
            return round(sum(series[name][i] for i in idx) / len(idx), 1) if idx else None
        compare = {name: {"with": mean(with_coffee, name), "without": mean(without, name)} for name in series}
        cups_total = sum(cups)

        def per_cup(name, digits=1):        # coffee days only
            if not cups_total:
                return None
            v = sum(series[name][i] for i in with_coffee) / cups_total
            return round(v, digits) if digits else round(v)
        return {
            "success": True, "days": days, "weeks": weeks, "total": total,
            "today": per_day.get(T.date_str(at), 0),
            "average": round(sum(active) / len(active), 1) if active else None,
            "last30": sum(d["cups"] for d in days),
            "correlations": correlations, "compare": compare, "daysCompared": len(keys),
            "focusPerCup": per_cup("focus"),
            "tasksPerCup": per_cup("tasks"),
            "tokensPerCup": per_cup("tokens", 0),
            "now": self.now(at),
        }

    # ------------------------------------------------------------ achievements

    def measures(self, sessions: list[dict], tasks_done: list[int]) -> dict:
        db = self.store.db
        cups = self.cups()
        out = {"cups": len(cups)}
        per_day = {}
        for c in cups:
            d = T.date_str(c)
            per_day[d] = per_day.get(d, 0) + 1
        out["bestDay"] = max(per_day.values(), default=0)
        out["streak"] = agents._longest_run(list(per_day))
        out["late"] = sum(1 for c in cups if dt.datetime.fromtimestamp(c / 1000).hour >= 18)
        out["early"] = sum(1 for c in cups if dt.datetime.fromtimestamp(c / 1000).hour < 7)
        # Peak caffeine: right after each cup, near the 45-minute peak.
        out["peak"] = round(max((in_body(cups, c + 45 * 60_000) for c in cups), default=0))
        # Days with 2 h of focus and no cup.
        focus_day = {}
        for s in sessions:
            focus_day[s["date"]] = focus_day.get(s["date"], 0) + s["focus"]
        out["decaf"] = sum(1 for d, f in focus_day.items() if f >= 7200 and d not in per_day)
        # Sessions of an hour or more started within 45 minutes after a cup.
        import bisect
        out["brewed"] = 0
        for s in sessions:
            i = bisect.bisect_right(cups, s["start"])
            if s["focus"] >= 3600 and i and s["start"] - cups[i - 1] <= 45 * 60_000:
                out["brewed"] += 1
        # Tasks checked with more than 100 mg on board.
        out["wiredTasks"] = sum(1 for t in tasks_done if in_body(
            cups[bisect.bisect_left(cups, t - 86_400_000):bisect.bisect_right(cups, t)], t) > 100)
        # Tokens in the two hours after a cup, best one.
        out["fuel"] = max((agents.tokens_between(self.store, c, c + 2 * HOUR_MS) for c in cups), default=0)
        # Weeks (Sunday to Saturday) with coffee that never went over the daily limit.
        weeks = {}
        for d, n in per_day.items():
            day = dt.date.fromisoformat(d)
            sunday = day - dt.timedelta(days=(day.weekday() + 1) % 7)
            weeks.setdefault(sunday, []).append(n)
        out["sensible"] = sum(1 for v in weeks.values() if max(v) * MG_PER_CUP <= DAILY_LIMIT_MG)
        out["timed"] = self.store.count_events("coffee_timed")
        return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)
