"""Rule: deadlines only count office hours, in the office's own time zone."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from snack_counter.working_hours import add_working_time

OSLO = "Europe/Oslo"
BLR = "Asia/Kolkata"


def oslo(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=ZoneInfo(OSLO))   # 16 Nov 2026 is a Monday


def test_same_day():
    assert add_working_time(oslo(16, 9), timedelta(hours=2), OSLO) == oslo(16, 11)


def test_carries_over_to_the_next_morning():
    assert add_working_time(oslo(16, 16), timedelta(hours=2), OSLO) == oslo(17, 10)


def test_skips_the_weekend():
    assert add_working_time(oslo(20, 16, 30), timedelta(hours=2), OSLO) == oslo(23, 10, 30)


def test_starts_counting_when_the_office_opens():
    assert add_working_time(oslo(16, 6), timedelta(hours=2), OSLO) == oslo(16, 11)
    assert add_working_time(oslo(21, 12), timedelta(hours=2), OSLO) == oslo(23, 11)   # asked on a Saturday


def test_one_working_day_lands_at_the_same_time_the_next_working_day():
    assert add_working_time(oslo(16, 11), timedelta(hours=8), OSLO) == oslo(17, 11)
    assert add_working_time(oslo(20, 15), timedelta(hours=8), OSLO) == oslo(23, 15)   # Friday to Monday


def test_each_office_uses_its_own_clock():
    # 12:00 in Oslo is 16:30 in Bengaluru: only half an hour of the office day is left there.
    due = add_working_time(oslo(16, 12), timedelta(hours=2), BLR)
    assert due == datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo(BLR))
