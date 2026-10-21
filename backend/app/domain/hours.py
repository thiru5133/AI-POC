"""Weekly operating hours: {"mon": "09:00-18:00", "sun": "closed"}. A day that is not listed counts as closed."""

from datetime import datetime, time, timedelta

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def parse_range(value: str) -> tuple[time, time] | None:
    """(opens, closes) for 'HH:MM-HH:MM', None for 'closed'. Raises ValueError for anything else."""
    text = value.strip().lower()
    if text in ("", "closed"):
        return None
    try:
        start, end = (time.fromisoformat(part.strip()) for part in text.split("-"))
    except ValueError:
        raise ValueError(f"invalid hours {value!r}: use 'HH:MM-HH:MM' or 'closed'") from None
    if start >= end:
        raise ValueError(f"invalid hours {value!r}: closing time must be after opening time")
    return start, end


def validate_hours(hours: dict[str, str]) -> dict[str, str]:
    """Lower-cased day keys and checked ranges; raises ValueError so a bad profile is rejected when it is saved."""
    out: dict[str, str] = {}
    for day, value in hours.items():
        key = day.strip().lower()[:3]
        if key not in DAYS:
            raise ValueError(f"unknown day {day!r}: use mon, tue, wed, thu, fri, sat or sun")
        parse_range(value)
        out[key] = value.strip().lower()
    return out


def _range_for(hours: dict[str, str], when: datetime) -> tuple[time, time] | None:
    return parse_range(hours.get(DAYS[when.weekday()], "closed"))


def is_open(hours: dict[str, str], now: datetime) -> bool:
    window = _range_for(hours, now)
    return window is not None and window[0] <= now.time() < window[1]


def next_opening(hours: dict[str, str], now: datetime) -> str | None:
    """'today at 09:00', 'tomorrow at 09:00' or 'Monday at 09:00'; None when no day has opening hours."""
    for ahead in range(8):
        day = now + timedelta(days=ahead)
        window = _range_for(hours, day)
        if window is None or (ahead == 0 and now.time() >= window[0]):
            continue
        label = "today" if ahead == 0 else "tomorrow" if ahead == 1 else _NAMES[day.weekday()]
        return f"{label} at {window[0].strftime('%H:%M')}"
    return None


def describe(hours: dict[str, str]) -> str:
    return ", ".join(f"{_NAMES[i][:3]} {hours.get(d, 'closed')}" for i, d in enumerate(DAYS))
