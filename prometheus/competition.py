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
from .store import session_seconds

FOCUS_SECONDS_PER_XP = 600

# --------------------------------------------------------------- leagues

LEAGUES = ["Bronze", "Silver", "Gold", "Sapphire", "Ruby", "Emerald", "Amethyst", "Pearl", "Obsidian", "Diamond"]
LEAGUE_COLORS = ["#cd7f32", "#c0c0c0", "#ffd700", "#2f6fdb", "#e0115f", "#50c878", "#9966cc", "#eae0c8",
                 "#6b6b85", "#b9f2ff"]
# The rivals' average weekly XP never goes under the league's floor (about
# 6 XP per hour of focus), and each league up makes them 5 % stronger.
LEAGUE_FLOORS = [10, 30, 50, 75, 100, 130, 160, 200, 240, 300]
LEAGUE_STEP = 0.05
REFERENCE_WEEKS = 4
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

SEASON_GOAL = 300            # the first goal, at least
SEASON_HARD_GOAL = 600       # the second goal, at least
SEASON_HARD_FACTOR = 1.25    # the second goal: the previous season's XP + 25 %
SEASON_MEDAL_XP = {1: 75, 2: 200}   # one bar, two bars (in all)
GRADES = [("A", "hard"), ("B", "goal"), ("C", 0.75), ("D", 0.5)]   # else F


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _monday(d: dt.date) -> dt.date:
    """The first day of the week of `d`: a Sunday (the name stayed)."""
    return T.week_first(d)


def _quarter(d: dt.date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def _quarter_start(y: int, q: int) -> dt.date:
    return dt.date(y, 3 * (q - 1) + 1, 1)


def _next_quarter(y: int, q: int) -> tuple[int, int]:
    return (y + 1, 1) if q == 4 else (y, q + 1)


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
    """The nine rivals of a season (key "2026-Q4"): drawn by lot, first names
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


def _rivals(week: dt.date, league: int, prev: list[int], progress: float) -> list[dict]:
    """Nine made-up players for a league week, drawn from a Gaussian fitted to
    your last four weeks (stronger each league up). Seeded by week and league,
    so a week always replays the same. `progress` (0 to 1): how much of the
    week has gone by; each rival earns its total at its own pace."""
    rng = random.Random(f"{week.isoformat()}:{league}")
    ref = sum(prev) / len(prev) if prev else LEAGUE_FLOORS[min(league + 1, len(LEAGUES) - 1)]
    mean = max(ref * (1 + LEAGUE_STEP * league), LEAGUE_FLOORS[league])
    spread = 0.0
    if len(prev) >= 2:
        spread = (sum((x - ref) ** 2 for x in prev) / (len(prev) - 1)) ** 0.5
    sd = max(spread, 0.25 * mean)
    y, q = _quarter(week + dt.timedelta(days=3))     # the season of the week's middle
    names = season_roster(f"{y}-Q{q}")
    out = []
    for name in names:
        final = max(0, round(rng.gauss(mean, sd)))
        pace = rng.uniform(0.7, 1.4)                # under 1 starts fast, over 1 finishes strong
        out.append({"name": name, "xp": round(final * min(1.0, max(0.0, progress)) ** pace), "final": final})
    return out


def _standings(xp: int, rivals: list[dict], league: int) -> tuple[list[dict], int, str]:
    """The ten players ranked (ties go to you), your rank and your zone."""
    players = [dict(r, you=False) for r in rivals] + [{"name": "You", "xp": xp, "you": True}]
    players.sort(key=lambda r: (-r["xp"], not r["you"]))
    for i, r in enumerate(players):
        r["rank"] = i + 1
        r["zone"] = ("promotion" if i < PROMOTED else
                     "relegation" if i >= len(players) - RELEGATED else "stagnation")
    rank = next(r["rank"] for r in players if r["you"])
    zone = players[rank - 1]["zone"]
    if xp == 0:
        zone = "relegation"                        # an empty week never stays put
    return players, rank, zone


def leagues(ledger: Ledger) -> dict:
    """Every settled week, and where the current one stands."""
    weeks = ledger.week_xp()
    this_monday = _monday(ledger.today)
    first = ledger.first_day
    start = _monday(first) if first else this_monday
    league, history, xps = 0, [], []
    w = start
    while True:
        xp = weeks.get(w, 0)
        prev = xps[-REFERENCE_WEEKS:]
        current = w == this_monday
        progress = 1.0
        if current:
            week_ms = 7 * 86_400_000
            progress = (ledger.now - T.week_start(ledger.now)) / week_ms
        players, rank, zone = _standings(xp, _rivals(w, league, prev, progress), league)
        top, bottom = league == len(LEAGUES) - 1, league == 0
        moves = {"promotion": 0 if top else 1, "relegation": 0 if bottom else -1, "stagnation": 0}[zone]
        if current:
            others = sorted((r["xp"] for r in players if not r["you"]), reverse=True)
            end = w + dt.timedelta(days=7)
            return {
                "history": history,
                "current": {"week": w.isoformat(), "league": league, "name": LEAGUES[league],
                            "color": LEAGUE_COLORS[league], "xp": xp, "rank": rank, "zone": zone,
                            "players": [{k: r[k] for k in ("name", "xp", "you", "rank", "zone")} for r in players],
                            # XP to pass the 3rd rival (promotion) and the 7th (out of relegation).
                            "toPromotion": max(0, others[PROMOTED - 1] + 1 - xp),
                            "toSafety": max(0, others[len(others) - RELEGATED] + 1 - xp),
                            "top": top, "bottom": bottom, "reference": sum(prev) / len(prev) if prev else None,
                            "daysLeft": (end - ledger.today).days},
            }
        after = league + moves
        history.append({"week": w.isoformat(), "before": league, "after": after, "xp": xp, "rank": rank,
                        "outcome": "up" if after > league else "down" if after < league else "stay"})
        league = after
        xps.append(xp)
        w += dt.timedelta(days=7)


# --------------------------------------------------------------- seasons


def _grade(xp: int, goal: int, hard: int) -> str:
    for letter, need in GRADES:
        bar = hard if need == "hard" else goal if need == "goal" else goal * need
        if xp >= bar:
            return letter
    return "F"


def seasons(ledger: Ledger) -> list[dict]:
    """Every season from the first with work, the current one last."""
    first = ledger.first_day or ledger.today
    y, q = _quarter(first)
    cur = _quarter(ledger.today)
    out, prev_xp, number = [], None, 1
    while (y, q) <= cur:
        start = _quarter_start(y, q)
        ny, nq = _next_quarter(y, q)
        end = _quarter_start(ny, nq)
        xp = ledger.between(ledger.xp, start, end)
        goal = max(SEASON_GOAL, prev_xp or 0)
        hard = max(SEASON_HARD_GOAL, math.ceil((prev_xp or 0) * SEASON_HARD_FACTOR / 10) * 10)
        running = (y, q) == cur
        weeks = defaultdict(int)
        for d, x in ledger.xp.items():
            if start <= _date(d) < end:
                weeks[_monday(_date(d))] += x
        season = {
            "key": f"{y}-Q{q}", "number": number, "label": f"Q{q} {y}",
            "start": start.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(),
            "running": running, "xp": xp, "goal": goal, "hardGoal": hard,
            "bars": 2 if xp >= hard else 1 if xp >= goal else 0,
            "grade": None if running else _grade(xp, goal, hard),
            "hours": round(ledger.between(ledger.focus, start, end) / 3600, 1),
            "sessions": ledger.between(ledger.sessions, start, end),
            "tasks": ledger.between(ledger.tasks, start, end),
            "quests": ledger.between(ledger.quests, start, end),
            "bestWeek": max(weeks.values(), default=0),
        }
        if running:
            total = (end - start).days
            elapsed = (ledger.today - start).days + 1
            season["daysLeft"] = (end - ledger.today).days
            season["projected"] = _grade(round(xp * total / max(1, elapsed)), goal, hard)
        out.append(season)
        prev_xp, number = xp, number + 1
        y, q = ny, nq
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
    """The colors the season's medal will have: drawn once, as the season
    starts, so the preview shows the very medal to win."""
    saved = store.get_setting("seasonColors") or {}
    if key not in saved:
        saved[key] = season_colors()
        store.set_setting("seasonColors", saved)
    return saved[key]


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
            new.append({"name": f"Season {s['number']} medal", "xp": SEASON_MEDAL_XP[s["bars"]],
                        "quip": "Two bars. The hard goal, cleared." if s["bars"] == 2 else "Season goal reached."})
        elif row["bars"] < s["bars"]:
            store.db.execute("UPDATE season_medals SET bars=?, xp=? WHERE season=?",
                             (s["bars"], SEASON_MEDAL_XP[s["bars"]], s["key"]))
            new.append({"name": f"Season {s['number']} medal, second bar",
                        "xp": SEASON_MEDAL_XP[s["bars"]] - row["xp"], "quip": "The hard goal, cleared."})
    return new


def season_medals(store) -> list[dict]:
    """The permanent season medals, newest first, for the placard."""
    out = []
    for r in store.db.execute("SELECT * FROM season_medals ORDER BY season DESC"):
        y, q = r["season"].split("-Q")
        out.append({"id": "season:" + r["season"], "season": r["season"], "number": r["number"],
                    "bars": r["bars"], "color": r["bg"], "dot": r["dot"], "edge": r["edge"],
                    "name": f"Season {r['number']}", "period": "season", "count": 1, "current": False,
                    "desc": f"Q{q} {y} · " + ("hard goal reached, two bars" if r["bars"] == 2 else "goal reached"),
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
