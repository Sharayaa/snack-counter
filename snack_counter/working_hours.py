"""Deadlines that only count office hours.

Volunteers answer chat and shop on working days, so a deadline that keeps
ticking overnight or over the weekend would time people out while they are
asleep. All deadlines in the service are therefore measured in working time:
Monday to Friday, 09:00 to 17:00 in the office's own time zone.

"8 working hours" is one full working day: a commitment made on Monday 11:00
is due Tuesday 11:00, and one made Friday 15:00 is due Monday 15:00.

Public holidays are not known here; see DESIGN.md.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

OPENS = time(9, 0)
CLOSES = time(17, 0)
HOURS_PER_DAY = 8


def is_working_day(day: date) -> bool:
    return day.weekday() < 5  # Monday is 0, Saturday is 5


def add_working_time(start: datetime, duration: timedelta, tz: str) -> datetime:
    """The moment `duration` of office time has passed since `start`."""
    local = start.astimezone(ZoneInfo(tz))
    left = duration
    while True:
        opens = datetime.combine(local.date(), OPENS, local.tzinfo)
        closes = datetime.combine(local.date(), CLOSES, local.tzinfo)
        if not is_working_day(local.date()) or local >= closes:
            local = opens + timedelta(days=1)       # jump to the next morning
            continue
        if local < opens:
            local = opens
        if left <= closes - local:
            return (local + left).astimezone(timezone.utc)
        left -= closes - local                      # use up today, carry the rest over
        local = opens + timedelta(days=1)
