"""More stats, drawn from every part of the app: where the week's XP comes
from, tasks, challenges, presence checks, focus quality, a week-by-hour
heatmap, and the context of sessions (power, weather)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import achievements as A
from . import timeutil as T
from .store import ABANDON_PENALTY, session_seconds

DAY_MS = 86_400_000
FOCUS_SECONDS_PER_XP = 600


def _days(start_ms: int, n: int) -> list[int]:
    return [T.add_days(start_ms, i) for i in range(n)]


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def xp_sources(store, now: int) -> list[dict]:
    """XP per day of the current week (Sunday to Saturday), by source."""
    first = T.week_start(now)
    days = _days(first, 7)
    keys = [T.date_str(d) for d in days]
    out = {k: {"date": k, "focus": 0, "tasks": 0, "challenges": 0, "quests": 0, "medals": 0, "achievements": 0}
           for k in keys}

    def add(ms, source, xp):
        k = T.date_str(ms)
        if k in out:
            out[k][source] += xp

    db = store.db
    for r in store.all_sessions():
        add(r["started_at"], "focus", session_seconds(r, until=now) // FOCUS_SECONDS_PER_XP)
    for r in db.execute("SELECT created_at, done_at, xp FROM tasks WHERE done_at IS NOT NULL"):
        add(r["done_at"], "tasks", r["xp"] if r["xp"] is not None else 1 + max(0, (r["done_at"] - r["created_at"]) // DAY_MS))
    for r in db.execute("SELECT ended_at, xp, state FROM challenges WHERE state IN ('won', 'abandoned') AND ended_at IS NOT NULL"):
        add(r["ended_at"], "challenges", r["xp"] if r["state"] == "won" else -ABANDON_PENALTY)
    for r in db.execute("SELECT done_at, xp FROM quests WHERE done_at IS NOT NULL"):
        add(r["done_at"], "quests", r["xp"] or 0)
    for r in db.execute("SELECT done_at, xp FROM quest_done"):
        add(r["done_at"], "quests", r["xp"])
    for r in db.execute("SELECT awarded_at, xp FROM medals"):
        add(r["awarded_at"], "medals", r["xp"])
    for r in db.execute("SELECT awarded_at, xp FROM season_medals"):
        add(r["awarded_at"], "medals", r["xp"])
    for r in db.execute("SELECT unlocked_at, xp FROM achievements"):
        add(r["unlocked_at"], "achievements", r["xp"])
    return [out[k] for k in keys]


def tasks(store, now: int) -> dict:
    today = T.day_start(now)
    db = store.db
    rows = db.execute("SELECT created_at, done_at FROM tasks").fetchall()
    done_per_day = []
    for d in _days(T.add_days(today, -13), 14):
        end = T.add_days(d, 1)
        done_per_day.append({"date": T.date_str(d), "done": sum(1 for r in rows if r["done_at"] is not None
                                                                and d <= r["done_at"] < end)})
    backlog = []
    for d in _days(T.add_days(today, -29), 30):
        end = min(T.add_days(d, 1), now)
        backlog.append({"date": T.date_str(d), "open": sum(1 for r in rows if r["created_at"] < end
                                                          and (r["done_at"] is None or r["done_at"] >= end))})
    ages = [(r["done_at"] - r["created_at"]) / DAY_MS for r in rows if r["done_at"] is not None]
    recent = [(r["done_at"] - r["created_at"]) / DAY_MS for r in rows
              if r["done_at"] is not None and r["done_at"] >= T.add_days(today, -30)]
    return {"donePerDay": done_per_day, "backlog": backlog,
            "avgAgeDays": round(sum(ages) / len(ages), 1) if ages else None,
            "avgAgeDays30": round(sum(recent) / len(recent), 1) if recent else None,
            "open": sum(1 for r in rows if r["done_at"] is None), "done": len(ages)}


def challenges(store) -> dict:
    counts = defaultdict(int)
    for r in store.db.execute("SELECT state, COUNT(*) AS n FROM challenges GROUP BY state"):
        counts[r["state"]] = r["n"]
    offered = sum(counts.values())
    taken = counts["active"] + counts["won"] + counts["abandoned"]
    settled = counts["won"] + counts["abandoned"]
    won_xp = int(store.db.execute("SELECT COALESCE(SUM(xp), 0) FROM challenges WHERE state='won'").fetchone()[0])
    return {"offered": offered, "accepted": taken, "won": counts["won"], "abandoned": counts["abandoned"],
            "declined": counts["declined"], "expired": counts["expired"],
            "acceptRate": round(100 * taken / offered) if offered else None,
            "winRate": round(100 * counts["won"] / settled) if settled else None,
            "xpWon": won_xp, "xpLost": ABANDON_PENALTY * counts["abandoned"]}


def presence(store) -> dict:
    ev = store.db.execute(
        "SELECT kind, at FROM events WHERE kind IN ('presence_asked', 'presence_answered') ORDER BY at"
    ).fetchall()
    asked = sum(1 for e in ev if e["kind"] == "presence_asked")
    answered = sum(1 for e in ev if e["kind"] == "presence_answered")
    reactions, last_ask = [], None
    for e in ev:
        if e["kind"] == "presence_asked":
            last_ask = e["at"]
        elif last_ask is not None:
            reactions.append((e["at"] - last_ask) / 1000)
            last_ask = None
    return {"asked": asked, "answered": answered,
            "answerRate": round(100 * min(answered, asked) / asked) if asked else None,
            "avgReactionSeconds": round(sum(reactions) / len(reactions), 1) if reactions else None,
            "reflexes": store.count_events("reflex"), "absences": store.count_events("absent"),
            "autoPauses": store.count_events("autopause")}


def focus_quality(store, now: int) -> dict:
    since = now - 30 * DAY_MS
    sessions = [r for r in store.all_sessions() if r["ended_at"] is not None and r["ended_at"] >= since]
    lengths = [session_seconds(r) / 60 for r in sessions]
    lengths = [x for x in lengths if x >= 1]
    ids = {r["id"] for r in sessions}
    switches = A._app_switches(store, min((r["started_at"] for r in sessions), default=now))
    per_app = defaultdict(lambda: defaultdict(int))
    for r in store.db.execute("SELECT session_id, app, started_at, ended_at FROM focus_spans "
                              "WHERE session_id IS NOT NULL AND started_at >= ?", (since,)):
        per_app[r["session_id"]][r["app"]] += r["ended_at"] - r["started_at"]
    shares = [max(a.values()) / sum(a.values()) for sid, a in per_app.items()
              if sid in ids and sum(a.values()) > 0]
    hours = sum(lengths) / 60
    return {"sessions": len(lengths),
            "meanMinutes": round(sum(lengths) / len(lengths)) if lengths else None,
            "medianMinutes": round(_median(lengths)) if lengths else None,
            "longestMinutes": round(max(lengths)) if lengths else None,
            "switchesPerHour": round(sum(switches.get(i, 0) for i in ids) / hours, 1) if hours else None,
            "topAppShare": round(100 * sum(shares) / len(shares)) if shares else None}


def heatmap(store, now: int, weeks: int = 8) -> dict:
    """Focus minutes by weekday (Sunday first) and hour, over the last weeks."""
    since = now - weeks * 7 * DAY_MS
    grid = [[0.0] * 24 for _ in range(7)]
    for r in store.db.execute("SELECT started_at, ended_at FROM focus_spans "
                              "WHERE session_id IS NOT NULL AND ended_at > ?", (since,)):
        t, e = max(r["started_at"], since), r["ended_at"]
        while t < e:
            local = dt.datetime.fromtimestamp(t / 1000)
            nxt = int((local.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)).timestamp() * 1000)
            grid[(local.weekday() + 1) % 7][local.hour] += (min(e, nxt) - t) / 60000
            t = min(e, nxt)
    return {"weeks": weeks, "minutes": [[round(m) for m in row] for row in grid]}


def context(store, now: int) -> dict:
    power = defaultdict(lambda: {"sessions": 0, "hours": 0.0})
    weather = defaultdict(lambda: {"sessions": 0, "hours": 0.0})
    for r in store.all_sessions():
        h = session_seconds(r, until=now) / 3600
        if h <= 0:
            continue
        key = "battery" if r["on_battery"] == 1 else "plugged" if r["on_battery"] == 0 else "unknown"
        power[key]["sessions"] += 1
        power[key]["hours"] += h
        w = r["weather"] or "unknown"
        weather[w]["sessions"] += 1
        weather[w]["hours"] += h
    fmt = lambda d: [{"key": k, "sessions": v["sessions"], "hours": round(v["hours"], 1)}
                     for k, v in sorted(d.items(), key=lambda kv: -kv[1]["hours"])]
    return {"power": fmt(power), "weather": fmt(weather)}


def extra(store, now: int) -> dict:
    return {"success": True, "xpSources": xp_sources(store, now), "tasks": tasks(store, now),
            "challenges": challenges(store), "presence": presence(store),
            "focus": focus_quality(store, now), "heatmap": heatmap(store, now), "context": context(store, now)}
