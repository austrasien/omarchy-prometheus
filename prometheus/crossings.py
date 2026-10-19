"""Measures for the achievements that tie two features together (the
crossings of the feature grid): breaks and agents, coffee and challenges,
leagues and seasons, and so on. Read once per check, from the context the
other measures already built (achievements.build_context) and the store."""

from __future__ import annotations

import bisect
import datetime as dt

from . import agents
from . import timeutil as T
from .coffee import in_body

MIN = 60_000
HOUR = 60 * MIN
NIGHT_FROM = 22                      # "after 22:00" runs until 4:00


def _late(ms: int) -> bool:
    h = dt.datetime.fromtimestamp(ms / 1000).hour
    return h >= NIGHT_FROM or h < 4


def _within(periods: list[tuple[int, int]], t: int) -> bool:
    return any(s <= t < e for s, e in periods)


def _season_of(seasons: list[dict], date: str) -> str | None:
    for s in seasons:
        if s["start"] <= date <= s["end"]:
            return s["key"]
    return None


def _round_of(rounds: list[dict], date: str) -> dict | None:
    for r in rounds:
        if r["week"] <= date <= r["end"]:
            return r
    return None


def measures(store, c) -> dict:
    db = store.db
    now = c.now
    out: dict[str, float] = {}

    # ---- shared material
    cups = [r[0] for r in db.execute("SELECT at FROM coffees ORDER BY at")]
    cup_days = {T.date_str(t) for t in cups}
    events: dict[str, list[int]] = {}
    for kind, at in db.execute("SELECT kind, at FROM events WHERE kind IN "
                               "('break_taken', 'reflex', 'presence_answered') ORDER BY at"):
        events.setdefault(kind, []).append(at)
    breaks, reflexes, answers = events.get("break_taken", []), events.get("reflex", []), events.get("presence_answered", [])
    tasks = sorted(t["done"] for t in c.tasks_done)
    task_days: dict[str, int] = {}
    for t in tasks:
        d = T.date_str(t)
        task_days[d] = task_days.get(d, 0) + 1
    goal_days = ({d for d, s in c.day_focus.items() if s >= c.goal_hours * 3600} if c.goal_hours else set())
    challenges = [dict(r) for r in db.execute(
        "SELECT session_id, answered_at, ended_at, state, xp FROM challenges "
        "WHERE state IN ('active', 'won', 'abandoned') AND answered_at IS NOT NULL")]
    won = [ch for ch in challenges if ch["state"] == "won" and ch["ended_at"]]
    windows = [(ch["answered_at"], ch["ended_at"] or now) for ch in challenges]
    quest_periods: dict[str, list[tuple[int, int]]] = {}
    for qid, s, e in db.execute("SELECT quest_id, started_at, ended_at FROM quest_active"):
        quest_periods.setdefault(qid, []).append((s, e if e is not None else now))
    any_quest = [p for ps in quest_periods.values() for p in ps]
    finished = [dict(r) for r in db.execute(
        "SELECT id, done_at FROM quests WHERE done_at IS NOT NULL AND kind != 'daily'")]
    quest_days = {T.date_str(q["done_at"]) for q in finished}
    day_medals = {r[0] for r in db.execute("SELECT period_key FROM medals WHERE length(period_key) = 10")}
    medal_times = [r[0] for r in db.execute("SELECT awarded_at FROM medals")]
    rounds = c.league_weeks
    promoted = [r for r in rounds if r["outcome"] == "up"]
    seasons = [s for s in c.seasons if s.get("start")]

    # ---- sessions
    by_session = {}
    for ch in won:
        by_session[ch["session_id"]] = by_session.get(ch["session_id"], 0) + ch["xp"]
    out["sessionXp"] = max((s["focus"] // 600 + by_session.get(s["id"], 0) for s in c.sessions), default=0)
    out["finalWhistle"] = max((c.day_focus.get(r["end"], 0) / 3600 for r in rounds), default=0)
    session_days = set(c.day_sessions)
    out["seasonOpeners"] = sum(1 for s in seasons if s["start"] in session_days)
    burnt = agents.session_tokens(store, [(s["start"], s["end"]) for s in c.closed])
    out["lockedPairs"] = sum(1 for s, t in zip(c.closed, burnt)
                             if s["focus"] >= 3600 and c.session_top_share.get(s["id"], 0) >= 0.8 and t >= 10_000_000)

    # ---- presence
    out["airTraffic"] = sum(1 for t in reflexes if agents.tokens_between(store, t - 15 * MIN, t + 1) > 0)
    out["jittery"] = sum(1 for t in reflexes if in_body(cups[:bisect.bisect_right(cups, t)][-8:], t) >= 100)
    out["onWatch"] = sum(1 for t in answers if _within(any_quest, t))

    # ---- breaks
    out["letItRun"] = sum(1 for t in breaks if agents.tokens_between(store, t, t + 15 * MIN) >= 10_000_000)
    out["coffeeBreaks"] = sum(1 for t in breaks
                              if bisect.bisect_left(cups, t + 20 * MIN) > bisect.bisect_left(cups, t))
    out["questPacing"] = sum(1 for q in finished
                             if any(_within(quest_periods.get(q["id"], []), t) for t in breaks))
    out["clearHead"] = sum(1 for t in tasks
                           if any(0 <= t - b <= 30 * MIN for b in breaks[max(0, bisect.bisect_right(breaks, t) - 3):
                                                                         bisect.bisect_right(breaks, t)]))
    out["siestas"] = sum(1 for t in breaks if 13 <= dt.datetime.fromtimestamp(t / 1000).hour < 15)
    break_days: dict[str, int] = {}
    for t in breaks:
        d = T.date_str(t)
        break_days[d] = break_days.get(d, 0) + 1
    out["sustainableGoal"] = sum(1 for d in goal_days if break_days.get(d, 0) >= 2)

    # ---- tasks
    out["bonusRound"] = sum(1 for t in tasks if _within(windows, t))
    out["delegatedTodo"] = sum(1 for t in tasks if agents.tokens_between(store, t - HOUR, t + 1) >= 10_000_000)
    out["nightList"] = sum(1 for t in tasks if _late(t))
    rainy = {s["date"] for s in c.closed if s.get("weather") == "rain"}
    out["rainyList"] = sum(n for d, n in task_days.items() if d in rainy)
    out["goalAndDone"] = sum(1 for d in goal_days if task_days.get(d, 0) >= 5)
    out["taskXp"] = sum(t["xp"] for t in c.tasks_done)

    # ---- challenges
    out["sideQuests"] = sum(1 for ch in won if _within(any_quest, ch["ended_at"]))
    out["secondWind"] = sum(1 for ch in won
                            if bisect.bisect_right(cups, ch["answered_at"]) > bisect.bisect_left(cups, ch["answered_at"] - 45 * MIN))
    out["lateExtensions"] = sum(1 for ch in won if _late(ch["ended_at"]))
    out["overachiever"] = sum(1 for ch in won if T.date_str(ch["ended_at"]) in goal_days)
    out["challengeXp"] = sum(ch["xp"] for ch in won)

    # ---- quests
    out["caffeinatedQuest"] = max((sum(1 for t in cups if _within(ps, t)) for ps in quest_periods.values()), default=0)
    out["onTarget"] = sum(1 for q in finished if T.date_str(q["done_at"]) in goal_days)
    current = rounds[-1]["after"] if rounds else 0
    leagues_done = set()
    for q in finished:
        r = _round_of(rounds, T.date_str(q["done_at"]))
        leagues_done.add(r["before"] if r else current)
    out["questLeagues"] = len(leagues_done) if finished else 0
    per_season: dict[str, int] = {}
    for q in finished:
        k = _season_of(seasons, T.date_str(q["done_at"]))
        if k:
            per_season[k] = per_season.get(k, 0) + 1
    out["questSeason"] = max(per_season.values(), default=0)
    out["medalMission"] = len(quest_days & day_medals)

    # ---- XP
    out["agentXp"] = sum(agents.xp_for(t) for t in c.day_tokens.values())
    out["medalXp"] = int(db.execute("SELECT COALESCE(SUM(xp), 0) FROM medals").fetchone()[0]
                         + db.execute("SELECT COALESCE(SUM(xp), 0) FROM season_medals").fetchone()[0])

    # ---- medals, leagues, seasons
    medals_season: dict[str, int] = {}
    for t in medal_times:
        k = _season_of(seasons, T.date_str(t))
        if k:
            medals_season[k] = medals_season.get(k, 0) + 1
    out["decoratedSeason"] = max(medals_season.values(), default=0)
    out["medalPromotion"] = max((sum(1 for t in medal_times if r["week"] <= T.date_str(t) <= r["end"])
                                 for r in promoted), default=0)
    out["doubleCrown"] = sum(1 for s in seasons if s.get("grade") in ("S", "A", "B")
                             and any(s["start"] <= r["end"] <= s["end"] for r in promoted))
    out["siliconLeague"] = sum(1 for r in promoted
                               if sum(t for d, t in c.day_tokens.items() if r["week"] <= d <= r["end"]) >= 500_000_000)
    out["goalClimb"] = max((sum(1 for d in goal_days if r["week"] <= d <= r["end"]) for r in promoted), default=0)

    # ---- coffee
    cups_season: dict[str, int] = {}
    for t in cups:
        k = _season_of(seasons, T.date_str(t))
        if k:
            cups_season[k] = cups_season.get(k, 0) + 1
    out["seasonedRoast"] = max(cups_season.values(), default=0)
    out["goalPlus"] = sum(1 for d in goal_days if c.day_tokens.get(d, 0) >= 100_000_000)
    rain_sessions = [(s["start"], s["end"]) for s in c.closed if s.get("weather") == "rain"]
    out["rainyBrew"] = sum(1 for t in cups if _within(rain_sessions, t))
    best, records = None, 0
    for d in sorted(c.day_earned):
        v = c.day_earned[d]
        if best is not None and v > best and d in cup_days:
            records += 1
        best = v if best is None else max(best, v)
    out["caffeinatedRecord"] = records
    return out
