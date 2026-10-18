"""Day, week and month boundaries, in epoch milliseconds.

A "day" starts at DAY_START_HOUR local time (5 h by default), not midnight:
a night of work until 1 h counts for the evening it started, the way
Habitica's custom day start does. Every boundary in Prometheus goes
through these functions, so changing the hour moves them all.
"""

from __future__ import annotations

import datetime as dt
import time

DEFAULT_DAY_START_HOUR = 5
_day_start_hour = DEFAULT_DAY_START_HOUR


def set_day_start_hour(hour: int) -> None:
    global _day_start_hour
    _day_start_hour = max(0, min(12, int(hour)))


def day_start_hour() -> int:
    return _day_start_hour


def now_ms() -> int:
    return int(time.time() * 1000)


def _local(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000).astimezone()


def _ms(d: dt.datetime) -> int:
    return int(d.timestamp() * 1000)


def _logical_date(ms: int) -> dt.date:
    """The calendar date a moment belongs to, once the day start is applied."""
    return (_local(ms) - dt.timedelta(hours=_day_start_hour)).date()


def _start_of(date: dt.date) -> int:
    return _ms(dt.datetime.combine(date, dt.time(hour=_day_start_hour)).astimezone())


def day_start(ms: int) -> int:
    return _start_of(_logical_date(ms))


def add_days(day_start_ms: int, days: int) -> int:
    """Start of the day `days` later. Built from the calendar date, so DST days are right."""
    return _start_of(_logical_date(day_start_ms) + dt.timedelta(days=days))


def date_str(ms: int) -> str:
    return _logical_date(ms).strftime("%Y-%m-%d")


def days_between(earlier_ms: int, later_ms: int) -> int:
    """Day starts crossed going from one moment to the other."""
    return (_logical_date(later_ms) - _logical_date(earlier_ms)).days


# Weeks run Sunday to Saturday.

def week_first(d: dt.date) -> dt.date:
    """The Sunday opening the week of date `d`."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def week_key(d: dt.date) -> tuple[int, int]:
    """(year, week number) of a Sunday-to-Saturday week: the ISO week of its
    Monday, so the Sunday counts with the days after it."""
    y, w, _ = (d + dt.timedelta(days=1)).isocalendar()
    return y, w


def week_start(ms: int) -> int:
    """Sunday's day start, for the week containing `ms`."""
    return _start_of(week_first(_logical_date(ms)))


def month_start(ms: int) -> int:
    return _start_of(_logical_date(ms).replace(day=1))


def period_window(period: str, ms: int) -> tuple[int, int]:
    if period == "week":
        return week_start(ms), ms
    if period == "month":
        return month_start(ms), ms
    return day_start(ms), ms


def iso_week(ms: int) -> int:
    return week_key(_logical_date(ms))[1]
