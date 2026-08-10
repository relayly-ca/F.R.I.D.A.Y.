"""Temporal resolution. Spec section 7 and 10.

"Always inject current date/time. Local models are hopeless at temporal reasoning
otherwise." "Resolve dates in code, never in the prompt."

The model receives resolved ISO date ranges and never performs date arithmetic.
This module owns every conversion between a phrase and a date range.

Test at the boundaries: 23:50, Sunday, month end, DST change, non-UTC timezone.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from friday.config import get


def _tz() -> ZoneInfo:
    """The configured timezone. Falls back to UTC."""
    try:
        cfg = get()
        return ZoneInfo(cfg.friday.general.timezone)
    except Exception:
        return ZoneInfo("UTC")


def now() -> datetime:
    """Current time in the configured timezone."""
    return datetime.now(_tz())


def today() -> date:
    """Today in the configured timezone."""
    return now().date()


def _week_range(ref: date, offset: int = 0) -> tuple[date, date]:
    """A week, Monday to Sunday. offset=-1 is last week, 0 is this week."""
    monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _month_range(ref: date, offset: int = 0) -> tuple[date, date]:
    """A month. offset=-1 is last month."""
    y, m = ref.year, ref.year * 12 + ref.month - 1 + offset
    y, m = divmod(m, 12)
    if m == 0:
        m = 12
        y -= 1
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(y, m + 1, 1) - timedelta(days=1)
    return start, end


_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _next_weekday(ref: date, target: int) -> date:
    """Next occurrence of target weekday (today if today is that day)."""
    days_ahead = target - ref.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return ref + timedelta(days=days_ahead)


def resolve(phrase: str, ref: datetime | None = None) -> tuple[datetime, datetime] | None:
    """Resolve a temporal phrase to a (start, end) datetime range.

    Returns None if the phrase is not recognised. The caller decides what to do
    with None — it may pass the phrase through to retrieval unchanged.

    All ranges are [start, end) — start inclusive, end exclusive — and both are
    timezone-aware in the configured timezone.

    Recognised phrases:
        today, yesterday, tomorrow
        this week, last week, next week
        this month, last month, next month
        next <weekday> (e.g. "next tuesday")
        last <weekday>
        before <date>, after <date>, on <date>
        in the last N days / N hours
    """
    ref = ref or now()
    p = phrase.strip().lower()
    tz = _tz()

    def _dt(d: date, t_start: time = time(0, 0)) -> datetime:
        return datetime.combine(d, t_start, tzinfo=tz)

    # Simple keywords
    if p == "today":
        return _dt(today()), _dt(today() + timedelta(days=1))
    if p == "yesterday":
        y = today() - timedelta(days=1)
        return _dt(y), _dt(today())
    if p == "tomorrow":
        t = today() + timedelta(days=1)
        return _dt(t), _dt(t + timedelta(days=1))

    # Week
    if p in ("this week", "this week's"):
        s, e = _week_range(today())
        return _dt(s), _dt(e + timedelta(days=1))
    if p in ("last week", "last week's"):
        s, e = _week_range(today(), offset=-1)
        return _dt(s), _dt(e + timedelta(days=1))
    if p in ("next week", "next week's"):
        s, e = _week_range(today(), offset=1)
        return _dt(s), _dt(e + timedelta(days=1))

    # Month
    if p in ("this month",):
        s, e = _month_range(today())
        return _dt(s), _dt(e + timedelta(days=1))
    if p in ("last month",):
        s, e = _month_range(today(), offset=-1)
        return _dt(s), _dt(e + timedelta(days=1))
    if p in ("next month",):
        s, e = _month_range(today(), offset=1)
        return _dt(s), _dt(e + timedelta(days=1))

    # Next/last weekday
    m = re.match(r"^(?:next|this|coming)\s+(\w+)$", p)
    if m and m.group(1) in _WEEKDAYS:
        target = _next_weekday(today(), _WEEKDAYS[m.group(1)])
        return _dt(target), _dt(target + timedelta(days=1))

    m = re.match(r"^last\s+(\w+)$", p)
    if m and m.group(1) in _WEEKDAYS:
        target_dow = _WEEKDAYS[m.group(1)]
        days_back = (today().weekday() - target_dow) % 7
        if days_back == 0:
            days_back = 7
        target = today() - timedelta(days=days_back)
        return _dt(target), _dt(target + timedelta(days=1))

    # In the last N days/hours
    m = re.match(r"^(?:in the\s+)?last\s+(\d+)\s+(days?|hours?|weeks?)$", p)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if unit == "day":
            start = ref - timedelta(days=n)
        elif unit == "hour":
            start = ref - timedelta(hours=n)
        elif unit == "week":
            start = ref - timedelta(weeks=n)
        else:
            return None
        return start, ref

    # On <date> (ISO or YYYY-MM-DD)
    m = re.match(r"^(?:on\s+)?(\d{4}-\d{2}-\d{2})$", p)
    if m:
        d = date.fromisoformat(m.group(1))
        return _dt(d), _dt(d + timedelta(days=1))

    # Before/after <date>
    m = re.match(r"^(?:before|until)\s+(\d{4}-\d{2}-\d{2})$", p)
    if m:
        d = date.fromisoformat(m.group(1))
        return _dt(date(2000, 1, 1)), _dt(d)

    m = re.match(r"^(?:after|since)\s+(\d{4}-\d{2}-\d{2})$", p)
    if m:
        d = date.fromisoformat(m.group(1))
        return _dt(d), datetime.combine(date(2100, 1, 1), time(0, 0), tzinfo=tz)

    return None


def inject_context() -> str:
    """The always-injected temporal context. Spec section 7.

    Returns a string with the current date, time, day of week, and today's date
    range — injected before retrieval, always, on every turn.
    """
    n = now()
    t = today()
    return (
        f"Current date: {t.isoformat()} ({n.strftime('%A')})\n"
        f"Current time: {n.strftime('%H:%M %Z')}\n"
        f"Week of: {t - timedelta(days=t.weekday())}"
    )
