"""Leagues, seasons and leaderboards: playing against your own past.

Everything here is worked out from the records, except the season medals,
which are kept once won (with their random colors) and never lost.

Earned XP, the currency of all three, is XP from the work itself: focus,
tasks, challenges won and quests. Achievements and medals are left out, so a
reward never feeds the race that grants it.

- Leagues: ten, Bronze to Diamond. Each week (Sunday to Saturday, logical days)
  is settled against your own recent weeks: up one league at most, down one
  at most. Promotion needs both 10 % more than the average of the four weeks
  before and the next league's floor. Relegation comes when the week falls
  under 90 % of that average and under the league's floor, or earns nothing.
- Seasons: calendar quarters, numbered from the first one with any work. Two
  XP goals, the previous season's XP being the bar: reaching the first wins
  a season medal with one bar, the second a medal with two bars. A season
  ends with a grade, A to F.
- Leaderboards: your best days, weeks, sessions and quests, ranked.
"""

from __future__ import annotations

import colorsys
import datetime as dt
import math
import random
from collections import defaultdict

from . import timeutil as T
from .bios import bio
from .store import ABANDON_PENALTY, session_seconds

FOCUS_SECONDS_PER_XP = 600

# --------------------------------------------------------------- leagues

LEAGUES = ["Bronze", "Silver", "Gold", "Sapphire", "Ruby", "Emerald", "Amethyst", "Pearl", "Obsidian", "Diamond"]
LEAGUE_COLORS = ["#cd7f32", "#c0c0c0", "#ffd700", "#2f6fdb", "#e0115f", "#50c878", "#9966cc", "#eae0c8",
                 "#6b6b85", "#b9f2ff"]
# A league round lasts two weeks, Sunday to the second Saturday, counted from
# a fixed Sunday so every round lines up.
ROUND_DAYS = 14
ROUND_ANCHOR = dt.date(2023, 1, 1)     # a Sunday
# Promotion takes a top-3 finish and at least this much XP a week, over the
# round (twice it), Bronze to Obsidian; Diamond has nowhere higher. About 6 XP
# per hour of focus: 300 a week is a strong week. Obsidian is twice Ruby.
PROMOTION_MIN_WEEKLY = [300, 340, 385, 435, 490, 580, 690, 820, 980]
DIAMOND_WEEKLY = 1150                  # what Diamond rivals play at, at least
# Your history sets the rivals' level (your last two rounds, 5 % stronger each
# league up), unless it is under 87 % of the league's minimum: then that
# floor is used instead, so the third of nine sits about at the minimum.
RIVAL_FLOOR_SHARE = 0.87
LEAGUE_STEP = 0.05
REFERENCE_ROUNDS = 2
PROMOTION_MIN = [2 * m for m in PROMOTION_MIN_WEEKLY]                  # per round
LEAGUE_FLOORS = [round(RIVAL_FLOOR_SHARE * m) for m in PROMOTION_MIN] + [round(RIVAL_FLOOR_SHARE * 2 * DIAMOND_WEEKLY)]
SHINING_FROM = 5                       # Emerald and up shine
RIVALS = 9                   # plus you: ten players a week
PROMOTED = 3                 # the top 3 go up
RELEGATED = 3                # the bottom 3 go down
# Scientists and pioneers. Each season draws its own nine rivals from them
# (by lot, seeded by the season), never two with the same first name.
RIVAL_NAMES = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "John von Neumann", "Claude Shannon",
    "Edsger Dijkstra", "Donald Knuth", "Dennis Ritchie", "Linus Torvalds", "John Carmack", "Steve Wozniak",
    "Margaret Hamilton", "Richard Feynman", "Charles Babbage", "Douglas Engelbart", "Alan Kay",
    "Nikola Tesla", "Marie Curie", "Emmy Noether", "Srinivasa Ramanujan", "Leonhard Euler",
    "Carl Friedrich Gauss", "Hedy Lamarr", "Satoshi Nakamoto", "Isaac Newton", "Albert Einstein",
    "Niels Bohr", "Max Planck", "Werner Heisenberg", "Erwin Schrodinger", "Paul Dirac", "Enrico Fermi",
    "Lise Meitner", "Rosalind Franklin", "Barbara McClintock", "Dorothy Hodgkin", "Katherine Johnson",
    "Mary Jackson", "Dorothy Vaughan", "Annie Easley", "Galileo Galilei", "Johannes Kepler",
    "Nicolaus Copernicus", "Tycho Brahe", "Edwin Hubble", "Carl Sagan", "Vera Rubin", "Henrietta Leavitt",
    "Cecilia Payne", "Jocelyn Bell", "Michael Faraday", "James Clerk Maxwell", "Ernest Rutherford",
    "Dmitri Mendeleev", "Louis Pasteur", "Antoine Lavoisier", "Gregor Mendel", "Charles Darwin",
    "Alfred Wallace", "Rachel Carson", "Jane Goodall", "Alexander Fleming", "Jonas Salk", "Tim Berners-Lee",
    "Vint Cerf", "Bob Kahn", "Ken Thompson", "Bjarne Stroustrup", "Guido van Rossum", "John McCarthy",
    "Marvin Minsky", "Barbara Liskov", "Frances Allen", "Radia Perlman", "Shafi Goldwasser",
    "Whitfield Diffie", "Ralph Merkle", "Ron Rivest", "Adi Shamir", "Leslie Lamport", "Butler Lampson",
    "Ivan Sutherland", "Seymour Cray", "Gordon Moore", "Robert Noyce", "Jack Kilby", "John Bardeen",
    "William Shockley", "Hans Bethe", "Robert Oppenheimer", "Wernher von Braun", "Sergei Korolev",
    "Konstantin Tsiolkovsky", "Robert Goddard", "Yuri Gagarin", "Valentina Tereshkova", "Sally Ride",
    "Neil Armstrong", "Buzz Aldrin", "John Glenn", "Wilbur Wright", "Orville Wright", "Amelia Earhart",
    "Elon Musk"]

# --------------------------------------------------------------- seasons

# Seasons follow the weather: winter from December 1st, spring from March 1st,
# summer from June 1st, autumn from September 1st. Goals are weekly rates over
# the season's length (from your first day, the first season): the goal is
# your good weeks' pace (the better half of the 26 weeks before), 250 XP a
# week at least; the hard goal 30 % above it, 350 XP a week at least.
SEASON_NAMES = ["Winter", "Spring", "Summer", "Autumn"]
SEASON_START_MONTH = [12, 3, 6, 9]
SEASON_WEEKLY_GOAL = 250
SEASON_WEEKLY_HARD = 350
SEASON_HARD_FACTOR = 1.30
SEASON_LOOKBACK_WEEKS = 26
SEASON_MIN_WEEKS = 4         # fewer weeks of history: the minimums decide
SEASON_MEDAL_XP = {1: 75, 2: 200}   # one bar, two bars (in all)
# S beyond the hard goal by 20 %, A the hard goal, B the goal, C 80 % of it,
# D 60 %, F below.
GRADES = [("S", "beyond"), ("A", "hard"), ("B", "goal"), ("C", 0.8), ("D", 0.6)]
S_FACTOR = 1.2


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _monday(d: dt.date) -> dt.date:
    """The first day of the week of `d`: a Sunday (the name stayed)."""
    return T.week_first(d)


def _season(d: dt.date) -> tuple[int, int]:
    """(year, index) of the season of `d`: 0 winter (the year of its
    December), 1 spring, 2 summer, 3 autumn."""
    if d.month == 12:
        return d.year, 0
    if d.month <= 2:
        return d.year - 1, 0
    return d.year, (d.month - 3) // 3 + 1


def _season_start(y: int, i: int) -> dt.date:
    return dt.date(y, SEASON_START_MONTH[i], 1)


def _next_season(y: int, i: int) -> tuple[int, int]:
    return (y + 1, 1) if i == 0 else (y, 0) if i == 3 else (y, i + 1)


def _season_key(y: int, i: int) -> str:
    return f"{y}-{SEASON_NAMES[i].lower()}"


def season_label(key: str) -> str:
    """"2026-autumn" -> "Autumn 2026"."""
    y, name = key.split("-", 1)
    return f"{name.capitalize()} {y}"


# ------------------------------------------------------------ the ledger


class Ledger:
    """Earned XP, focus and counts per logical day, read once."""

    def __init__(self, store, now: int):
        self.now = now
        self.today = _date(T.date_str(now))
        self.xp = defaultdict(int)          # date -> earned XP
        self.focus = defaultdict(int)       # date -> focus seconds
        self.sessions = defaultdict(int)    # date -> sessions
        self.tasks = defaultdict(int)       # date -> tasks checked
        self.quests = defaultdict(int)      # date -> short or long quests finished
        self.session_rows = []              # (focus seconds, start ms, task, open)
        for r in store.all_sessions():
            sec = session_seconds(r, until=now)
            d = T.date_str(r["started_at"])
            self.xp[d] += sec // FOCUS_SECONDS_PER_XP
            self.focus[d] += sec
            self.sessions[d] += 1
            self.session_rows.append((sec, r["started_at"], r["task"], r["ended_at"] is None))
        db = store.db
        for r in db.execute("SELECT created_at, done_at, xp FROM tasks WHERE done_at IS NOT NULL"):
            d = T.date_str(r["done_at"])
            self.xp[d] += r["xp"] if r["xp"] is not None else 1 + max(0, (r["done_at"] - r["created_at"]) // 86_400_000)
            self.tasks[d] += 1
        for r in db.execute("SELECT ended_at, xp FROM challenges WHERE state='won' AND ended_at IS NOT NULL"):
            self.xp[T.date_str(r["ended_at"])] += r["xp"]
        for r in db.execute("SELECT ended_at FROM challenges WHERE state='abandoned' AND ended_at IS NOT NULL"):
            self.xp[T.date_str(r["ended_at"])] -= ABANDON_PENALTY
        for r in db.execute("SELECT done_at, xp FROM quests WHERE done_at IS NOT NULL"):
            d = T.date_str(r["done_at"])
            self.xp[d] += r["xp"] or 0
            self.quests[d] += 1
        for r in db.execute("SELECT done_at, xp FROM quest_done"):
            self.xp[T.date_str(r["done_at"])] += r["xp"]

    @property
    def first_day(self) -> dt.date | None:
        days = [_date(d) for d, x in self.xp.items() if x > 0]
        return min(days) if days else None

    def between(self, table: dict, start: dt.date, end: dt.date) -> int:
        return sum(v for d, v in table.items() if start <= _date(d) < end)

    def week_xp(self) -> dict[dt.date, int]:
        weeks = defaultdict(int)
        for d, x in self.xp.items():
            weeks[_monday(_date(d))] += x
        return weeks


# --------------------------------------------------------------- leagues


def season_roster(key: str) -> list[str]:
    """The nine rivals of a season (key "2026-autumn"): drawn by lot, first names
    all different."""
    rng = random.Random("roster:" + key)
    pool = RIVAL_NAMES[:]
    rng.shuffle(pool)
    roster, firsts = [], set()
    for name in pool:
        first = name.split()[0]
        if first not in firsts:
            roster.append(name)
            firsts.add(first)
        if len(roster) == RIVALS:
            break
    return roster


def round_start(d: dt.date) -> dt.date:
    """The Sunday opening the two-week league round of `d`."""
    return ROUND_ANCHOR + dt.timedelta(days=ROUND_DAYS * ((d - ROUND_ANCHOR).days // ROUND_DAYS))


def _rivals(week: dt.date, league: int, prev: list[int], progress: float) -> list[dict]:
    """Nine made-up players for a league round, drawn from a Gaussian fitted to
    your last two rounds (stronger each league up, never under the league's
    floor). Seeded by round and league, so a round always replays the same.
    `progress` (0 to 1): how much of the round has gone by; each rival earns
    its total at its own pace."""
    rng = random.Random(f"{week.isoformat()}:{league}")
    ref = sum(prev) / len(prev) if prev else 0
    mean = max(ref * (1 + LEAGUE_STEP * league), LEAGUE_FLOORS[league])
    spread = 0.0
    if len(prev) >= 2:
        spread = (sum((x - ref) ** 2 for x in prev) / (len(prev) - 1)) ** 0.5
    sd = max(spread, 0.25 * mean)
    names = season_roster(_season_key(*_season(week + dt.timedelta(days=ROUND_DAYS // 2))))   # the round's middle
    out = []
    for name in names:
        final = max(0, round(rng.gauss(mean, sd)))
        pace = rng.uniform(0.7, 1.4)                # under 1 starts fast, over 1 finishes strong
        out.append({"name": name, "xp": round(final * min(1.0, max(0.0, progress)) ** pace), "final": final})
    return out


def _standings(xp: int, rivals: list[dict], league: int, progress: float = 1.0) -> tuple[list[dict], int, str]:
    """The ten players ranked (ties go to you), your rank and your zone. The
    top 3 without the league's promotion minimum is no promotion; during the
    round, the minimum is prorated like the rivals' XP."""
    players = [dict(r, you=False) for r in rivals] + [{"name": "You", "xp": xp, "you": True}]
    players.sort(key=lambda r: (-r["xp"], not r["you"]))
    for i, r in enumerate(players):
        r["rank"] = i + 1
        r["zone"] = ("promotion" if i < PROMOTED else
                     "relegation" if i >= len(players) - RELEGATED else "stagnation")
    rank = next(r["rank"] for r in players if r["you"])
    zone = players[rank - 1]["zone"]
    if zone == "promotion" and league < len(PROMOTION_MIN) and xp < PROMOTION_MIN[league] * progress:
        zone = "stagnation"
    if xp == 0:
        zone = "relegation"                        # an empty week never stays put
    return players, rank, zone


def leagues(ledger: Ledger) -> dict:
    """Every settled round, and where the current one stands."""
    days = defaultdict(int)
    for d, x in ledger.xp.items():
        days[round_start(_date(d))] += x
    this_round = round_start(ledger.today)
    first = ledger.first_day
    start = round_start(first) if first else this_round
    league, history, xps = 0, [], []
    r = start
    round_ms = ROUND_DAYS * 86_400_000
    while True:
        xp = days.get(r, 0)
        prev = xps[-REFERENCE_ROUNDS:]
        current = r == this_round
        progress = 1.0
        if current:
            progress = (ledger.now - T._start_of(r)) / round_ms
        players, rank, zone = _standings(xp, _rivals(r, league, prev, progress), league, progress)
        top, bottom = league == len(LEAGUES) - 1, league == 0
        moves = {"promotion": 0 if top else 1, "relegation": 0 if bottom else -1, "stagnation": 0}[zone]
        end = r + dt.timedelta(days=ROUND_DAYS)
        if current:
            others = sorted((p["xp"] for p in players if not p["you"]), reverse=True)
            minimum = PROMOTION_MIN[league] if league < len(PROMOTION_MIN) else None
            return {
                "history": history,
                "current": {"week": r.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(),
                            "league": league, "name": LEAGUES[league], "shining": league >= SHINING_FROM,
                            "color": LEAGUE_COLORS[league], "xp": xp, "rank": rank, "zone": zone,
                            "players": [dict({k: p[k] for k in ("name", "xp", "you", "rank", "zone")},
                                             bio=None if p["you"] else bio(p["name"])) for p in players],
                            # XP to pass the 3rd rival and the minimum so far (promotion),
                            # and to pass the 7th (out of relegation).
                            "toPromotion": max(0, others[PROMOTED - 1] + 1 - xp,
                                               math.ceil(minimum * progress) - xp if minimum else 0),
                            "promotionMin": minimum,
                            "promotionMinSoFar": math.ceil(minimum * progress) if minimum else None,
                            "toSafety": max(0, others[len(others) - RELEGATED] + 1 - xp),
                            "top": top, "bottom": bottom, "reference": sum(prev) / len(prev) if prev else None,
                            "progress": round(progress, 3), "daysLeft": (end - ledger.today).days},
            }
        after = league + moves
        history.append({"week": r.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(),
                        "before": league, "after": after, "xp": xp, "rank": rank,
                        "outcome": "up" if after > league else "down" if after < league else "stay"})
        league = after
        xps.append(xp)
        r = end


# --------------------------------------------------------------- seasons


def _grade(xp: int, goal: int, hard: int) -> str:
    for letter, need in GRADES:
        bar = (hard * S_FACTOR if need == "beyond" else hard if need == "hard"
               else goal if need == "goal" else goal * need)
        if xp >= bar:
            return letter
    return "F"


def _round10(x: float) -> int:
    return int(math.ceil(x / 10) * 10)


def _good_weeks_pace(weeks: dict, before: dt.date) -> float | None:
    """Average of the better half of the complete weeks in the 26 before
    `before` (weeks with no XP count, from the first one with any)."""
    start = _monday(before) - dt.timedelta(days=7 * SEASON_LOOKBACK_WEEKS)
    first = min((w for w, x in weeks.items() if x > 0), default=None)
    if first is None:
        return None
    vals, w = [], max(start, first)
    while w + dt.timedelta(days=7) <= before:
        vals.append(weeks.get(w, 0))
        w += dt.timedelta(days=7)
    if len(vals) < SEASON_MIN_WEEKS:
        return None
    vals.sort(reverse=True)
    top = vals[:max(1, len(vals) // 2)]
    return sum(top) / len(top)


def seasons(ledger: Ledger) -> list[dict]:
    """Every season from the first with work, the current one last."""
    first = ledger.first_day or ledger.today
    y, i = _season(first)
    cur = _season(ledger.today)
    weeks_xp = ledger.week_xp()
    out, number = [], 1
    while _season_start(y, i) <= _season_start(*cur):
        start = _season_start(y, i)
        ny, ni = _next_season(y, i)
        end = _season_start(ny, ni)
        xp = ledger.between(ledger.xp, start, end)
        played = (end - max(start, first)).days / 7          # weeks the season counts for you
        pace = _good_weeks_pace(weeks_xp, start)
        goal = _round10(played * max(SEASON_WEEKLY_GOAL, pace or 0))
        hard = _round10(played * max(SEASON_WEEKLY_HARD, SEASON_HARD_FACTOR * (pace or 0)))
        running = (y, i) == cur
        weeks = defaultdict(int)
        for d, x in ledger.xp.items():
            if start <= _date(d) < end:
                weeks[_monday(_date(d))] += x
        key = _season_key(y, i)
        season = {
            "key": key, "number": number, "label": season_label(key),
            "start": start.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(),
            "running": running, "xp": xp, "goal": goal, "hardGoal": hard,
            "weeklyGoal": round(goal / played) if played else None,
            "weeklyHard": round(hard / played) if played else None,
            "bars": 2 if xp >= hard else 1 if xp >= goal else 0,
            "grade": None if running else _grade(xp, goal, hard),
            "hours": round(ledger.between(ledger.focus, start, end) / 3600, 1),
            "sessions": ledger.between(ledger.sessions, start, end),
            "tasks": ledger.between(ledger.tasks, start, end),
            "quests": ledger.between(ledger.quests, start, end),
            "bestWeek": max(weeks.values(), default=0),
        }
        if running:
            total = (end - max(start, first)).days
            elapsed = (ledger.today - max(start, first)).days + 1
            season["daysLeft"] = (end - ledger.today).days
            season["projected"] = _grade(round(xp * total / max(1, elapsed)), goal, hard)
        out.append(season)
        number += 1
        y, i = ny, ni
    return out


# The ten vivid hues of the other medals: a season medal never uses them.
BASE_COLORS = ["#f22424", "#ea9a23", "#c2ea23", "#4bea23", "#24f276",
               "#24f2f2", "#2476f2", "#4d24f2", "#c924f2", "#f2249f"]
MIN_BASE_DISTANCE = 70     # RGB distance a season color keeps from each of them


def _rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _far_from_base(c: str) -> bool:
    r, g, b = _rgb(c)
    return all(((r - R) ** 2 + (g - G) ** 2 + (b - B) ** 2) ** 0.5 >= MIN_BASE_DISTANCE
               for R, G, B in map(_rgb, BASE_COLORS))


def _random_color(rng: random.Random, hue: float, sat: tuple, val: tuple) -> str:
    """A color of about `hue`, kept away from the ten base hues (drawn again
    until it is)."""
    for _ in range(200):
        h = (hue + rng.uniform(-0.03, 0.03)) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, rng.uniform(*sat), rng.uniform(*val))
        c = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
        if _far_from_base(c):
            return c
        hue = rng.random()
    return "#5a4a7a"


def season_colors(rng: random.Random | None = None) -> dict:
    """Contrasted colors: a deep, rich ribbon, a near-white star, and vivid
    edge bars of another hue; none close to the ten base medal hues."""
    rng = rng or random.Random()
    hue = rng.random()
    return {
        "bg": _random_color(rng, hue, (0.60, 0.90), (0.26, 0.44)),
        "dot": _random_color(rng, hue + rng.uniform(0.35, 0.65), (0.05, 0.30), (0.93, 1.00)),
        "edge": _random_color(rng, hue + rng.uniform(0.25, 0.45), (0.55, 0.80), (0.70, 0.85)),
    }


def pending_colors(store, key: str) -> dict:
    """The colors of a season's medal: drawn from a seed made of the season's
    name, so every player, on any machine, gets the very same medal for the
    same season. (`store` is kept for the call sites.)"""
    return season_colors(random.Random("prometheus-season-medal:" + key))


def check_season_medals(store, ledger: Ledger, now: int) -> list[dict]:
    """Award (or upgrade to two bars) the season medals the records justify."""
    new = []
    have = {r["season"]: r for r in store.db.execute("SELECT * FROM season_medals")}
    for s in seasons(ledger):
        if s["bars"] == 0:
            continue
        row = have.get(s["key"])
        if row is None:
            c = pending_colors(store, s["key"])
            store.db.execute(
                "INSERT INTO season_medals(season, number, bars, bg, dot, edge, awarded_at, xp) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (s["key"], s["number"], s["bars"], c["bg"], c["dot"], c["edge"], now, SEASON_MEDAL_XP[s["bars"]]))
            new.append({"name": f"{s['label']} medal", "xp": SEASON_MEDAL_XP[s["bars"]],
                        "quip": "Two bars. The hard goal, cleared." if s["bars"] == 2 else "Season goal reached."})
        elif row["bars"] < s["bars"]:
            store.db.execute("UPDATE season_medals SET bars=?, xp=? WHERE season=?",
                             (s["bars"], SEASON_MEDAL_XP[s["bars"]], s["key"]))
            new.append({"name": f"{s['label']} medal, second bar",
                        "xp": SEASON_MEDAL_XP[s["bars"]] - row["xp"], "quip": "The hard goal, cleared."})
    return new


def season_medals(store) -> list[dict]:
    """The permanent season medals, newest first, for the placard."""
    out = []
    for r in store.db.execute("SELECT * FROM season_medals ORDER BY number DESC"):
        label = season_label(r["season"])
        out.append({"id": "season:" + r["season"], "season": r["season"], "number": r["number"],
                    "bars": r["bars"], "color": r["bg"], "dot": r["dot"], "edge": r["edge"],
                    "name": label, "period": "season", "count": 1, "current": False,
                    "desc": "season medal · " + ("hard goal reached, two bars" if r["bars"] == 2 else "goal reached"),
                    "xp": r["xp"]})
    return out


def season_xp_total(store) -> int:
    return int(store.db.execute("SELECT COALESCE(SUM(xp), 0) FROM season_medals").fetchone()[0])


# ----------------------------------------------------------- leaderboards


BOARDS = ("days", "weeks", "sessions", "quests")
BOARD_SIZE = 10


def leaderboard(store, ledger: Ledger, board: str, quests: list[dict] | None = None) -> dict:
    """Your best `board` entries, ranked, with where the current one stands."""
    today = ledger.today.isoformat()
    entries = []
    if board == "weeks":
        this = _monday(ledger.today)
        for w, x in ledger.week_xp().items():
            if x > 0 or w == this:
                entries.append({"label": "Week of " + w.strftime("%b %-d, %Y"), "value": x, "unit": "XP",
                                "date": w.isoformat(), "current": w == this})
    elif board == "sessions":
        for sec, start, task, is_open in ledger.session_rows:
            if sec > 0:
                when = dt.datetime.fromtimestamp(start / 1000)
                entries.append({"label": (task or "Session") + " · " + when.strftime("%b %-d, %Y"),
                                "value": sec, "unit": "s", "date": T.date_str(start), "current": is_open})
    elif board == "quests":
        for q in quests or []:
            if q.get("board_hidden"):
                continue
            if q["activity"]["xp"] > 0 or q.get("active"):
                entries.append({"id": q["id"], "label": q["title"], "value": q["activity"]["xp"], "unit": "XP",
                                "date": T.date_str(q["created"]), "current": bool(q.get("active"))})
    else:
        board = "days"
        days = dict(ledger.xp)
        days.setdefault(today, 0)
        for d, x in days.items():
            if x > 0 or d == today:
                entries.append({"label": _date(d).strftime("%a %b %-d, %Y"), "value": x, "unit": "XP",
                                "date": d, "current": d == today})
    # Ties: the earlier one keeps the higher rank (it got there first).
    entries.sort(key=lambda e: (-e["value"], e["date"]))
    for i, e in enumerate(entries):
        e["rank"] = i + 1
    you = next((e for e in entries if e["current"]), None)
    return {"success": True, "board": board, "entries": entries[:BOARD_SIZE], "count": len(entries),
            "you": you if you is not None and you["rank"] > BOARD_SIZE else None}


def records(values: list[tuple]) -> int:
    """Times an entry beat every entry before it (the first one is no record).
    `values`: (order key, value)."""
    best, n = None, 0
    for _, v in sorted(values):
        if best is not None and v > best:
            n += 1
        best = v if best is None else max(best, v)
    return n


def podiums(values: list[tuple], warmup: int = 5) -> int:
    """Entries that made the top 3 of everything so far, once `warmup`
    entries came before them."""
    seen, n = [], 0
    for _, v in sorted(values):
        if len(seen) >= warmup and sum(1 for s in seen if s > v) < 3:
            n += 1
        seen.append(v)
    return n
