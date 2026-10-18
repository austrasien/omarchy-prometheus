"""Medals: recurring decorations, put back in play every day, week or month.

A medal is won once per period (a day, a Monday-Sunday week, a calendar
month, all along Prometheus' logical days) as soon as its condition holds,
and can be won again the next period. Each one is drawn as a military ribbon:

  - dots in the middle tell the period: 1 daily, 2 weekly, 3 monthly;
  - stripes on the edges tell the difficulty: none, left, left and right;
  - the background color tells the theme (focus, tasks, challenges, clock...).

Rewards: 5 / 20 / 60 XP for a daily / weekly / monthly medal, x1.5 with a
left stripe, x2 with both.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from . import achievements as A
from . import timeutil as T

H = 3600

# Ribbon colors, by theme.
BLUE, NAVY, GREEN, GOLD, RED = "#3b5bdb", "#1e3a8a", "#2f9e44", "#e0a800", "#c92a2a"
CRIMSON, ORANGE, PURPLE, TEAL, WHITE = "#a61e4d", "#e8590c", "#7048e8", "#0c8599", "#dee2e6"

BASE_XP = {"day": 5, "week": 20, "month": 60}
EDGE_FACTOR = {"none": 1.0, "left": 1.5, "both": 2.0}
DOTS = {"day": 1, "week": 2, "month": 3}


@dataclass
class Medal:
    id: str
    name: str
    period: str            # day, week, month
    desc: str
    quip: str
    color: str
    dot: str
    edges: str             # none, left, both
    check: Callable[["Period"], bool]

    @property
    def xp(self) -> int:
        return int(BASE_XP[self.period] * EDGE_FACTOR[self.edges])

    def ribbon(self) -> dict:
        return {"color": self.color, "dots": DOTS[self.period], "dot": self.dot, "edges": self.edges}


# ----------------------------------------------------------------- periods


def period_key(period: str, date: dt.date) -> str:
    if period == "day":
        return date.isoformat()
    if period == "week":
        y, w, _ = date.isocalendar()
        return f"{y}-W{w:02d}"
    return date.strftime("%Y-%m")


def period_days(period: str, date: dt.date) -> list[dt.date]:
    if period == "day":
        return [date]
    if period == "week":
        monday = date - dt.timedelta(days=date.weekday())
        return [monday + dt.timedelta(days=i) for i in range(7)]
    first = date.replace(day=1)
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    return [first + dt.timedelta(days=i) for i in range((nxt - first).days)]


@dataclass
class Period:
    """One day, week or month, seen through the achievements context."""
    kind: str
    days: list
    ctx: A.Context
    won_challenges: list          # (logical date, session id) of won challenges
    procrastinated: set           # logical dates of procrastinated sessions

    @property
    def dates(self) -> set[str]:
        return {d.isoformat() for d in self.days}

    def focus(self) -> float:
        return sum(self.ctx.day_focus.get(d, 0) for d in self.dates)

    def active_days(self) -> int:
        return sum(1 for d in self.dates if d in self.ctx.day_sessions)

    def sessions(self) -> list[dict]:
        return [s for s in self.ctx.sessions if s["date"] in self.dates]

    def tasks_done(self) -> int:
        return sum(1 for t in self.ctx.tasks_done if T.date_str(t["done"]) in self.dates)

    def challenges(self) -> list:
        return [c for c in self.won_challenges if c[0] in self.dates]

    def tracked(self) -> float:
        return sum(self.ctx.day_tracked.get(d, 0) for d in self.dates)


def _best_previous(ctx: A.Context, kind: str, before: dt.date) -> float:
    """Best focus of a whole week or month that ended before `before`."""
    buckets = defaultdict(float)
    for d, s in ctx.day_focus.items():
        day = dt.date.fromisoformat(d)
        if day < before:
            buckets[period_key(kind, day)] += s
    return max(buckets.values(), default=0.0)


def _streak_in(p: Period, n: int) -> bool:
    run = 0
    for d in p.days:
        run = run + 1 if d.isoformat() in p.ctx.day_sessions else 0
        if run >= n:
            return True
    return False


def _goal_day(p: Period) -> bool:
    g = p.ctx.goal
    return bool(g and g["period"] == "day" and p.focus() >= g["hours"] * H)


def _purity(p: Period) -> bool:
    tracked = p.tracked()
    return tracked >= 2 * H and p.focus() >= 0.9 * tracked


def _hat_trick(p: Period) -> bool:
    per_session = defaultdict(int)
    for _, sid in p.challenges():
        per_session[sid] += 1
    return any(n >= 3 for n in per_session.values())


def _early(p: Period) -> bool:
    for s in p.sessions():
        t = A._local(s["start"])
        if 4 <= t.hour < 8:
            return True
    return False


def _late(p: Period) -> bool:
    return any(A._night_hour(s) > 22 for s in p.sessions())


def _weekend(p: Period) -> bool:
    days = {d.weekday(): d.isoformat() for d in p.days}
    return days.get(5) in p.ctx.day_sessions and days.get(6) in p.ctx.day_sessions


def _record(kind: str, floor_hours: float):
    def check(p: Period) -> bool:
        focus = p.focus()
        return focus >= floor_hours * H and focus > _best_previous(p.ctx, kind, p.days[0])
    return check


def _no_procrastination(p: Period) -> bool:
    return len(p.sessions()) >= 5 and not (p.procrastinated & p.dates)


def _weathers(p: Period) -> bool:
    kinds = {s["weather"] for s in p.ctx.closed if s["date"] in p.dates and s["weather"]}
    return len(kinds) >= 3


MEDALS: list[Medal] = [
    # ---- daily: one dot
    Medal("dayshift", "Day Shift", "day", "2 h of focus in a day.",
          "Two hours. The bare minimum for a civilization-scale ambition.",
          BLUE, WHITE, "none", lambda p: p.focus() >= 2 * H),
    Medal("deepday", "Deep Day", "day", "4 h of focus in a day.",
          "Four hours deep. Most people never touch the bottom.",
          BLUE, GOLD, "left", lambda p: p.focus() >= 4 * H),
    Medal("ironday", "Iron Day", "day", "6 h of focus in a day.",
          "Six hours. The day surrendered.",
          NAVY, GOLD, "both", lambda p: p.focus() >= 6 * H),
    Medal("closer", "Closer", "day", "Finish 5 tasks in a day.",
          "Five closed. Always be closing.",
          GREEN, WHITE, "none", lambda p: p.tasks_done() >= 5),
    Medal("earlybird", "Early Bird", "day", "Start a session before 8:00.",
          "First mover advantage, daily.",
          ORANGE, WHITE, "none", _early),
    Medal("nightwatch", "Night Watch", "day", "Still in session after 22:00.",
          "The night is dark and full of shipping.",
          PURPLE, WHITE, "none", _late),
    Medal("challenger", "Challenger", "day", "Win an extension challenge.",
          "Took the bet, won the bet.",
          GOLD, RED, "none", lambda p: len(p.challenges()) >= 1),
    Medal("hattrickday", "Hat Trick", "day", "Win all 3 challenges of a session.",
          "Three for three. Diminishing returns denied.",
          GOLD, RED, "both", _hat_trick),
    Medal("quota", "On Quota", "day", "Reach your daily hours goal.",
          "Goal hit. Tomorrow, raise it.",
          RED, WHITE, "left", _goal_day),
    Medal("purity", "Pure Focus", "day", "90 % of 2 h+ tracked time spent in session.",
          "No drift, no doomscroll. Pure signal.",
          WHITE, BLUE, "left", _purity),

    # ---- weekly: two dots
    Medal("sevenforseven", "Seven for Seven", "week", "A session every day of the week.",
          "Seven days, seven sessions. Weekends are a legacy protocol.",
          TEAL, WHITE, "left", lambda p: p.active_days() == 7),
    Medal("thirtyclub", "Thirty Club", "week", "30 h of focus in a week.",
          "Thirty hours of real focus. Most 40-hour weeks contain twelve.",
          BLUE, WHITE, "none", lambda p: p.focus() >= 30 * H),
    Medal("fiftyclub", "Fifty Club", "week", "50 h of focus in a week.",
          "Fifty hours. Hardcore mode, as requested by management (you).",
          NAVY, GOLD, "both", lambda p: p.focus() >= 50 * H),
    Medal("taskcrusher", "Task Crusher", "week", "Finish 25 tasks in a week.",
          "Twenty-five tasks down. The backlog filed for bankruptcy.",
          GREEN, GOLD, "left", lambda p: p.tasks_done() >= 25),
    Medal("recordweek", "Record Week", "week", "Beat your best week ever (10 h+).",
          "New all-time high. Up only.",
          CRIMSON, GOLD, "both", _record("week", 10)),
    Medal("challengemaster", "Challenge Master", "week", "Win 5 extension challenges in a week.",
          "Five challenges in a week. Comfort zones are for incumbents.",
          GOLD, RED, "left", lambda p: len(p.challenges()) >= 5),
    Medal("weekendwarrior", "Weekend Warrior", "week", "Sessions on Saturday and Sunday.",
          "The weekend was a 20th-century regulation anyway.",
          ORANGE, PURPLE, "none", _weekend),
    Medal("noprocrastination", "Zero Procrastination", "week", "5+ sessions and none put off.",
          "Not a single 'later' all week. Optionality: declined.",
          WHITE, GREEN, "left", _no_procrastination),

    # ---- monthly: three dots
    Medal("ironmonth", "Iron Month", "month", "20 active days in a month.",
          "Twenty days on. The month belongs to you.",
          TEAL, GOLD, "left", lambda p: p.active_days() >= 20),
    Medal("centurion", "Centurion", "month", "100 h of focus in a month.",
          "A hundred hours. Rome would have given you a legion.",
          NAVY, GOLD, "both", lambda p: p.focus() >= 100 * H),
    Medal("cleansweep", "Clean Sweep", "month", "Finish 80 tasks in a month.",
          "Eighty tasks in a month. Throughput is a moral virtue.",
          GREEN, GOLD, "both", lambda p: p.tasks_done() >= 80),
    Medal("recordmonth", "Record Month", "month", "Beat your best month ever (40 h+).",
          "Best month on record. The chart only knows one direction.",
          CRIMSON, GOLD, "both", _record("month", 40)),
    Medal("streaklord", "Streak Lord", "month", "14 days in a row within the month.",
          "Two weeks unbroken. Momentum is a physical law.",
          RED, GOLD, "left", lambda p: _streak_in(p, 14)),
    Medal("rainorshine", "Rain or Shine", "month", "Finish sessions in 3 kinds of weather.",
          "Rain, sun, snow: same output. Weather is not a KPI.",
          TEAL, WHITE, "none", _weathers),
]

BY_ID = {m.id: m for m in MEDALS}


# ------------------------------------------------------------------ awards


def _extras(store, ctx: A.Context) -> tuple[list, set]:
    won = [(T.date_str(r["ended_at"]), r["session_id"])
           for r in store.db.execute("SELECT ended_at, session_id FROM challenges WHERE state='won'")]
    put_off = {T.date_str(r["ended_at"]) for r in store.all_sessions()
               if r["end_reason"] == "procrastinated" and r["ended_at"] is not None}
    return won, put_off


def evaluate(store, now: int, history: bool = False) -> list[dict]:
    """Award what the current periods (or, with `history`, every period with
    activity) now justify. Returns the new awards."""
    ctx = A.build_context(store, now, level=1)
    won, put_off = _extras(store, ctx)
    held = store.medal_awards()
    today = dt.date.fromisoformat(T.date_str(now))
    if history:
        anchors = sorted({dt.date.fromisoformat(d) for d in ctx.day_sessions} | {today})
    else:
        anchors = [today]
    fresh = []
    for m in MEDALS:
        seen = set()
        for day in anchors:
            key = period_key(m.period, day)
            if key in seen or (m.id, key) in held:
                continue
            seen.add(key)
            days = [d for d in period_days(m.period, day) if d <= today]
            if m.check(Period(m.period, days, ctx, won, put_off)):
                store.award_medal(m.id, key, now, m.xp)
                held.add((m.id, key))
                fresh.append({"id": m.id, "name": m.name, "period": m.period, "key": key,
                              "xp": m.xp, "quip": m.quip})
    return fresh


def placard(store, now: int) -> list[dict]:
    """Every medal won at least once, for the jacket: most valuable first."""
    today = dt.date.fromisoformat(T.date_str(now))
    counts = store.medal_counts()
    out = []
    for m in MEDALS:
        c = counts.get(m.id)
        if not c:
            continue
        out.append(dict(m.ribbon(), id=m.id, name=m.name, period=m.period, desc=m.desc,
                        count=c["count"], current=c["last_key"] == period_key(m.period, today),
                        xp=m.xp))
    rank = {"month": 0, "week": 1, "day": 2}
    out.sort(key=lambda r: (rank[r["period"]], -EDGE_FACTOR[r["edges"]], -r["count"]))
    return out


def catalogue(store, now: int) -> dict:
    today = dt.date.fromisoformat(T.date_str(now))
    counts = store.medal_counts()
    medals = []
    for m in MEDALS:
        c = counts.get(m.id) or {"count": 0, "last_key": None}
        medals.append(dict(m.ribbon(), id=m.id, name=m.name, period=m.period, desc=m.desc,
                           quip=m.quip, xp=m.xp, count=c["count"],
                           current=c["last_key"] == period_key(m.period, today)))
    return {"success": True, "medals": medals}
