"""Achievements: a catalogue of families, each with one or more tiers, and
the measures that unlock them, all computed from Prometheus' own records.

A family has a measure (a number, or None when nothing qualifies yet) and
thresholds. Each threshold is a tier: an achievement with a name, a
description, a line for when it unlocks, and an XP reward. Tiered rewards
grow 5 XP per tier up to the 10th (50 XP), then 2 XP per tier; a single
achievement is worth 10 XP. Each family has a weight (x1, x2, x3) by how hard
it is. Secret achievements are worth 25 XP, flat.
"""

from __future__ import annotations

import datetime as dt
import functools
import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import agents
from . import geekdates
from . import timeutil as T
from .store import ABANDON_PENALTY, session_seconds

QUALIFYING_SECONDS = 10 * 60      # shorter sessions count for nothing

# Rarity, from the XP a tier is worth (its difficulty): under 30 normal, then
# common, rare, epic, and legendary from 360 XP. Secrets are epic; the
# calendar's dates are common.
RARITIES = ["normal", "common", "rare", "epic", "legendary"]
FIXED_RARITY_XP = {"normal": 10, "common": 20, "rare": 40, "epic": 80, "legendary": 150}
LEADERBOARD_WARMUP_DAYS = 30     # a new top-10 entry only counts this long after the first day
RARITY_XP = [30, 60, 140, 360]


def rarity_for(xp: int, secret: bool = False) -> str:
    if secret:
        return "epic"
    for name, bound in zip(RARITIES, RARITY_XP):
        if xp < bound:
            return name
    return "legendary"
DAY = 24 * 3600
H = 3600


@dataclass
class Family:
    id: str
    title: str
    measure: Callable[["Context"], float | None]
    thresholds: list[float]
    name: Callable[[float], str]
    desc: Callable[[float], str]
    quips: list[str]
    compare: str = "ge"           # ge: measure >= threshold; gt: >; lt: <
    secret: bool = False
    unit: str = ""               # shown with the progress: "", "h", "%", "days"
    scale: float = 1.0           # measure / scale is what is shown
    weight: int = 1              # x1 easy, x2 hard, x3 extreme
    # A rarity chosen by hand, per tier (or one for all), for achievements
    # whose difficulty is not in their numbers; XP then follows the rarity.
    rarities: list | str | None = None

    @property
    def single(self) -> bool:
        return len(self.thresholds) == 1

    def tier_id(self, i: int) -> str:
        return self.id if self.single else f"{self.id}:{self.thresholds[i]:g}"

    def xp(self, i: int) -> int:
        if self.rarities is not None:
            return FIXED_RARITY_XP[self.rarity(i)]
        if self.secret:
            return 25
        if self.single:
            base = 10
        elif i < 10:
            base = 5 * (i + 1)
        else:
            base = 50 + 2 * (i - 9)
        return base * self.weight

    def rarity(self, i: int) -> str:
        if self.rarities is not None:
            return self.rarities if isinstance(self.rarities, str) else self.rarities[i]
        return rarity_for(self.xp(i), self.secret)

    def quip(self, i: int) -> str:
        return self.quips[i % len(self.quips)].format(n=_fmt(self.thresholds[i] / self.scale))

    def passes(self, value: float | None, i: int) -> bool:
        if value is None:
            return False
        t = self.thresholds[i]
        if self.compare == "lt":
            return value < t
        if self.compare == "gt":
            return value > t
        return value >= t


def _fmt(x: float) -> str:
    return f"{x:g}"


# --------------------------------------------------------------- context


@dataclass
class Context:
    """Everything the measures need, read once per evaluation."""

    now: int
    sessions: list[dict] = field(default_factory=list)       # qualifying ones, open included
    closed: list[dict] = field(default_factory=list)         # qualifying and closed
    day_focus: dict = field(default_factory=dict)            # logical date -> focus seconds
    day_sessions: dict = field(default_factory=dict)         # logical date -> qualifying sessions
    tasks_done: list[dict] = field(default_factory=list)
    challenges_won: int = 0
    triples: int = 0
    absences: int = 0
    procrastinations: dict = field(default_factory=dict)     # task text -> times put off
    goal_hours: float | None = None                          # daily goal, if any
    level: int = 1
    monotask: float = 0.0                                    # longest one-app stretch in a session, s
    reflexes: int = 0                                        # "Still there?" answered in < 10 s
    inbox_zero: int = 0                                      # times the to-do list was emptied
    put_off: list = field(default_factory=list)              # (task text, when) of procrastinated sessions
    switches: dict = field(default_factory=dict)             # session id -> app changes
    interrupted: set = field(default_factory=set)            # sessions with an automatic pause
    day_first: dict = field(default_factory=dict)            # logical date -> first session start, ms
    day_xp: dict = field(default_factory=dict)               # logical date -> XP earned (no achievements)
    goal: dict | None = None                                 # {hours, period}
    day_tracked: dict = field(default_factory=dict)          # logical date -> tracked seconds (all apps)
    session_top_share: dict = field(default_factory=dict)    # session id -> share of its top app
    challenge_states: list = field(default_factory=list)     # challenge states, oldest first
    end_dates: set = field(default_factory=set)              # local dates on which a session ended
    quests: list = field(default_factory=list)               # every quest, with its activity (quests.summary)
    quests_full: int = 0                                     # times ten quests were open at once
    quest_sweeps: int = 0                                    # times the multi-day quests were all finished
    league_weeks: list = field(default_factory=list)         # settled weeks (competition.leagues history)
    seasons: list = field(default_factory=list)              # every season, the running one last
    day_earned: dict = field(default_factory=dict)           # date -> earned XP (competition.Ledger)
    session_focus: list = field(default_factory=list)        # (start ms, focus s) of every session
    events: dict = field(default_factory=dict)               # event kind -> count (usage of the tool)
    day_tokens: dict = field(default_factory=dict)           # date -> agent tokens
    agent: dict = field(default_factory=dict)                # agent measures (agents.measures)


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@functools.lru_cache(maxsize=65_536)
def _local(ms: int) -> dt.datetime:
    # The same session starts and ends are asked for by many families.
    return dt.datetime.fromtimestamp(ms / 1000).astimezone()


def build_context(store, now: int, level: int) -> Context:
    ctx = Context(now=now, level=level)
    for r in store.all_sessions():
        focus = session_seconds(r, until=now)
        if focus < QUALIFYING_SECONDS:
            continue
        end = r["ended_at"] if r["ended_at"] is not None else now
        s = {
            "id": r["id"], "task": r["task"], "start": r["started_at"], "end": end,
            "open": r["ended_at"] is None, "focus": focus, "pause_ms": r["total_pause_ms"] or 0,
            "reason": r["end_reason"], "battery": r["on_battery"], "weather": r["weather"],
            "temp": r["temp_c"], "date": T.date_str(r["started_at"]),
            "battery_pct": r["battery_pct"],
        }
        ctx.sessions.append(s)
        if not s["open"]:
            ctx.closed.append(s)
        ctx.day_focus[s["date"]] = ctx.day_focus.get(s["date"], 0) + focus
        ctx.day_sessions[s["date"]] = ctx.day_sessions.get(s["date"], 0) + 1
        ctx.day_first[s["date"]] = min(ctx.day_first.get(s["date"], s["start"]), s["start"])
        ctx.day_xp[s["date"]] = ctx.day_xp.get(s["date"], 0) + focus // 600
    ctx.sessions.sort(key=lambda s: s["start"])

    # Procrastinations count every put-off session, however short.
    for r in store.all_sessions():
        if r["end_reason"] == "procrastinated" and r["task"]:
            ctx.procrastinations[r["task"]] = ctx.procrastinations.get(r["task"], 0) + 1
            ctx.put_off.append((r["task"], r["ended_at"] or now))

    ctx.tasks_done = [{"text": r["text"], "created": r["created_at"], "done": r["done_at"], "xp": r["xp"] or 1}
                      for r in store.done_tasks()]
    for t in ctx.tasks_done:
        d = T.date_str(t["done"])
        ctx.day_xp[d] = ctx.day_xp.get(d, 0) + t["xp"]
    for r in store.db.execute("SELECT ended_at, xp FROM challenges WHERE state='won'"):
        d = T.date_str(r["ended_at"])
        ctx.day_xp[d] = ctx.day_xp.get(d, 0) + r["xp"]
    for r in store.db.execute("SELECT ended_at FROM challenges WHERE state='abandoned' AND ended_at IS NOT NULL"):
        d = T.date_str(r["ended_at"])
        ctx.day_xp[d] = ctx.day_xp.get(d, 0) - ABANDON_PENALTY
    ctx.day_tokens = agents.tokens_by_day(store)
    for d, tokens in ctx.day_tokens.items():
        ctx.day_xp[d] = ctx.day_xp.get(d, 0) + agents.xp_for(tokens)
    ctx.interrupted = store.sessions_with_event("autopause") | store.sessions_with_event("absent")
    ctx.challenge_states = [r[0] for r in store.db.execute("SELECT state FROM challenges ORDER BY offered_at")]
    ctx.end_dates = {_local(s["end"]).date() for s in ctx.closed}
    _read_spans(store, ctx)
    ctx.reflexes = store.count_events("reflex")
    ctx.inbox_zero = store.count_events("inbox_zero")
    ctx.challenges_won = int(store.db.execute("SELECT COUNT(*) FROM challenges WHERE state='won'").fetchone()[0])
    ctx.triples = int(store.db.execute(
        "SELECT COUNT(*) FROM (SELECT session_id FROM challenges WHERE state='won' "
        "GROUP BY session_id HAVING COUNT(*) >= 3)").fetchone()[0])
    ctx.absences = store.count_events("absent")
    goal = store.get_setting("hoursGoal")
    if goal:
        ctx.goal = {"hours": float(goal["hours"]), "period": goal.get("period")}
    if goal and goal.get("period") == "day":
        ctx.goal_hours = float(goal["hours"])
    from .quests import Quests    # late: quests imports the store, like this module
    ctx.quests = Quests(store).summary(now)
    ctx.quests_full = store.count_events("quests_full")
    ctx.quest_sweeps = store.count_events("quest_sweep")
    from . import competition as C
    ledger = C.Ledger(store, now)
    ctx.league_weeks = C.leagues(ledger)["history"]
    ctx.seasons = C.seasons(ledger)
    ctx.day_earned = dict(ledger.xp)
    ctx.session_focus = [(start, sec) for sec, start, _, _ in ledger.session_rows]
    ctx.events = {r[0]: r[1] for r in store.db.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind")}
    ctx.agent = agents.measures(store, ctx.closed)
    return ctx


def _span_totals(rows, gap_ms: int = 60_000) -> dict:
    """Over spans ordered by session then start: tracked time per day, the
    main app's share of each session, app switches per session (a pause or an
    idle cut in one app is not a switch), and the longest stretch in one app
    inside a session (short gaps bridged), in ms."""
    out = {"day_tracked": {}, "top_share": {}, "switches": {}, "best": 0}
    day_tracked, switches = out["day_tracked"], out["switches"]
    apps, sid, app, run_start, run_end, best = {}, None, None, 0, 0, 0

    def close_session():
        total = sum(apps.values())
        if sid is not None and total > 0:
            out["top_share"][sid] = max(apps.values()) / total

    for r in rows:
        start, end = r["started_at"], r["ended_at"]
        d = T.date_str(start)
        day_tracked[d] = day_tracked.get(d, 0) + (end - start) / 1000
        if r["session_id"] is None:
            continue
        if r["session_id"] != sid:
            close_session()
            sid, app, apps = r["session_id"], r["app"], {}
            switches[sid] = 0
            run_start, run_end = start, end
        else:
            if r["app"] != app:
                switches[sid] += 1
            if r["app"] == app and start - run_end <= gap_ms:
                run_end = max(run_end, end)
            else:
                run_start, run_end = start, end
            app = r["app"]
        apps[app] = apps.get(app, 0) + end - start
        best = max(best, run_end - run_start)
    close_session()
    out["best"] = best
    return out


# Spans settled before today (ended, in a session ended too, or in none) never
# change: their totals are kept on the store and computed again only when the
# day turns, the day start moves, or their number changes (an import).
_LIVE = ("(ended_at >= :cut OR session_id IS NOT NULL AND session_id IN "
         "(SELECT id FROM sessions WHERE ended_at IS NULL OR ended_at >= :cut))")


def _read_spans(store, ctx: Context) -> None:
    cut = T.day_start(ctx.now)
    # Index lookups, merged here: SQLite scans the whole table for an OR over
    # a subquery, or a UNION.
    cols = "id, session_id, app, started_at, ended_at"
    rows = {r["id"]: r for r in store.db.execute(
        f"SELECT {cols} FROM focus_spans INDEXED BY idx_spans_ended WHERE ended_at >= ?", (cut,))}
    sids = [r[0] for r in store.db.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL OR ended_at >= ?", (cut,))]
    if sids:
        marks = ",".join("?" * len(sids))
        for r in store.db.execute(f"SELECT {cols} FROM focus_spans WHERE session_id IN ({marks})", sids):
            rows[r["id"]] = r
    live = sorted(rows.values(), key=lambda r: (r["session_id"] is not None, r["session_id"] or "", r["started_at"]))
    settled_n = store.db.execute("SELECT COUNT(*) FROM focus_spans").fetchone()[0] - len(live)
    key = (cut, T.day_start_hour(), settled_n)
    cache = getattr(store, "_span_cache", None)
    if cache is None or cache[0] != key:
        rows = store.db.execute(
            f"SELECT session_id, app, started_at, ended_at FROM focus_spans WHERE NOT {_LIVE} "
            "ORDER BY session_id, started_at", {"cut": cut})
        cache = (key, _span_totals(rows))
        store._span_cache = cache
    old, new = cache[1], _span_totals(live)
    ctx.day_tracked = dict(old["day_tracked"])
    for d, sec in new["day_tracked"].items():
        ctx.day_tracked[d] = ctx.day_tracked.get(d, 0) + sec
    ctx.session_top_share = {**old["top_share"], **new["top_share"]}
    ctx.switches = {**old["switches"], **new["switches"]}
    ctx.monotask = max(old["best"], new["best"]) / 1000


def _app_switches(store, since: int = 0) -> dict:
    """App changes per session (a pause or an idle cut in one app is not a switch)."""
    out, sid, app = {}, None, None
    for r in store.db.execute(
        "SELECT session_id, app FROM focus_spans WHERE session_id IS NOT NULL AND started_at >= ? "
        "ORDER BY session_id, started_at", (since,)
    ):
        if r["session_id"] != sid:
            sid, app = r["session_id"], r["app"]
            out[sid] = 0
        elif r["app"] != app:
            out[sid] += 1
            app = r["app"]
    return out


# -------------------------------------------------------------- measures


def _quests_done(c: Context, kind: str | None = None) -> list[dict]:
    """Short and long quests finished (deleting one later does not undo it)."""
    return [q for q in c.quests if q["kind"] != "daily" and q["done"] is not None
            and (kind is None or q["kind"] == kind)]


def _count(xs) -> int | None:
    return len(xs) or None


def _best(c: Context, key: str) -> float | None:
    return max((q["activity"][key] for q in c.quests), default=0) or None


def _daily_run(c: Context) -> int | None:
    """Longest run of consecutive days one daily quest was done."""
    return max((_longest_run(set(q["done_days"])) for q in c.quests if q["kind"] == "daily"), default=0) or None


def _hour_share(q: dict, hours: set[int]) -> float:
    minutes = q["activity"]["hours"]
    total = sum(minutes)
    return sum(m for h, m in enumerate(minutes) if h in hours) / total if total else 0.0


NIGHT_HOURS = {22, 23, 0, 1, 2, 3}       # after 22 h, until 4 h
DAWN_HOURS = {4, 5, 6, 7}                # before 8 h
TIMED_QUEST_MIN_SECONDS = H              # a night or dawn quest needs some real focus


def _timed_quests(hours: set[int]):
    return lambda c: _count([q for q in _quests_done(c) if q["activity"]["seconds"] >= TIMED_QUEST_MIN_SECONDS
                             and _hour_share(q, hours) > 0.5])


def _speedruns(c: Context) -> int | None:
    return _count([q for q in _quests_done(c, "short") if 1 <= q["days_worked"] <= 2])


def _marathons(c: Context) -> int | None:
    return _count([q for q in _quests_done(c, "long") if q["first_active"] is not None
                   and q["done"] - q["first_active"] >= 30 * DAY * 1000])


def _league_peak(c: Context) -> int | None:
    return max((w["after"] for w in c.league_weeks), default=0) or None


def _promotions(c: Context) -> int | None:
    return _count([w for w in c.league_weeks if w["outcome"] == "up"])


def _bounce_backs(c: Context) -> int | None:
    weeks = c.league_weeks
    return _count([1 for a, b in zip(weeks, weeks[1:]) if a["outcome"] == "down" and b["outcome"] == "up"])


def _promotion_run(c: Context) -> int | None:
    best = run = 0
    for w in c.league_weeks:
        run = run + 1 if w["outcome"] == "up" else 0
        best = max(best, run)
    return best or None


def _diamond_weeks(c: Context) -> int | None:
    """Weeks played in Diamond (a league round is two weeks)."""
    return 2 * len([w for w in c.league_weeks if w["before"] == 9]) or None


def _seasons_with(c: Context, bars: int) -> int | None:
    return _count([s for s in c.seasons if s["bars"] >= bars])


def _graded(c: Context) -> list[dict]:
    return [s for s in c.seasons if s["grade"] is not None]


def _honor_run(c: Context) -> int | None:
    best = run = 0
    for s in _graded(c):
        run = run + 1 if s["grade"] in ("S", "A", "B") else 0
        best = max(best, run)
    return best or None


def _phoenix(c: Context) -> int | None:
    g = _graded(c)
    return _count([1 for a, b in zip(g, g[1:]) if a["grade"] == "F" and b["grade"] in ("A", "S")])


def _day_records(c: Context) -> int | None:
    from .competition import records
    return records([(d, x) for d, x in c.day_earned.items()]) or None


def _session_records(c: Context) -> int | None:
    from .competition import records
    return records(c.session_focus) or None


def _day_podiums(c: Context) -> int | None:
    from .competition import podiums
    return podiums([(d, x) for d, x in c.day_earned.items()]) or None


def _event(kind: str):
    return lambda c: c.events.get(kind, 0) or None


SETTING_KINDS = ("setting:handle", "setting:daystart", "setting:presence", "setting:goal",
                 "setting:apps", "setting:words", "setting:aliases")
TABS = ("session", "tasks", "quests", "leagues", "seasons", "achievements", "stats", "leaderboard", "settings")


def _power_user(c: Context) -> int | None:
    touched = all(c.events.get(k) for k in SETTING_KINDS)
    export = any(k.startswith("setting:export:") for k in c.events)
    return 1 if touched and export else None


def _grand_tour(c: Context) -> int | None:
    return 1 if all(c.events.get(f"tab:{t}") for t in TABS) else None


def _new_top10(values: list[tuple], after) -> int:
    """Entries that made the top 10 of everything so far, from `after` on.
    `values`: (order key, value), the order key comparable with `after`."""
    best, n = [], 0                      # the 10 best so far, a min-heap
    for key, v in sorted(values):
        if key >= after and (len(best) < 10 or v >= best[0]):
            n += 1
        if len(best) < 10:
            heapq.heappush(best, v)
        elif v > best[0]:
            heapq.heapreplace(best, v)
    return n


def _hall_of_fame(c: Context) -> int | None:
    days = sorted(c.day_earned)
    if not days:
        return None
    after = (_date(days[0]) + dt.timedelta(days=LEADERBOARD_WARMUP_DAYS)).isoformat()
    return _new_top10(list(c.day_earned.items()), after) or None


def _token_fame(c: Context) -> int | None:
    days = sorted(d for d, v in c.day_tokens.items() if v > 0)
    if not days:
        return None
    after = (_date(days[0]) + dt.timedelta(days=LEADERBOARD_WARMUP_DAYS)).isoformat()
    return _new_top10(list(c.day_tokens.items()), after) or None


def _session_legend(c: Context) -> int | None:
    if not c.session_focus:
        return None
    after = min(s for s, _ in c.session_focus) + LEADERBOARD_WARMUP_DAYS * 86_400_000
    return _new_top10(c.session_focus, after) or None


def _pivots(c: Context) -> int | None:
    return _count([q for q in c.quests if q["deleted"] is not None and q["activity"]["seconds"] > 5 * H])



def _longest_run(dates: set[str]) -> int:
    days = sorted(_date(d) for d in dates)
    best = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    return best


def _streak_sessions(n: int):
    return lambda c: _longest_run({d for d, k in c.day_sessions.items() if k >= n}) or None


def _streak_hours(h: float):
    return lambda c: _longest_run({d for d, s in c.day_focus.items() if s >= h * H}) or None


def _rolling(c: Context, days: int) -> float | None:
    if not c.day_focus:
        return None
    best = 0
    for d in c.day_focus:
        end = _date(d)
        best = max(best, sum(c.day_focus.get((end - dt.timedelta(days=k)).isoformat(), 0) for k in range(days)))
    return best


def _week_focus(c: Context) -> float | None:
    weeks = defaultdict(float)
    for d, s in c.day_focus.items():
        y, w = T.week_key(_date(d))
        weeks[(y, w)] += s
    return max(weeks.values()) if weeks else None


def _tasks_per(c: Context, key) -> float | None:
    counts = defaultdict(int)
    for t in c.tasks_done:
        counts[key(_date(T.date_str(t["done"])))] += 1
    return max(counts.values()) if counts else None


def _morning(c: Context) -> float | None:
    """Earliest start hour, among sessions started between 4:00 and 8:00."""
    hours = []
    for s in c.sessions:
        t = _local(s["start"])
        h = t.hour + t.minute / 60
        if 4 <= h < 8:
            hours.append(h)
    return min(hours) if hours else None


def _night_hour(s: dict) -> float:
    """When a session ended, in hours from the midnight opening its day (25.5 = 1:30 next night)."""
    day = _date(s["date"])
    midnight = dt.datetime.combine(day, dt.time()).astimezone()
    return (_local(s["end"]) - midnight).total_seconds() / 3600


def _night(c: Context) -> float | None:
    return max((_night_hour(s) for s in c.sessions), default=None)


def _weekend(c: Context) -> float | None:
    dates = set(c.day_sessions)
    for d in dates:
        day = _date(d)
        if day.weekday() == 5 and (day + dt.timedelta(days=1)).isoformat() in dates:
            return 1
    return None


def _friday_night(c: Context) -> float | None:
    for s in c.sessions:
        if _date(s["date"]).weekday() == 4 and _night_hour(s) > 19:
            return 1
    return None


def _new_year(c: Context) -> float | None:
    for s in c.sessions:
        t = _local(s["start"])
        if (t.month, t.day) == (1, 1) or s["date"].endswith("-01-01"):
            return 1
    return None


def moon_age(ms: int) -> float:
    """Days since the last new moon (synodic month from the 2000-01-06 new moon)."""
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc).timestamp() * 1000
    return ((ms - ref) / (DAY * 1000)) % 29.530588853


def _full_moon(c: Context) -> float | None:
    return 1 if any(abs(moon_age(s["start"]) - 14.77) <= 1 for s in c.sessions) else None


def _anniversary(c: Context) -> float | None:
    if not c.sessions:
        return None
    first = c.sessions[0]["start"]
    return 1 if any(s["start"] - first >= 365 * DAY * 1000 for s in c.sessions) else None


def _weather(kind: str):
    return lambda c: sum(1 for s in c.closed if s["weather"] == kind) or None


def _same_day_tasks(c: Context) -> float | None:
    return sum(1 for t in c.tasks_done if T.date_str(t["created"]) == T.date_str(t["done"])) or None


def _redemptions(c: Context) -> float | None:
    """Tasks finished after a session on them had been procrastinated."""
    n = sum(1 for t in c.tasks_done if any(task == t["text"] and when <= t["done"] for task, when in c.put_off))
    return n or None


def _months(c: Context) -> dict:
    counts = defaultdict(int)
    for d in c.day_sessions:
        counts[d[:7]] += 1
    return counts


def _calm_sessions(c: Context) -> float | None:
    """Sessions of 1 h+ with fewer than 5 app switches per hour."""
    n = 0
    for s in c.closed:
        if s["focus"] >= H and c.switches.get(s["id"], 0) / (s["focus"] / H) < 5:
            n += 1
    return n or None


def _bookends(c: Context) -> float | None:
    early, late = set(), set()
    for s in c.sessions:
        t = _local(s["start"])
        if 4 <= t.hour < 7:
            early.add(s["date"])
        if _night_hour(s) > 22:
            late.add(s["date"])
    return len(early & late) or None


def _midnight_crossings(c: Context) -> float | None:
    return sum(1 for s in c.sessions if _local(s["start"]).date() != _local(s["end"]).date()) or None


def _on_dates(dates: set[tuple[int, int]]):
    def measure(c: Context) -> float | None:
        for s in c.sessions:
            t = _local(s["start"])
            if (t.month, t.day) in dates:
                return 1
        return None
    return measure


def _goal_hits(period: str):
    """How many days / weeks / months reached the hours goal set for that period."""
    def measure(c: Context) -> float | None:
        if not c.goal or c.goal["period"] != period:
            return None
        buckets = defaultdict(float)
        for d, s in c.day_focus.items():
            day = _date(d)
            key = d if period == "day" else T.week_key(day) if period == "week" else d[:7]
            buckets[key] += s
        return sum(1 for s in buckets.values() if s >= c.goal["hours"] * H) or None
    return measure


def _personal_bests(c: Context) -> float | None:
    """Weeks that beat every week before them (the first week is no record)."""
    weeks = defaultdict(float)
    for d, s in c.day_focus.items():
        weeks[T.week_key(_date(d))] += s
    best, records = None, 0
    for key in sorted(weeks):
        if best is not None and weeks[key] > best:
            records += 1
        best = weeks[key] if best is None else max(best, weeks[key])
    return records or None


def _tod(ms: int) -> float:
    t = _local(ms)
    return t.hour * 60 + t.minute


def _clockwork(c: Context) -> float | None:
    """Longest run of days whose first session starts within 15 min of the day before."""
    days = sorted(c.day_first)
    best = run = 0
    prev = None
    for d in days:
        cur = _date(d)
        if prev is not None and (cur - _date(prev)).days == 1 and abs(_tod(c.day_first[d]) - _tod(c.day_first[prev])) <= 15:
            run += 1
        else:
            run = 1
        best = max(best, run)
        prev = d
    return best if best >= 2 else None


def _early_streak(c: Context) -> float | None:
    early = set()
    for s in c.sessions:
        t = _local(s["start"])
        if 4 <= t.hour < 8:
            early.add(s["date"])
    return _longest_run(early) or None


def _uninterrupted(c: Context) -> float | None:
    return sum(1 for s in c.closed if s["focus"] >= 2 * H and s["id"] not in c.interrupted) or None


def _years_on(month: int, day: int):
    """Different years with a session on that calendar date."""
    def measure(c: Context) -> float | None:
        years = {_local(s["start"]).year for s in c.sessions
                 if (_local(s["start"]).month, _local(s["start"]).day) == (month, day)}
        return len(years) or None
    return measure


def _on_exact(year: int, month: int, day: int):
    def measure(c: Context) -> float | None:
        return 1 if any(_local(s["start"]).date() == dt.date(year, month, day) for s in c.sessions) else None
    return measure


def _longest_gap_comeback(c: Context) -> float | None:
    """Longest break, in days, that ended with a new session."""
    best = 0
    for a, b in zip(c.sessions, c.sessions[1:]):
        best = max(best, (b["start"] - a["end"]) / (DAY * 1000))
    return best or None


def _monomaniac(c: Context) -> float | None:
    hours = defaultdict(float)
    for s in c.sessions:
        if s["task"]:
            hours[s["task"].strip().casefold()] += s["focus"]
    return max(hours.values(), default=None)


def _focus_purity(c: Context) -> float | None:
    """Days where 90 %+ of tracked time was in session (at least 1 h tracked)."""
    n = sum(1 for d, tracked in c.day_tracked.items()
            if tracked >= H and c.day_focus.get(d, 0) >= 0.9 * tracked)
    return n or None


def _locked_in(c: Context) -> float | None:
    return sum(1 for s in c.closed if s["focus"] >= H and c.session_top_share.get(s["id"], 0) >= 0.9) or None


def _yes_man(c: Context) -> float | None:
    best = run = 0
    for st in c.challenge_states:
        if st in ("active", "won", "abandoned"):
            run += 1
            best = max(best, run)
        elif st in ("declined", "expired"):
            run = 0
    return best or None


def _perfect_weeks(c: Context) -> float | None:
    weeks = defaultdict(set)
    for d in c.day_sessions:
        weeks[T.week_key(_date(d))].add(d)
    return sum(1 for days in weeks.values() if len(days) == 7) or None


def _month_hours(c: Context) -> float | None:
    months = defaultdict(float)
    for d, s in c.day_focus.items():
        months[d[:7]] += s
    return max(months.values(), default=None)


def _year_hours(c: Context) -> float | None:
    years = defaultdict(float)
    for d, s in c.day_focus.items():
        years[d[:4]] += s
    return max(years.values(), default=None)


def _goal_streak(c: Context) -> float | None:
    if not c.goal_hours:
        return None
    return _longest_run({d for d, s in c.day_focus.items() if s >= c.goal_hours * H}) or None


# ------------------------------------------------------------- catalogue

_CLOCK = {19: "19:00", 20: "20:00", 21: "21:00", 22: "22:00", 23: "23:00",
          24: "midnight", 25: "1:00", 26: "2:00", 27: "3:00", 28: "4:00"}


def _hours_label(h: float) -> str:
    return _CLOCK.get(int(h), f"{int(h) % 24}:00")


def _tiers(start, stop, step, extra=()):
    out = list(range(start, stop + 1, step))
    for e in extra:
        if e not in out:
            out.append(e)
    return out


FAMILIES: list[Family] = [
    # ---- volume
    Family("sessions", "Shipping cadence", lambda c: len(c.closed) or None, [10 * 2 ** k for k in range(10)],
           lambda t: f"Shipping Cadence {t:g}", lambda t: f"Complete {t:g} sessions.",
           ["Ten sessions. The flywheel spins. Keep regulators away from it.",
            "Twenty. Iteration speed is the only moat that matters.",
            "Forty sessions. You're compounding faster than the Fed can print.",
            "Eighty. That's not a habit anymore, that's a launch cadence.",
            "{n} sessions. SpaceX launches less often, and they have a whole company.",
            "{n}. Your commit graph would make a 10x engineer blush.",
            "{n} sessions. Habits are just compounding with better branding.",
            "{n}. At this cadence you're a utility, not a person.",
            "{n} sessions. The universe trends toward entropy; you trend toward output.",
            "{n}. Somewhere a union rep is drafting a complaint about you."]),
    Family("tasks", "Zero to one", lambda c: len(c.tasks_done) or None, [10 * 2 ** k for k in range(10)],
           lambda t: f"Zero to {t:g}", lambda t: f"Finish {t:g} tasks.",
           ["Zero to ten. Thiel would call it a start. A small one.",
            "Twenty tasks shipped while the committee is still drafting the memo.",
            "Forty. Execution is the only ideology that compiles.",
            "Eighty. You ship like paperwork is a myth from a dying civilization.",
            "{n} tasks. Done is the engine; perfect is a tax.",
            "{n} closed. Backlogs tremble when you open your laptop.",
            "{n}. Your throughput just got its own GDP line.",
            "{n} tasks. Ideas are cheap; you're the expensive part.",
            "{n}. If tasks were taxable, you'd be moving to Puerto Rico.",
            "{n} tasks shipped. Zero to one, repeated until it's a power law."]),
    Family("cumul", "Compound interest", lambda c: sum(s["focus"] for s in c.sessions) or None,
           [h * H for h in range(100, 10001, 100)],
           lambda t: f"Compound Interest {t / H:g} h", lambda t: f"Reach {t / H:g} h of focus in total.",
           ["{n} hours. Time in the market beats timing the market.",
            "{n} hours of focus, untaxed. For now.",
            "{n} hours. Your future self just sent a thank-you note from orbit.",
            "{n} hours. Compounding is the eighth wonder; you're the ninth.",
            "{n} hours. Entropy is losing, and it knows it.",
            "{n} hours. Somewhere, a central planner felt a disturbance.",
            "{n} hours. The singularity is near; you're ahead of schedule.",
            "{n} hours. Not a career, a trajectory.",
            "{n} hours. Malthus was wrong and so is your procrastination.",
            "{n} hours. Accelerate."], unit="h", scale=H),
    Family("levels", "Ascension", lambda c: c.level, [5, 10, 20, 30, 50],
           lambda t: f"Level {t:g}", lambda t: f"Reach level {t:g}.",
           ["Level 5. Still pre-seed, but the deck is looking good.",
            "Level 10. Series A energy. Don't let them dilute you.",
            "Level 20. Pre-IPO. The normies are starting to notice.",
            "Level 30. Your résumé now requires a transhumanist to read it.",
            "Level 50. Kardashev Type I, personally."]),

    # ---- endurance and intensity
    Family("endurance", "Long burn", lambda c: max((s["focus"] for s in c.sessions), default=None),
           [h * H for h in (2, 3, 4, 5, 6)],
           lambda t: f"Long Burn {t / H:g} h", lambda t: f"Hold a single session for {t / H:g} h of focus.",
           ["Two hours in one go. Attention spans are a choice.",
            "Three hours. The dopamine merchants lost a customer.",
            "Four hours straight. Your chair is now load-bearing infrastructure.",
            "Five hours. You don't take breaks, breaks take you. Eventually.",
            "Six hours. Biology filed a support ticket. Closed: won't fix."], unit="h", scale=H),
    Family("monk", "Full stack monk",
           lambda c: max((s["focus"] for s in c.closed if s["pause_ms"] == 0), default=None),
           [4 * H], lambda t: "Full Stack Monk", lambda t: "Hold 4 h in one session without a single pause.",
           ["Four hours, zero pauses. Your bladder signed an NDA."], secret=True, unit="h", scale=H),
    Family("intensity", "Time dilation",
           lambda c: max(c.day_focus.values()) / DAY * 100 if c.day_focus else None, [40, 50, 60, 70],
           lambda t: f"Time Dilation {t:g}%", lambda t: f"Spend {t:g}% of a day in session.",
           ["40% of your day, voluntarily. The state calls it exploitation; you call it Tuesday.",
            "Half the day in flow. The other half is loading screens.",
            "60%. Sleep is beta software and you're on the nightly build.",
            "70%. You've outgrown the human default settings. Upgrade pending."], unit="%"),
    Family("sprint3", "72-hour sprint", lambda c: _rolling(c, 3), [h * H for h in range(24, 41, 2)],
           lambda t: f"72-Hour Sprint {t / H:g} h", lambda t: f"Focus {t / H:g} h over 3 consecutive days.",
           ["{n} hours in three days. Hackathons are for amateurs.",
            "{n} hours in 72. Crunch time is a lifestyle, not an emergency.",
            "{n} hours. Three days, one mission, zero meetings."], unit="h", scale=H),
    Family("week", "Hardcore week", _week_focus, [h * H for h in _tiers(35, 99, 2, extra=(100,))],
           lambda t: f"Hardcore Week {t / H:g} h", lambda t: f"Focus {t / H:g} h in one week (Mon–Sun).",
           ["{n} hours this week. The 35-hour week was a European fiction anyway.",
            "{n} hours. Someone told you 40 was full-time. Cute.",
            "{n} hours. Elon said 80 to 100. You heard 'minimum'.",
            "{n} hours in a week. Labor law is a suggestion; physics is the only limit."],
           unit="h", scale=H),

    # ---- regularity
    Family("streak", "Uptime", _streak_sessions(1), _tiers(5, 49, 2, extra=(50,)),
           lambda t: f"Uptime {t:g} Days", lambda t: f"Hold a session {t:g} days in a row.",
           ["{n} days of uptime. Sleep is a legacy dependency.",
            "{n} days straight. Consistency is the one superpower nobody can tax.",
            "{n} days. Entropy filed a complaint. Denied.",
            "{n} days. The fire stays lit. Prometheus approves of unauthorized flames.",
            "{n} days. Weekends were a government construct anyway."], unit="days"),
    Family("streak2", "Double shift", _streak_sessions(2), [5, 10, 20, 30, 50],
           lambda t: f"Double Shift ×{t:g}", lambda t: f"At least 2 sessions a day, {t:g} days in a row.",
           ["Two sessions a day, {n} days. Redundancy, like a good rocket.",
            "{n} days of double shifts. The minimum viable ambition."], unit="days"),
    Family("streak3", "Triple stack", _streak_sessions(3), [5, 10, 20, 30, 50],
           lambda t: f"Triple Stack ×{t:g}", lambda t: f"At least 3 sessions a day, {t:g} days in a row.",
           ["Three a day for {n} days. You're not working, you're iterating.",
            "{n} days of triple stacks. Moore's law, but for you."], unit="days"),
    Family("deep3", "Deep hours I", _streak_hours(3), [5, 10, 20, 30, 50],
           lambda t: f"Deep Hours 3 h ×{t:g}", lambda t: f"3 h of focus a day, {t:g} days in a row.",
           ["3 hours a day, {n} days. That's more deep work than most ministries do in a year."], unit="days"),
    Family("deep4", "Deep hours II", _streak_hours(4), [5, 10, 20, 30, 50],
           lambda t: f"Deep Hours 4 h ×{t:g}", lambda t: f"4 h of focus a day, {t:g} days in a row.",
           ["4 hours a day for {n} days. Founder mode: engaged."], unit="days"),
    Family("deep5", "Deep hours III", _streak_hours(5), [5, 10, 20, 30, 50],
           lambda t: f"Deep Hours 5 h ×{t:g}", lambda t: f"5 h of focus a day, {t:g} days in a row.",
           ["5 hours a day, {n} days. Your competitors are in a standup about synergy."], unit="days"),
    Family("goal", "Quota crusher", _goal_streak, [3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 365],
           lambda t: f"Quota Crusher ×{t:g}", lambda t: f"Hit your daily hours goal {t:g} days in a row.",
           ["Goal hit {n} days running. Targets are floors, not ceilings.",
            "{n} days on target. Quotas are a planned-economy thing; you just overdeliver.",
            "{n} days. Your goal is starting to feel underpriced.",
            "{n} days straight. Raise the bar; it's clearly too low."], unit="days"),
    Family("goalday", "Daily quota", _goal_hits("day"), [1, 5, 10, 25, 50, 100, 200, 365, 500, 1000],
           lambda t: f"Daily Quota {t:g}", lambda t: f"Reach your daily hours goal on {t:g} days.",
           ["Goal reached. The plan was the minimum.",
            "{n} days at quota. Five-year plans failed; your daily ones don't.",
            "{n} days on target. Consistency is a deflationary asset."], unit="days"),
    Family("goalweek", "Weekly quota", _goal_hits("week"), [1, 2, 4, 8, 13, 26, 52, 104, 156, 260],
           lambda t: f"Weekly Quota {t:g}", lambda t: f"Reach your weekly hours goal in {t:g} weeks.",
           ["Weekly goal: done. The weekend is now optional.",
            "{n} weeks at quota. A quarter, a year, a decade: same energy.",
            "{n} weeks. Your OKRs have OKRs."]),
    Family("goalmonth", "Monthly quota", _goal_hits("month"), [1, 2, 3, 6, 12, 24, 36, 60, 120],
           lambda t: f"Monthly Quota {t:g}", lambda t: f"Reach your monthly hours goal in {t:g} months.",
           ["A month on target. Central banks miss theirs; you don't.",
            "{n} months at quota. Long-term thinking is the real alpha.",
            "{n} months. Your goal should start paying you rent."]),
    Family("personalbest", "Personal best", _personal_bests, [1, 3, 5, 10, 15, 20, 25, 30, 40, 50],
           lambda t: f"Personal Best ×{t:g}", lambda t: f"Beat your best week in hours, {t:g} times.",
           ["New record week. Your past self is now your competitor.",
            "{n} records broken. Up and to the right, the only acceptable chart.",
            "{n} personal bests. Stagnation is a choice you keep declining."]),
    Family("dayxp", "XP rush", lambda c: max(c.day_xp.values(), default=None), [50, 100, 150, 200, 250, 300, 400, 500],
           lambda t: f"XP Rush {t:g}", lambda t: f"Earn {t:g} XP in one day (achievements aside).",
           ["{n} XP in a day. Hyperinflation, but the good kind.",
            "{n} XP today. Your level bar needs a bigger monitor.",
            "{n} in one day. The leaderboard is just you, competing with you."]),
    Family("clockwork", "Clockwork", _clockwork, [5, 7, 10, 14, 21, 30, 45, 60, 90],
           lambda t: f"Clockwork ×{t:g}", lambda t: f"Start your day within 15 min of the day before, {t:g} days in a row.",
           ["Same time, {n} days. Predictable like a launch window.",
            "{n} days on schedule. Atomic clocks are taking notes.",
            "{n} days of clockwork. Discipline is freedom with a cron job."], unit="days"),
    Family("earlystreak", "Dawn patrol", _early_streak, [5, 7, 10, 14, 21, 30, 45, 60, 90, 120],
           lambda t: f"Dawn Patrol ×{t:g}", lambda t: f"A session before 8:00, {t:g} days in a row.",
           ["{n} early mornings. The rest of the world is still hitting snooze.",
            "{n} days before 8. You front-run the day.",
            "{n} dawns. Sunrise is your daily standup."], unit="days"),
    Family("uninterrupted", "Zero interruptions", _uninterrupted, [1, 5, 10, 25, 50, 100, 200, 300],
           lambda t: f"Zero Interruptions {t:g}", lambda t: f"{t:g} sessions of 2 h+ without any automatic pause.",
           ["Two hours, no idle, no lock, no AFK. Pure throughput.",
            "{n} unbroken sessions. Your focus has no attack surface.",
            "{n} times uninterrupted. Notifications fear you."]),
    Family("comeback", "Comebacks", _longest_gap_comeback, [7, 14, 30, 60, 90, 180, 365],
           lambda t: {7: "Return of the King", 14: "Sabbatical Over", 30: "The Prodigal Founder",
                      60: "Second Act", 90: "Back from Exile", 180: "Resurrection",
                      365: "Cold Boot"}.get(int(t), f"Comeback {t:g}"),
           lambda t: f"Start a session after {t:g} days without one.",
           ["You're back. The market missed you. Briefly.",
            "Two weeks off, back on. Vacations are just extended context switches.",
            "A month away. The prodigal founder returns; the fatted calf is a backlog.",
            "Two months out. Every great company has a second act.",
            "Three months of exile, over. Napoleon came back too. Ship faster than he did.",
            "Half a year. You died, metaphorically, and rebooted. Transhumanism works.",
            "A full year off, then back. Cryosleep complete. Welcome to the future."], unit="days"),

    # ---- tasks
    Family("tasksday", "Throughput", lambda c: _tasks_per(c, lambda d: d), [5, 10, 15, 20, 25, 30],
           lambda t: f"Throughput {t:g}/day", lambda t: f"Finish {t:g} tasks in one day.",
           ["{n} tasks in a day. Bureaucracies measure that per fiscal year.",
            "{n} in a day. Move fast and finish things.",
            "{n} tasks today. Your to-do list is filing for bankruptcy."]),
    Family("tasksweek", "Weekly burn", lambda c: _tasks_per(c, lambda d: T.week_key(d)),
           list(range(30, 201, 10)),
           lambda t: f"Weekly Burn {t:g}", lambda t: f"Finish {t:g} tasks in one week (Mon–Sun).",
           ["{n} tasks this week. Velocity is a moral virtue.",
            "{n} in a week. The backlog fears you.",
            "{n} tasks. You're not a worker, you're a deflationary force."]),
    Family("archaeologist", "Archaeologist",
           lambda c: max(((t["done"] - t["created"]) / (DAY * 1000) for t in c.tasks_done), default=None),
           [7, 30, 100],
           lambda t: f"Archaeologist {t:g} Days", lambda t: f"Finish a task that waited {t:g} days.",
           ["Seven days old and finally done. Delayed, not denied.",
            "A month-old task, executed. Bureaucracy could never.",
            "100 days. That task predates your current personality."]),

    # ---- clock
    Family("morning", "Pre-market", _morning, [8, 7, 6, 5],
           lambda t: f"Pre-Market {t:g}:00", lambda t: f"Start a session before {t:g}:00.",
           ["Before 8. Markets aren't open, but you are.",
            "Before 7. The early founder eats the whole TAM.",
            "Before 6. Even the sun is still in standup.",
            "Before 5. You are the alarm clock now."], compare="lt"),
    Family("night", "After hours", _night, [19, 20, 21, 22, 23, 24, 25, 26, 27, 28],
           lambda t: f"After Hours {_hours_label(t)}", lambda t: f"Still in session after {_hours_label(t)}.",
           ["After 19:00. Office hours are for employees.",
            "After 20:00. Dinner is a meeting you can skip.",
            "After 21:00. Prime time, and you're the content.",
            "After 22:00. The night shift of civilization reports for duty.",
            "After 23:00. Tomorrow's problems, solved today.",
            "Past midnight. Technically, you're ahead of schedule.",
            "1:00. The servers and you: the only ones still up.",
            "2:00. Sleep is a subscription you keep forgetting to renew.",
            "3:00. The bug isn't going anywhere, and neither are you.",
            "4:00. You've seen things. Mostly stack traces."], compare="gt"),
    Family("friday", "Friday night founder", _friday_night, [1],
           lambda t: "Friday Night Founder", lambda t: "Be in session after 19:00 on a Friday.",
           ["Friday night, in session. Everyone else is at happy hour, subsidizing your future."],
           secret=True),
    Family("weekend", "No weekends", _weekend, [1],
           lambda t: "No Weekends", lambda t: "Hold sessions on both Saturday and Sunday of a weekend.",
           ["Saturday and Sunday. The weekend was a 20th-century labor regulation anyway."], secret=True),

    # ---- challenges and presence
    Family("challenges", "Moonshot taker", lambda c: c.challenges_won or None, [10, 25, 50, 100],
           lambda t: f"Moonshot Taker {t:g}", lambda t: f"Win {t:g} extension challenges.",
           ["{n} challenges won. Risk tolerance: venture-grade.",
            "{n} extensions. You keep moving the goalposts, forward.",
            "{n} challenges. Comfort zones are for incumbents.",
            "{n}. At this point the challenge should be afraid of you."]),
    Family("triple", "Hat trick", lambda c: c.triples or None, [5, 10, 25],
           lambda t: f"Hat Trick ×{t:g}", lambda t: f"Win all 3 challenges of a session, {t:g} times.",
           ["Three for three, {n} times. Diminishing returns are a myth.",
            "{n} hat tricks. Your session lengths are now a geopolitical concern."]),
    Family("procrastinator", "Strategic ambiguity",
           lambda c: max(c.procrastinations.values(), default=None), [3],
           lambda t: "Strategic Ambiguity", lambda t: "Procrastinate the same task 3 times.",
           ["Three postponements. You're not procrastinating, you're optimizing for optionality."],
           secret=True),
    Family("ghost", "Proof of absence", lambda c: c.absences or None, [10],
           lambda t: "Proof of Absence", lambda t: "Get paused 10 times for not answering \"Still there?\".",
           ["Ten no-shows. Even your AFK has an AFK."], secret=True),
    Family("monotask", "Single thread", lambda c: c.monotask or None, [1 * H, 2 * H],
           lambda t: f"Single Thread {t / H:g} h", lambda t: f"Stay {t / H:g} h in one app during a session.",
           ["One hour, one app. Multitasking is a tax on the weak.",
            "Two hours, one thread. Your attention is now a sovereign state."], unit="h", scale=H),

    # ---- calendar
    Family("newyear", "Day one", _new_year, [1],
           lambda t: "Day One", lambda t: "Hold a session on January 1st.",
           ["New year, same mission. Resolutions are for people without roadmaps."], secret=True),
    Family("christmas", "Ghost of Christmas future", _on_dates({(12, 25)}), [1],
           lambda t: "Ghost of Christmas Future", lambda t: "Hold a session on December 25th.",
           ["A session on Christmas. Santa runs a logistics monopoly; you run a one-person moonshot."],
           secret=True),
    Family("orthodox", "Julian calendar", _on_dates({(1, 6), (1, 7)}), [1],
           lambda t: "Julian Calendar", lambda t: "Hold a session on Orthodox Christmas (January 6th or 7th).",
           ["Two Christmases, zero days off. Calendar arbitrage."], secret=True),
    Family("bookends", "Bookends", _bookends, [1, 5, 10, 25, 50],
           lambda t: f"Bookends ×{t:g}", lambda t: f"Start before 7:00 and still be in session after 22:00, the same day, {t:g} times.",
           ["Dawn to dark, {n} times. Work-life balance is a cope.",
            "{n} days bookended. The sun clocks fewer hours than you."], secret=True),
    Family("midnight", "Date line", _midnight_crossings, [1, 5, 10, 25, 50],
           lambda t: f"Date Line ×{t:g}", lambda t: f"Cross midnight in session {t:g} times.",
           ["You started yesterday and finished today. Time zones are a social construct.",
            "{n} midnights crossed mid-flow. Calendars can't contain you."], secret=True),
    Family("piday", "Pi day", _years_on(3, 14), [1, 2, 3, 5, 10],
           lambda t: f"Pi Day ×{t:g}", lambda t: f"Hold a session on March 14th, {t:g} different years.",
           ["3.14159… and you're still not rounding down your effort.",
            "{n} Pi Days. Irrational dedication."], secret=True),
    Family("apollo", "Apollo", _years_on(7, 20), [1, 2, 3, 5, 10],
           lambda t: f"Apollo ×{t:g}", lambda t: f"Hold a session on July 20th, {t:g} different years.",
           ["July 20th. One small session for you, one giant leap for your backlog.",
            "{n} Apollo days. We went to the Moon on slide rules; no excuses."], secret=True),
    Family("sputnik", "Sputnik", _years_on(10, 4), [1, 2, 3, 5, 10],
           lambda t: f"Sputnik ×{t:g}", lambda t: f"Hold a session on October 4th, {t:g} different years.",
           ["October 4th. The space race started today; so did your session.",
            "{n} Sputnik days. Beep. Beep. Still shipping."], secret=True),
    Family("leapday", "Leap day", _years_on(2, 29), [1, 2, 3, 5, 10],
           lambda t: f"Leap Day ×{t:g}", lambda t: f"Hold a session on February 29th, {t:g} different leap years.",
           ["A day that barely exists, and you used it. Maximum calendar efficiency.",
            "{n} leap days. You've found the bonus level of time."], secret=True),
    Family("longestday", "Longest day", _years_on(6, 21), [1, 2, 3, 5, 10],
           lambda t: f"Longest Day ×{t:g}", lambda t: f"Hold a session on June 21st, {t:g} different years.",
           ["Longest day of the year. More daylight, more output.",
            "{n} solstices of maximum sun, maximum ship."], secret=True),
    Family("longestnight", "Longest night", _years_on(12, 21), [1, 2, 3, 5, 10],
           lambda t: f"Longest Night ×{t:g}", lambda t: f"Hold a session on December 21st, {t:g} different years.",
           ["Longest night of the year, and the night SpaceX first landed an orbital booster (2015). Prometheus brought fire for exactly this.",
            "{n} winter solstices. The darkness is just more screen contrast."], secret=True),
    Family("y2k38", "Y2K38 warm-up", _on_exact(2033, 5, 18), [1],
           lambda t: "Y2K38 Warm-Up", lambda t: "Hold a session on May 18th, 2033, when Unix time passes 2 billion seconds.",
           ["Two billion seconds since 1970. You were there, shipping. Veteran status: unlocked."],
           secret=True),
    Family("fullmoon", "Lunar shift", _full_moon, [1],
           lambda t: "Lunar Shift", lambda t: "Hold a session under a full moon.",
           ["Full moon session. Next one from Mars."]),
    Family("anniversary", "Year one", _anniversary, [1],
           lambda t: "Year One", lambda t: "Still lighting fires 365 days after your first session.",
           ["One year of stolen fire. Zeus is suing; a billionaire is funding your defense."]),

    # ---- more tasks
    Family("sameday", "Same-day delivery", _same_day_tasks, [5, 10, 25, 50, 100, 200],
           lambda t: f"Same-Day Delivery {t:g}", lambda t: f"Finish {t:g} tasks the day you added them.",
           ["{n} tasks shipped same day. Amazon Prime wishes.",
            "{n} same-day finishes. Backlogs are where ideas go to get regulated.",
            "{n}. Your to-do list has a half-life of hours."]),
    Family("inboxzero", "Inbox zero", lambda c: c.inbox_zero or None, [1, 5, 20, 40, 80, 160],
           lambda t: f"Inbox Zero ×{t:g}", lambda t: f"Empty your to-do list by finishing the last task, {t:g} times.",
           ["Nothing left to do. Go invent something.",
            "{n} empty lists. Scarcity of tasks: the only scarcity you enjoy.",
            "{n} times at zero. The backlog is a myth you keep debunking."]),
    Family("redemption", "Redemption arc", _redemptions, [1, 5, 20, 40, 80, 160],
           lambda t: f"Redemption Arc ×{t:g}", lambda t: f"Finish {t:g} tasks you had procrastinated.",
           ["Procrastinated, then crushed. Optionality, exercised.",
            "{n} comebacks. Every delay was just a strategic pivot.",
            "{n} redemptions. Your past self owes you equity."]),

    # ---- more regularity
    Family("activedays", "Days in orbit", lambda c: len(c.day_sessions) or None, [30, 100, 365, 1000, 2000, 3000],
           lambda t: f"Days in Orbit {t:g}", lambda t: f"Hold a session on {t:g} different days.",
           ["{n} days in orbit. Gravity is optional.",
            "{n} active days. You don't show up; you persist.",
            "{n} days. Lindy effect: the longer you last, the longer you'll last."], unit="days"),
    Family("fullmonth", "Full month", lambda c: max(_months(c).values(), default=None), [20, 25, 30],
           lambda t: f"Full Month {t:g}", lambda t: f"{t:g} active days in the same month.",
           ["{n} days this month. Holidays are a rounding error.",
            "{n} days. You've annexed the calendar."], unit="days"),
    Family("dailymax", "Session spree", lambda c: max(c.day_sessions.values(), default=None), [5, 8, 12],
           lambda t: f"Session Spree {t:g}", lambda t: f"Hold {t:g} sessions in one day.",
           ["{n} sessions in a day. Context switches are cheap when you own the context.",
            "{n} in one day. Ship, reset, ship again."]),
    Family("goodmonths", "Monthly cadence",
           lambda c: sum(1 for k in _months(c).values() if k >= 20) or None, [1, 2, 3, 4, 5, 10, 25, 50, 100, 200],
           lambda t: f"Monthly Cadence {t:g}", lambda t: f"{t:g} months with at least 20 active days.",
           ["{n} strong months. Quarterly reports are for people who need permission.",
            "{n} months at 20+ days. Consistency, compounding, conquest.",
            "{n} months. Your work ethic has a longer track record than most startups."]),

    # ---- focus quality and reflexes
    Family("calm", "Deep water", _calm_sessions, [1, 5, 10, 25, 50],
           lambda t: f"Deep Water {t:g}", lambda t: f"{t:g} sessions of 1 h+ with fewer than 5 app switches an hour.",
           ["One hour, barely a switch. Attention is the new oil and you're OPEC.",
            "{n} calm sessions. The attention economy wants a refund."]),
    Family("reflexes", "Quick draw", lambda c: c.reflexes or None, [1, 5, 10, 25, 50, 100, 200, 300, 400, 500],
           lambda t: f"Quick Draw {t:g}", lambda t: f"Answer \"Still there?\" in under 10 seconds, {t:g} times.",
           ["Under ten seconds. Still here, still shipping.",
            "{n} quick answers. Your latency beats most governments' by a decade.",
            "{n} times in under 10 s. Neuralink, call this person."]),
    Family("fumes", "Running on fumes",
           lambda c: sum(1 for s in c.closed if s["battery"] and s["battery_pct"] is not None and s["battery_pct"] < 10) or None,
           [1, 5, 10, 25, 50, 100, 200, 300, 400, 500],
           lambda t: f"Running on Fumes {t:g}", lambda t: f"End {t:g} sessions with the battery under 10 %.",
           ["Under 10 % and still shipping. Energy scarcity is a skill issue.",
            "{n} sessions on fumes. Your charger is a crutch.",
            "{n} near-dead finishes. Living dangerously, efficiently."]),

    # ---- projects, intention, volume
    Family("monomaniac", "Monomaniac", _monomaniac, [h * H for h in (10, 25, 50, 100, 250, 500, 1000)],
           lambda t: f"Monomaniac {t / H:g} h", lambda t: f"Spend {t / H:g} h of focus on the same task.",
           ["{n} hours on one thing. Focus is saying no to a thousand good ideas.",
            "{n} hours, one project. Obsession is underrated by people without it.",
            "{n} hours on a single mission. Founders call it conviction; HR calls it a concern."],
           unit="h", scale=H),
    Family("intentional", "Intentional", lambda c: sum(1 for s in c.closed if s["task"]) or None,
           [10 * 2 ** k for k in range(10)],
           lambda t: f"Intentional {t:g}", lambda t: f"Finish {t:g} sessions started with a task name.",
           ["{n} named sessions. Intent is the cheapest productivity hack.",
            "{n} sessions with a mission statement. Shorter than most corporate ones."]),
    Family("backlogcleaner", "Backlog cleaner",
           lambda c: sum(1 for t in c.tasks_done if t["done"] - t["created"] >= 7 * DAY * 1000) or None,
           [5, 10, 25, 50, 100, 200],
           lambda t: f"Backlog Cleaner {t:g}", lambda t: f"Finish {t:g} tasks that waited a week or more.",
           ["{n} old tasks cleared. Technical debt, repaid without a bailout.",
            "{n} ancient tasks done. The archive is shrinking."]),
    Family("speedrun", "Speedrun",
           lambda c: sum(1 for t in c.tasks_done if t["done"] - t["created"] < H) or None,
           [5, 10, 25, 50, 100, 200, 500],
           lambda t: f"Speedrun {t:g}", lambda t: f"Finish {t:g} tasks within an hour of adding them.",
           ["{n} tasks done within the hour. Any% category, world record pace.",
            "{n} speedruns. Your to-do list never gets a chance to age."]),
    Family("bestmonth", "Best month", _month_hours, [h * H for h in (50, 100, 150, 200, 250, 300, 350, 400)],
           lambda t: f"Best Month {t / H:g} h", lambda t: f"Focus {t / H:g} h in one calendar month.",
           ["{n} hours in a month. That's a quarter's work at a ministry.",
            "{n} hours this month. The calendar is a resource, and you extracted it."],
           unit="h", scale=H),
    Family("annual", "Annual report", _year_hours, [h * H for h in range(500, 4001, 500)],
           lambda t: f"Annual Report {t / H:g} h", lambda t: f"Focus {t / H:g} h in one calendar year.",
           ["{n} hours this year. Shareholders, read it and weep.",
            "{n} hours in a year. Ten thousand hours is a milestone, not a ceiling."],
           unit="h", scale=H),
    Family("perfectweek", "Perfect week", _perfect_weeks, [1, 2, 4, 8, 13, 26, 52],
           lambda t: f"Perfect Week {t:g}", lambda t: f"Hold a session every day of a week (Mon–Sun), {t:g} times.",
           ["Seven days, seven sessions. God rested on the seventh; you shipped.",
            "{n} perfect weeks. The weekend is an outdated protocol."]),
    Family("veteran", "Veteran", lambda c: len({s["date"][:4] for s in c.sessions}) or None, [1, 2, 3, 5, 10],
           lambda t: f"Veteran {t:g}", lambda t: f"Hold sessions in {t:g} different years.",
           ["A year on the board. Lindy is on your side.",
            "{n} years of fire. Most startups don't survive that long."]),
    Family("purity", "Focus purity", _focus_purity, [1, 5, 10, 25, 50, 100, 200, 365],
           lambda t: f"Focus Purity {t:g}", lambda t: f"{t:g} days with 90 %+ of tracked time in session.",
           ["90% in session. Your idle time is a rounding error.",
            "{n} pure days. You don't browse; you execute."], unit="days"),
    Family("lockedin", "Locked in", _locked_in, [1, 5, 10, 25, 50, 100, 300],
           lambda t: f"Locked In {t:g}", lambda t: f"{t:g} sessions of 1 h+ with 90 % in a single app.",
           ["One app, one hour, one mind. Locked in.",
            "{n} locked-in sessions. Attention is a weapon and you're armed."]),
    Family("yesman", "Yes man", _yes_man, [3, 5, 10, 25, 50],
           lambda t: f"Yes Man {t:g}", lambda t: f"Accept {t:g} challenges in a row without declining one.",
           ["{n} yeses in a row. Risk-on.",
            "{n} challenges accepted straight. You never met an extension you didn't like."]),
    Family("aroundtheclock", "Around the clock",
           lambda c: len({_local(s["start"]).hour for s in c.sessions}) or None, [12, 18, 24],
           lambda t: f"Around the Clock {t:g}", lambda t: f"Start sessions at {t:g} different hours of the day.",
           ["{n} different start hours. Circadian rhythm is a suggestion.",
            "All 24 hours covered. You are the always-on economy."]),
    Family("meteorologist", "Meteorologist",
           lambda c: 1 if ({"rain", "snow", "storm", "clear"} <= {s["weather"] for s in c.closed}
                           and any(s["temp"] is not None and s["temp"] > 30 for s in c.closed)
                           and any(s["temp"] is not None and s["temp"] < 0 for s in c.closed)) else None,
           [1], lambda t: "Meteorologist", lambda t: "Finish sessions in rain, snow, storm, sun, heat and frost.",
           ["Every weather, same output. Climate is not a productivity variable."], secret=True),

    # ---- the world outside
    Family("battery", "Off-grid", lambda c: sum(1 for s in c.closed if s["battery"]) or None,
           [10 * 2 ** k for k in range(10)],
           lambda t: f"Off-Grid {t:g}", lambda t: f"Run {t:g} sessions on battery.",
           ["{n} sessions unplugged. Energy independence starts in your laptop.",
            "{n} off the grid. The utility company is nervous.",
            "{n} on battery. You're one solar panel away from secession.",
            "{n} sessions without the grid. Musk would call that sustainable abundance."]),
    Family("rain", "Rain check denied", _weather("rain"), [1, 5, 10, 20, 30],
           lambda t: f"Rain Check Denied {t:g}", lambda t: f"Finish {t:g} sessions while it rains.",
           ["Rain outside, output inside. Weather is not a valid excuse."]),
    Family("snow", "Cold start", _weather("snow"), [1, 5, 10, 20, 30],
           lambda t: f"Cold Start {t:g}", lambda t: f"Finish {t:g} sessions while it snows.",
           ["Snow day? Only for schools run by the state."]),
    Family("storm", "Thunder run", _weather("storm"), [1, 5, 10, 20, 30],
           lambda t: f"Thunder Run {t:g}", lambda t: f"Finish {t:g} sessions during a storm.",
           ["Lightning outside. Prometheus feels right at home."]),
    Family("sun", "Opportunity cost", _weather("clear"), [1, 5, 10, 20, 30],
           lambda t: f"Opportunity Cost {t:g}", lambda t: f"Finish {t:g} sessions under clear skies.",
           ["Perfect weather, spent building. The beach will still be there after the exit."]),
    Family("heat", "Overclocked", lambda c: sum(1 for s in c.closed if s["temp"] is not None and s["temp"] > 30) or None,
           [1, 5, 10, 20, 30],
           lambda t: f"Overclocked {t:g}", lambda t: f"Finish {t:g} sessions above 30 °C.",
           ["Above 30 °C and still shipping. Thermal throttling is for CPUs."]),
    # ---- quests
    Family("questfirst", "Mission statement", lambda c: _count(c.quests), [1],
           lambda t: "Mission Statement", lambda t: "Create your first quest.",
           ["Every empire starts as a to-do with delusions of grandeur."]),
    Family("closer", "Closer", lambda c: _count(_quests_done(c)), [1, 3, 5, 10, 25, 50, 100],
           lambda t: f"Closer ×{t:g}", lambda t: f"Finish {t:g} short or long quests.",
           ["Ideas are cheap. Shipping is the whole game.",
            "{n} quests closed. Founders talk; closers ship.",
            "{n} done. Your roadmap is now a changelog."]),
    Family("longgame", "Long game", lambda c: _count(_quests_done(c, "long")), [1, 3, 5, 10, 20],
           lambda t: f"Long Game ×{t:g}", lambda t: f"Finish {t:g} long quests.",
           ["Thiel would call it a definite future.",
            "{n} long quests. You plan in decades and ship in weeks."]),
    Family("rituals", "Rituals", lambda c: sum(len(q["done_days"]) for q in c.quests) or None,
           [10, 30, 100, 250, 500, 1000],
           lambda t: f"Rituals ×{t:g}", lambda t: f"Complete daily quests {t:g} times in all.",
           ["Habits are just compounding with better marketing.",
            "{n} rituals. Discipline is the API, results are the response."]),
    Family("unbroken", "Unbroken", _daily_run, [7, 14, 30, 60, 100, 365],
           lambda t: f"Unbroken {t:g} days", lambda t: f"Complete the same daily quest {t:g} days in a row.",
           ["Consistency is the only moat that can't be forked.",
            "{n} days unbroken. Your streak has better uptime than most clouds."], unit="days"),
    Family("fullspectrum", "Full spectrum", lambda c: c.quests_full or None, [1],
           lambda t: "Full Spectrum", lambda t: "Have ten quests open at once, all ten colors.",
           ["A portfolio, not a bet."]),
    Family("redthread", "Red thread",
           lambda c: _count([q for q in _quests_done(c) if q["color"].lower() == "#f22424"]), [1, 5, 10, 25],
           lambda t: f"Red Thread ×{t:g}", lambda t: f"Finish {t:g} red quests.",
           ["First principles, first color.",
            "{n} red quests down. Seeing red is a growth strategy."]),
    Family("cleansweep", "Clean sweep", lambda c: c.quest_sweeps or None, [1],
           lambda t: "Clean Sweep",
           lambda t: "Finish every open short and long quest, at least three of them, without deleting any.",
           ["Zero open loops. Pure throughput."]),
    Family("deepquest", "Deep quest", lambda c: _best(c, "seconds"), [5 * H, 10 * H, 25 * H, 50 * H, 100 * H, 250 * H],
           lambda t: f"Deep Quest {t / H:g} h", lambda t: f"Focus {t / H:g} h on a single quest.",
           ["Ten thousand hours is a rounding error at this scale.",
            "{n} h on one quest. Depth is the new scale."], unit="h", scale=H),
    Family("attrition", "War of attrition", lambda c: _best(c, "sessions"), [5, 10, 25, 50, 100],
           lambda t: f"War of Attrition ×{t:g}", lambda t: f"Hold {t:g} sessions on a single quest.",
           ["Persistence is underrated because it's unglamorous.",
            "{n} sessions on one quest. Attrition favors the stubborn."]),
    Family("questgrinder", "Quest grinder", lambda c: _best(c, "tasks"), [5, 10, 25, 50, 100],
           lambda t: f"Quest Grinder ×{t:g}", lambda t: f"Check {t:g} tasks while a single quest is active.",
           ["Decompose the moonshot into tickets.",
            "{n} tickets for one quest. Moonshots are just very long sprints."]),
    Family("payload", "Payload", lambda c: _best(c, "xp"), [50, 100, 250, 500, 1000],
           lambda t: f"Payload {t:g} XP", lambda t: f"Earn {t:g} XP on a single quest.",
           ["Value capture, quest edition.",
            "{n} XP from one quest. Margins a SaaS would kill for."], unit="XP"),
    Family("nightshift", "Night shift", _timed_quests(NIGHT_HOURS), [1],
           lambda t: "Night Shift",
           lambda t: "Finish a quest with more than half of its focus (1 h at least) between 22 h and 4 h.",
           ["The market never sleeps, neither does this quest."]),
    Family("dawnraid", "Dawn raid", _timed_quests(DAWN_HOURS), [1],
           lambda t: "Dawn Raid",
           lambda t: "Finish a quest with more than half of its focus (1 h at least) between 4 h and 8 h.",
           ["Shipped before the market opened. Pre-market alpha."]),
    Family("speedrunner", "Speedrunner", _speedruns, [1],
           lambda t: "Speedrunner", lambda t: "Finish a short quest in one or two days worked.",
           ["Move fast. Ship faster."]),
    Family("marathoner", "Marathoner", _marathons, [1],
           lambda t: "Marathoner", lambda t: "Finish a long quest 30 days or more after first activating it.",
           ["Patience is a strategy, not a virtue."]),
    Family("pivot", "Pivot", _pivots, [1],
           lambda t: "Pivot", lambda t: "Delete a quest you had already put more than 5 h into.",
           ["Sunk cost is a tax on the weak."], secret=True),

    # ---- leagues
    Family("promoted", "Promoted", _promotions, [1, 3, 5, 10, 25, 50],
           lambda t: f"Promoted ×{t:g}", lambda t: f"Get promoted to a higher league {t:g} times.",
           ["Up a league. Meritocracy works when you're the merit.",
            "{n} promotions. The org chart can't keep up with you.",
            "{n} times promoted. Your past self is filing a complaint with HR."]),
    Family("leagueclimb", "League climber", _league_peak, list(range(1, 10)),
           lambda t: f"{['Bronze', 'Silver', 'Gold', 'Sapphire', 'Ruby', 'Emerald', 'Amethyst', 'Pearl', 'Obsidian', 'Diamond'][int(t)]} League",
           lambda t: f"Reach the {['Bronze', 'Silver', 'Gold', 'Sapphire', 'Ruby', 'Emerald', 'Amethyst', 'Pearl', 'Obsidian', 'Diamond'][int(t)]} league.",
           ["New league, new altitude. Gravity is a suggestion.",
            "Another league up. Escape velocity is just compounding with a rocket.",
            "Higher still. The air is thin and the competition thinner."]),
    Family("diamondhands", "Diamond hands", _diamond_weeks, [1, 4, 12, 26, 52],
           lambda t: f"Diamond Hands {t:g}", lambda t: f"Play {t:g} weeks in the Diamond league.",
           ["Diamond league. Pressure makes diamonds; you make pressure.",
            "{n} weeks in Diamond. Holding the top like a long-term position."], unit="weeks"),
    Family("bounceback", "Bounce back", _bounce_backs, [1, 3, 5, 10],
           lambda t: f"Bounce Back ×{t:g}", lambda t: f"Get promoted right after a relegation, {t:g} times.",
           ["Relegated, then promoted. Drawdowns are buying opportunities.",
            "{n} bounces. Antifragile, by the book."]),
    Family("promostreak", "Promotion streak", _promotion_run, [2, 3, 5, 9],
           lambda t: f"Promotion Streak {t:g}", lambda t: f"Get promoted {t:g} league rounds in a row (two weeks each).",
           ["{n} promotions in a row. Exponential, not linear.",
            "{n} straight. Hockey stick, achieved."], unit="rounds"),

    # ---- seasons
    Family("seasonpass", "Season pass", lambda c: _seasons_with(c, 1), [1, 2, 4, 8, 12],
           lambda t: f"Season Pass ×{t:g}", lambda t: f"Reach the season goal in {t:g} seasons.",
           ["Season goal, cleared. Quarterly guidance: exceeded.",
            "{n} seasons on target. Wall Street would love your consistency."]),
    Family("hardmode", "Hard mode", lambda c: _seasons_with(c, 2), [1, 2, 4, 8],
           lambda t: f"Hard Mode ×{t:g}", lambda t: f"Reach the hard season goal in {t:g} seasons.",
           ["Two bars. The hard goal is the only goal.",
            "{n} hard seasons. Difficulty setting: founder."]),
    Family("straighta", "Straight A", lambda c: _count([s for s in _graded(c) if s["grade"] in ("A", "S")]), [1, 2, 4, 8],
           lambda t: f"Straight A ×{t:g}", lambda t: f"Finish {t:g} seasons with an A or better.",
           ["An A. Grade inflation, except you earned it.",
            "{n} A seasons. The curve is you."]),
    Family("stier", "S-tier", lambda c: _count([s for s in _graded(c) if s["grade"] == "S"]), [1, 2, 4, 8],
           lambda t: f"S-Tier ×{t:g}", lambda t: f"Finish {t:g} seasons with an S: 20 % beyond the hard goal.",
           ["An S. The grading scale needed a new letter for you.",
            "{n} S seasons. Off the charts is now your baseline."]),
    Family("honorroll", "Honor roll", _honor_run, [2, 4, 8],
           lambda t: f"Honor Roll {t:g}", lambda t: f"Finish {t:g} seasons in a row with a B or better.",
           ["{n} good seasons in a row. Consistency compounds.",
            "{n} straight. Your track record is now a moat."], unit="seasons"),
    Family("phoenix", "Phoenix", _phoenix, [1],
           lambda t: "Phoenix", lambda t: "Follow an F season with an A season.",
           ["From F to A. Every great company has a near-death chapter."], secret=True),

    # ---- leaderboards
    Family("dayrecord", "Record day", _day_records, [1, 5, 10, 25, 50],
           lambda t: f"Record Day ×{t:g}", lambda t: f"Beat your best day ever in XP, {t:g} times.",
           ["New best day. The leaderboard has one name and it's yours.",
            "{n} record days. Your ceiling keeps becoming your floor."]),
    Family("sessionrecord", "Record session", _session_records, [1, 5, 10, 25],
           lambda t: f"Record Session ×{t:g}", lambda t: f"Beat your longest session ever, {t:g} times.",
           ["Longest session ever. Endurance is a competitive advantage.",
            "{n} session records. Your attention span is an outlier."]),
    Family("podium", "Podium", _day_podiums, [5, 10, 25, 50, 100],
           lambda t: f"Podium ×{t:g}", lambda t: f"Make your top 3 days ever, {t:g} times.",
           ["{n} podium days. Bronze is still a medal; you aim higher.",
            "{n} top-3 days. Your best is a moving target."]),

    # ---- exploring the tool (rarity set by hand)
    Family("presskit", "Press kit", _event("share_card"), [1, 5, 20],
           lambda t: f"Press Kit ×{t:g}", lambda t: f"Generate your ID card {t:g} times.",
           ["Your service record, minted. Personal brand: shipped.",
            "{n} cards. Your PR team is just you, and it's enough."],
           unit="M", scale=1e6, rarities=["common", "rare", "epic"]),
    Family("revisionist", "Revisionist history", _event("board_remove_done"), [1],
           lambda t: "Revisionist History", lambda t: "Take a finished quest off the leaderboard.",
           ["History is written by the ones who ship. And edited by them too."], rarities="rare"),
    Family("callsign", "Call sign", _event("setting:handle"), [1],
           lambda t: "Call Sign", lambda t: "Set your @handle.",
           ["Every founder needs a handle. Now the internet knows who to blame."], rarities="normal"),
    Family("timezone", "Own your clock", _event("setting:daystart"), [1],
           lambda t: "Own Your Clock", lambda t: "Change the hour your day starts.",
           ["Midnight is a convention. You set your own."], rarities="common"),
    Family("pacemaker", "Pacemaker", _event("setting:presence"), [1],
           lambda t: "Pacemaker", lambda t: "Change how often \"Still there?\" asks.",
           ["You tuned the heartbeat monitor. Trust, but verify."], rarities="common"),
    Family("rebrand", "Rebrand", _event("setting:aliases"), [1],
           lambda t: "Rebrand", lambda t: "Rename or merge an app.",
           ["A rebrand. Cheaper than a pivot, almost as satisfying."], rarities="normal"),
    Family("redacted", "Redacted", _event("setting:words"), [1],
           lambda t: "Redacted", lambda t: "Add a forbidden word for window titles.",
           ["Some things the logs should never see. Operational security."], rarities="rare"),
    Family("invisible", "Invisible ink", _event("setting:apps"), [1],
           lambda t: "Invisible Ink", lambda t: "Hide an app from the records.",
           ["Off the books. Every empire has a back office."], rarities="common"),
    Family("goalsetter", "Goal setter", _event("setting:goal"), [1],
           lambda t: "Goal Setter", lambda t: "Set an hours goal.",
           ["A number on the wall. Now the work has a scoreboard."], rarities="normal"),
    Family("formatwar", "Format war", lambda c: sum(v for k, v in c.events.items() if k == "setting:export:apng") or None, [1],
           lambda t: "Format War", lambda t: "Switch the share export to animated PNG.",
           ["APNG over GIF. Taste is a competitive advantage."], rarities="rare"),
    Family("poweruser", "Power user", _power_user, [1],
           lambda t: "Power User", lambda t: "Change every setting at least once.",
           ["Every knob turned. You don't use tools, you configure them."], rarities="epic"),
    Family("grandtour", "Grand tour", _grand_tour, [1],
           lambda t: "Grand Tour", lambda t: "Open every tab of the panel.",
           ["Full reconnaissance. Now you know the terrain."], rarities="common"),
    Family("historian", "Historian", _event("bio"), [1, 10, 50],
           lambda t: f"Historian ×{t:g}", lambda t: f"Read {t:g} rival bios in the leagues.",
           ["Know your rivals. They built the world you're optimizing.",
            "{n} bios read. Standing on the shoulders of giants, and taking notes."],
           rarities=["normal", "rare", "epic"]),

    # ---- coding agents: tokens burned (rarity set by hand)
    Family("burner", "Token burner", lambda c: max(c.day_tokens.values(), default=0) or None,
           [10e6, 50e6, 100e6, 250e6, 500e6, 1e9],
           lambda t: f"Burner {agents.short(t)}", lambda t: f"Burn {agents.short(t)} agent tokens in a day.",
           ["The GPUs felt that one. Somewhere a datacenter fan spun up for you.",
            "{n}. Your agents worked harder than most teams."],
           unit="M", scale=1e6, rarities=["normal", "common", "rare", "epic", "epic", "legendary"]),
    Family("lifetime", "Lifetime burn", lambda c: c.agent.get("lifetime") or None, [100e6, 1e9, 5e9, 10e9, 50e9],
           lambda t: f"Lifetime {agents.short(t)}", lambda t: f"Burn {agents.short(t)} agent tokens in all.",
           ["A hundred million tokens. Compute is the new payroll.",
            "{n} tokens. You don't write code anymore, you allocate intelligence."],
           unit="M", scale=1e6, rarities=["common", "rare", "epic", "legendary", "legendary"]),
    Family("orchestrator", "Orchestrator", lambda c: c.agent.get("maxParallel") or None, [3, 5, 10],
           lambda t: f"Orchestrator ×{t:g}", lambda t: f"Have {t:g} agent conversations working in the same minute.",
           ["Three agents at once. You're not a developer, you're a conductor.",
            "{n} in parallel. Span of control: unreasonable."],
           rarities=["common", "rare", "epic"]),
    Family("polyglot", "Polyglot", lambda c: c.agent.get("maxModels") or None, [3, 4],
           lambda t: f"Polyglot ×{t:g}", lambda t: f"Use {t:g} model families in one day.",
           ["Right model, right job. Portfolio thinking.", "Every model in the stable. A true multi-model shop."],
           rarities=["rare", "epic"]),
    Family("fleet", "Remote fleet", lambda c: c.agent.get("remoteDays") or None, [1, 7, 30],
           lambda t: f"Remote Fleet ×{t:g}", lambda t: f"Burn more on other machines than here, {t:g} days.",
           ["The real work happens on the server. You just steer.", "{n} days run from afar. Distributed company."],
           rarities=["common", "rare", "epic"]),
    Family("cachewhisperer", "Cache whisperer", lambda c: c.agent.get("cacheDays") or None, [1, 10],
           lambda t: f"Cache Whisperer ×{t:g}", lambda t: f"Keep 97 % of a day's tokens (1M at least) in the cache, {t:g} days.",
           ["Unit economics: excellent. Investors love a cache hit.", "{n} lean days. Margins like a SaaS."],
           rarities=["rare", "epic"]),
    Family("nightshift", "Night shift", lambda c: c.agent.get("bestNight") or None, [10e6, 100e6],
           lambda t: f"Night Shift {agents.short(t)}", lambda t: f"Have agents burn {agents.short(t)} tokens between midnight and 6 am.",
           ["You slept. They didn't. Leverage.", "A whole night of agents. The company never sleeps."],
           rarities=["rare", "epic"]),
    Family("deeppair", "Deep pair", lambda c: c.agent.get("deepPairs") or None, [1, 10],
           lambda t: f"Deep Pair ×{t:g}", lambda t: f"Focus 2 hours while agents burn 10M tokens, {t:g} times.",
           ["Human and machine in lockstep. That's the future of work.", "{n} deep pairings. Cyborg mode."],
           rarities=["epic", "legendary"]),
    Family("agentstreak", "Agent streak", lambda c: c.agent.get("streak") or None, [7, 30, 100],
           lambda t: f"Agent Streak {t:g}", lambda t: f"Have agents at work {t:g} days in a row.",
           ["A week of agents every day. Habit formed.", "{n} days running. The machine is part of the team."],
           rarities=["common", "epic", "legendary"]),
    Family("delegator", "Delegator", lambda c: c.agent.get("bestOutside") or None, [50e6, 200e6],
           lambda t: f"Delegator {agents.short(t)}", lambda t: f"Have agents burn {agents.short(t)} tokens in a day outside your focus sessions.",
           ["Work happened without you. That's what managers call leverage.", "{n} while you were elsewhere. Pure delegation."],
           unit="M", scale=1e6, rarities=["rare", "epic"]),
    Family("bigspender", "Big spender", lambda c: c.agent.get("bestCost") or None, [50, 100, 250],
           lambda t: f"Big Spender ${t:g}", lambda t: f"Burn ${t:g} of agent compute in a day (API prices).",
           ["Burn rate: healthy. The board would ask questions.", "${n} in a day. Compute is cheaper than hires."],
           rarities=["common", "rare", "epic"]),
    Family("tokenfame", "Token hall of fame", lambda c: _token_fame(c), [1, 5, 10],
           lambda t: f"Token Hall of Fame ×{t:g}",
           lambda t: f"Put a day in your top 10 token days, {t:g} times (from your 30th day on).",
           ["A top-10 burn day. The leaderboard noticed.", "{n} record days of compute."]),

    # ---- leaderboards: new top-10 entries, from 30 days in
    Family("halloffame", "Hall of fame", _hall_of_fame, [1, 5, 10, 25, 50],
           lambda t: f"Hall of Fame ×{t:g}",
           lambda t: f"Put a day in your top 10 days, {t:g} times (from your 30th day on).",
           ["Into the top 10. The leaderboard just got harder to read without you.",
            "{n} hall-of-fame days. Your history is now mostly highlights."]),
    Family("sessionlegend", "Session legend", _session_legend, [1, 5, 10, 25],
           lambda t: f"Session Legend ×{t:g}",
           lambda t: f"Put a session in your top 10 sessions, {t:g} times (from your 30th day on).",
           ["A top-10 session. Deep work, certified.",
            "{n} legendary sessions. Focus as a moat."]),

    Family("frost", "Cryo mode", lambda c: sum(1 for s in c.closed if s["temp"] is not None and s["temp"] < 0) or None,
           [1, 5, 10, 20, 30],
           lambda t: f"Cryo Mode {t:g}", lambda t: f"Finish {t:g} sessions below 0 °C.",
           ["Below zero, still running. Practicing for cryonics."]),
]


# Difficulty weights: x2 hard, x3 extreme; everything else x1.
WEIGHTS = {
    "cumul": 3, "deep5": 3, "streak3": 3, "week": 3, "intensity": 3, "goodmonths": 3, "activedays": 3,
    "endurance": 2, "sprint3": 2, "streak": 2, "streak2": 2, "deep3": 2, "deep4": 2, "goal": 2,
    "goalday": 2, "goalweek": 2, "goalmonth": 2, "tasksday": 2, "tasksweek": 2, "triple": 2,
    "personalbest": 2, "clockwork": 2, "earlystreak": 2, "uninterrupted": 2, "calm": 2,
    "monotask": 2, "archaeologist": 2, "fullmonth": 2, "dailymax": 2, "dayxp": 2,
    "monomaniac": 2, "annual": 3, "bestmonth": 2, "perfectweek": 2, "purity": 2, "lockedin": 2,
    "veteran": 2,
    "closer": 2, "longgame": 3, "unbroken": 2, "cleansweep": 2, "deepquest": 2, "payload": 2,
    "marathoner": 3,
    "leagueclimb": 2, "diamondhands": 3, "promostreak": 2, "seasonpass": 2, "hardmode": 3,
    "honorroll": 2, "podium": 2, "stier": 3, "halloffame": 2, "sessionlegend": 2, "tokenfame": 2,
}
for _f in FAMILIES:
    _f.weight = WEIGHTS.get(_f.id, 1)


# ------------------------------------------------------------- evaluation


def evaluate(store, now: int, level_for_xp: Callable[[int], int], base_xp: int) -> list[dict]:
    """Unlock what the records now justify; returns the new unlocks.

    Level achievements grant XP that can raise the level, so this runs until
    nothing new unlocks."""
    fresh: list[dict] = []
    # Rewards follow the current rules, also for what was unlocked before.
    unlocked = store.unlocked_achievements()
    for f in FAMILIES:
        for i in range(len(f.thresholds)):
            row = unlocked.get(f.tier_id(i))
            if row is not None and row["xp"] != f.xp(i):
                store.set_achievement_xp(row["id"], f.xp(i))
    while True:
        unlocked = store.unlocked_achievements()
        level = level_for_xp(base_xp + store.achievement_xp_total())
        ctx = build_context(store, now, level)
        new = []
        for f in FAMILIES:
            value = f.measure(ctx)
            for i in range(len(f.thresholds)):
                aid = f.tier_id(i)
                if aid not in unlocked and f.passes(value, i):
                    store.unlock(aid, now, f.xp(i))
                    new.append({"id": aid, "name": f.name(f.thresholds[i]), "xp": f.xp(i),
                                "quip": f.quip(i), "secret": f.secret, "rarity": f.rarity(i)})
        for day in sorted(ctx.end_dates):
            event = geekdates.event_on(day)
            if event and f"cal:{event[0]}" not in unlocked:
                aid, name, _, quip = event
                store.unlock(f"cal:{aid}", now, geekdates.XP)
                unlocked = store.unlocked_achievements()
                new.append({"id": f"cal:{aid}", "name": name, "xp": geekdates.XP, "quip": quip, "secret": True,
                            "rarity": "common"})
        if not new:
            return fresh
        fresh.extend(new)


def _dots(text: str) -> str:
    """The shape of a text without its words: every letter becomes a dot."""
    return "".join(ch if ch.isspace() else "•" for ch in text)


def _started(value) -> bool:
    return value is not None and value != 0


def catalogue(store, now: int, level: int) -> dict:
    """Every family with its tiers, what is unlocked, and the progress to the next."""
    unlocked = store.unlocked_achievements()
    ctx = build_context(store, now, level)
    families, got, total, xp = [], 0, 0, 0
    for f in FAMILIES:
        value = f.measure(ctx)
        tiers = []
        for i, t in enumerate(f.thresholds):
            aid = f.tier_id(i)
            row = unlocked.get(aid)
            total += 1
            if row is not None:
                got += 1
                xp += row["xp"]
            tiers.append({"id": aid, "threshold": t / f.scale, "name": f.name(t), "desc": f.desc(t),
                          "xp": f.xp(i), "unlockedAt": row["unlocked_at"] if row else None,
                          "quip": f.quip(i) if row else None, "rarity": f.rarity(i)})
        revealed = not f.secret or any(t["unlockedAt"] for t in tiers)
        if not revealed:
            tiers = [{"id": None, "threshold": None, "name": "???", "desc": "Secret achievement.",
                      "xp": f.xp(0), "unlockedAt": None, "quip": None, "rarity": "epic"}]
        # Suspense: a family nobody has started shows only the shape of its
        # text; a started one shows its unlocked tiers and the next one, the
        # tiers after that stay dots until the one before is reached.
        started = any(t["unlockedAt"] for t in tiers) or _started(value)
        masked = revealed and not started
        if revealed:
            nxt = next((i for i, t in enumerate(tiers) if not t["unlockedAt"]), len(tiers))
            for i, t in enumerate(tiers):
                if masked or i > nxt:
                    t.update(name=_dots(t["name"]), desc=_dots(t["desc"]), threshold=None, hidden=True,
                             rarity=None)
        families.append({
            "id": f.id, "title": (_dots(f.title) if masked else f.title) if revealed else "???",
            "secret": f.secret, "masked": masked,
            "unit": f.unit, "compare": f.compare,
            "value": (None if value is None or not revealed or masked else round(value / f.scale, 2)),
            "tiers": tiers,
        })
    # The calendar: one collection, each date hidden until found.
    tiers, found = [], 0
    for aid, name, desc, quip in geekdates.all_entries():
        row = unlocked.get(f"cal:{aid}")
        total += 1
        if row is not None:
            found += 1
            got += 1
            xp += row["xp"]
            tiers.append({"id": f"cal:{aid}", "threshold": None, "name": name, "desc": desc,
                          "xp": row["xp"], "unlockedAt": row["unlocked_at"], "quip": quip, "rarity": "common"})
        else:
            tiers.append({"id": None, "threshold": None, "name": "???",
                          "desc": "Finish a session on the right day.", "xp": geekdates.XP,
                          "unlockedAt": None, "quip": None, "rarity": "common"})
    tiers.sort(key=lambda t: (t["unlockedAt"] is None, t["unlockedAt"] or 0))
    families.append({"id": "calendar", "title": "Calendar", "secret": False, "kind": "collection",
                     "unit": "", "compare": "ge", "value": found, "tiers": tiers})
    return {"success": True, "families": families, "unlocked": got, "total": total, "xp": xp}
