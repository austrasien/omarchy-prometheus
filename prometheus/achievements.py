"""Achievements: a catalogue of families, each with one or more tiers, and
the measures that unlock them, all computed from Prometheus' own records.

A family has a measure (a number, or None when nothing qualifies yet) and
thresholds. Each threshold is a tier: an achievement with a name, a
description, a line for when it unlocks, and an XP reward. Tiered rewards
grow 5 XP per tier, capped at 50; a single achievement is worth 10 XP, a
secret one 25.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import timeutil as T
from .store import session_seconds

QUALIFYING_SECONDS = 10 * 60      # shorter sessions count for nothing
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

    @property
    def single(self) -> bool:
        return len(self.thresholds) == 1

    def tier_id(self, i: int) -> str:
        return self.id if self.single else f"{self.id}:{self.thresholds[i]:g}"

    def xp(self, i: int) -> int:
        if self.secret:
            return 25
        if self.single:
            return 10
        return min(50, 5 * (i + 1))

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
    reflexes: int = 0                                        # "Toujours là ?" answered in < 10 s
    inbox_zero: int = 0                                      # times the to-do list was emptied
    put_off: list = field(default_factory=list)              # (task text, when) of procrastinated sessions
    switches: dict = field(default_factory=dict)             # session id -> app changes


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _local(ms: int) -> dt.datetime:
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
    ctx.sessions.sort(key=lambda s: s["start"])

    # Procrastinations count every put-off session, however short.
    for r in store.all_sessions():
        if r["end_reason"] == "procrastinated" and r["task"]:
            ctx.procrastinations[r["task"]] = ctx.procrastinations.get(r["task"], 0) + 1
            ctx.put_off.append((r["task"], r["ended_at"] or now))

    ctx.tasks_done = [{"text": r["text"], "created": r["created_at"], "done": r["done_at"]}
                      for r in store.done_tasks()]
    ctx.reflexes = store.count_events("reflex")
    ctx.inbox_zero = store.count_events("inbox_zero")
    ctx.switches = _app_switches(store)
    ctx.challenges_won = int(store.db.execute("SELECT COUNT(*) FROM challenges WHERE state='won'").fetchone()[0])
    ctx.triples = int(store.db.execute(
        "SELECT COUNT(*) FROM (SELECT session_id FROM challenges WHERE state='won' "
        "GROUP BY session_id HAVING COUNT(*) >= 3)").fetchone()[0])
    ctx.absences = store.count_events("absent")
    goal = store.get_setting("hoursGoal")
    if goal and goal.get("period") == "day":
        ctx.goal_hours = float(goal["hours"])
    ctx.monotask = _longest_single_app(store)
    return ctx


def _app_switches(store) -> dict:
    """App changes per session (a pause or an idle cut in one app is not a switch)."""
    out, sid, app = {}, None, None
    for r in store.db.execute(
        "SELECT session_id, app FROM focus_spans WHERE session_id IS NOT NULL ORDER BY session_id, started_at"
    ):
        if r["session_id"] != sid:
            sid, app = r["session_id"], r["app"]
            out[sid] = 0
        elif r["app"] != app:
            out[sid] += 1
            app = r["app"]
    return out


def _longest_single_app(store, gap_ms: int = 60_000) -> float:
    """Longest stretch in one app inside a session (short gaps bridged), in s."""
    best, cur_sid, cur_app, cur_start, cur_end = 0, None, None, 0, 0
    for r in store.db.execute(
        "SELECT session_id, app, started_at, ended_at FROM focus_spans "
        "WHERE session_id IS NOT NULL ORDER BY session_id, started_at"
    ):
        if r["session_id"] == cur_sid and r["app"] == cur_app and r["started_at"] - cur_end <= gap_ms:
            cur_end = max(cur_end, r["ended_at"])
        else:
            cur_sid, cur_app, cur_start, cur_end = r["session_id"], r["app"], r["started_at"], r["ended_at"]
        best = max(best, cur_end - cur_start)
    return best / 1000


# -------------------------------------------------------------- measures


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
        y, w, _ = _date(d).isocalendar()
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


def _comeback(c: Context) -> float | None:
    for a, b in zip(c.sessions, c.sessions[1:]):
        if b["start"] - a["end"] >= 7 * DAY * 1000:
            return 1
    return None


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
    Family("sessions", "Shipping cadence", lambda c: len(c.closed) or None, [10, 20, 40, 80],
           lambda t: f"Shipping Cadence {t:g}", lambda t: f"Complete {t:g} sessions.",
           ["Ten sessions. The flywheel spins. Keep regulators away from it.",
            "Twenty. Iteration speed is the only moat that matters.",
            "Forty sessions. You're compounding faster than the Fed can print.",
            "Eighty. That's not a habit anymore, that's a launch cadence."]),
    Family("tasks", "Zero to one", lambda c: len(c.tasks_done) or None, [10, 20, 40, 80],
           lambda t: f"Zero to {t:g}", lambda t: f"Finish {t:g} tasks.",
           ["Zero to ten. Thiel would call it a start. A small one.",
            "Twenty tasks shipped while the committee is still drafting the memo.",
            "Forty. Execution is the only ideology that compiles.",
            "Eighty. You ship like paperwork is a myth from a dying civilization."]),
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
    Family("goal", "Quota crusher", _goal_streak, [3, 5, 10, 20, 30],
           lambda t: f"Quota Crusher ×{t:g}", lambda t: f"Hit your daily hours goal {t:g} days in a row.",
           ["Goal hit {n} days running. Targets are floors, not ceilings."], unit="days"),
    Family("comeback", "Return of the king", _comeback, [1],
           lambda t: "Return of the King", lambda t: "Start a session after 7 days without one.",
           ["You're back. The market missed you. Briefly."]),

    # ---- tasks
    Family("tasksday", "Throughput", lambda c: _tasks_per(c, lambda d: d), [5, 10, 15, 20, 25, 30],
           lambda t: f"Throughput {t:g}/day", lambda t: f"Finish {t:g} tasks in one day.",
           ["{n} tasks in a day. Bureaucracies measure that per fiscal year.",
            "{n} in a day. Move fast and finish things.",
            "{n} tasks today. Your to-do list is filing for bankruptcy."]),
    Family("tasksweek", "Weekly burn", lambda c: _tasks_per(c, lambda d: d.isocalendar()[:2]),
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
           lambda t: "Proof of Absence", lambda t: "Get paused 10 times for not answering « Toujours là ? ».",
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
           lambda t: f"Quick Draw {t:g}", lambda t: f"Answer « Toujours là ? » in under 10 seconds, {t:g} times.",
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
    Family("frost", "Cryo mode", lambda c: sum(1 for s in c.closed if s["temp"] is not None and s["temp"] < 0) or None,
           [1, 5, 10, 20, 30],
           lambda t: f"Cryo Mode {t:g}", lambda t: f"Finish {t:g} sessions below 0 °C.",
           ["Below zero, still running. Practicing for cryonics."]),
]


# ------------------------------------------------------------- evaluation


def evaluate(store, now: int, level_for_xp: Callable[[int], int], base_xp: int) -> list[dict]:
    """Unlock what the records now justify; returns the new unlocks.

    Level achievements grant XP that can raise the level, so this runs until
    nothing new unlocks."""
    fresh: list[dict] = []
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
                                "quip": f.quip(i), "secret": f.secret})
        if not new:
            return fresh
        fresh.extend(new)


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
                          "quip": f.quip(i) if row else None})
        revealed = not f.secret or any(t["unlockedAt"] for t in tiers)
        if not revealed:
            tiers = [{"id": None, "threshold": None, "name": "???", "desc": "Secret achievement.",
                      "xp": f.xp(0), "unlockedAt": None, "quip": None}]
        families.append({
            "id": f.id, "title": f.title if revealed else "???", "secret": f.secret,
            "unit": f.unit, "compare": f.compare,
            "value": (None if value is None or not revealed else round(value / f.scale, 2)),
            "tiers": tiers,
        })
    return {"success": True, "families": families, "unlocked": got, "total": total, "xp": xp}
