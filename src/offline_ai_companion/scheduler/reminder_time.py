"""Strict local calendar parsing; no model or network access."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MONTHS = {name: i for i, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}


def local_timezone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("REMINDER_TIMEZONE must name an installed IANA timezone; install tzdata on Windows.") from exc


def parse_reminder_time(expression: str, now: datetime, zone) -> datetime:
    """Return UTC instant; refuse past, underspecified and DST-ambiguous times.

    A bare clock time means today. A month/day without year means this year.
    Neither form automatically rolls into tomorrow/next year.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The reminder clock must include a timezone.")
    text = expression.strip().lower().rstrip(".!?")
    relative = re.fullmatch(r"in (\d+) (minutes?|hours?)", text)
    if relative:
        amount = int(relative[1])
        if not 1 <= amount <= 525600:
            raise ValueError("Use a positive reminder delay of at most 525600 minutes or hours.")
        try:
            return now.astimezone(timezone.utc) + timedelta(**{
                "minutes" if relative[2].startswith("minute") else "hours": amount})
        except OverflowError as exc:
            raise ValueError("That reminder delay is out of range.") from exc
    match = re.fullmatch(r"(?:(.+?)\s+)?at (\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
    if not match:
        raise ValueError("Specify in N minutes/hours, or a date and time such as tomorrow at 6 PM or on 2026-10-15 at 10 AM.")
    day_text, hour_text, minute_text, period = match.groups()
    hour, minute = int(hour_text), int(minute_text or "0")
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise ValueError("Use a valid 12-hour time with AM or PM.")
    local_now = now.astimezone(zone)
    day_text = (day_text or "today").removeprefix("on ")
    if day_text in {"today", "tomorrow"}:
        day = local_now.date() + timedelta(days=int(day_text == "tomorrow"))
    else:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_text):
                day = datetime.strptime(day_text, "%Y-%m-%d").date()
            else:
                date_match = re.fullmatch(r"([a-z]+) (\d{1,2})(?:,? (\d{4}))?", day_text)
                if not date_match or date_match[1] not in MONTHS:
                    raise ValueError
                day = datetime(int(date_match[3] or local_now.year), MONTHS[date_match[1]],
                               int(date_match[2])).date()
        except ValueError as exc:
            raise ValueError("Use a valid unambiguous date: YYYY-MM-DD or full month name and day, optionally year.") from exc
    wall = datetime.combine(day, datetime.min.time()).replace(
        hour=hour % 12 + (12 if period == "pm" else 0), minute=minute)
    candidates = set()
    for fold in (0, 1):
        instant = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.add(instant)
    if len(candidates) != 1:
        raise ValueError("That local time is nonexistent or ambiguous at a daylight-saving transition. Choose another time.")
    instant = candidates.pop()
    if instant <= now.astimezone(timezone.utc):
        raise ValueError("That time is in the past or already due. Specify a future date and time.")
    return instant
