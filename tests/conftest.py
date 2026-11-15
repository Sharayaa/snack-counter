from datetime import date, datetime, timedelta, timezone

import pytest

from snack_counter import FakeChat, FakeHR, FixedClock, SnackService, Volunteer
from snack_counter.setup_data import BENGALURU, OSLO

# Monday 16 November 2026, 08:00 UTC = 09:00 in Oslo, 13:30 in Bengaluru.
START = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
DAYS = [date(2026, 11, 16) + timedelta(days=i) for i in range(45)]   # into December


def at(office, days=DAYS):
    """A schedule that puts someone at `office` on every given day."""
    return {d: office for d in days}


def make_volunteers():
    return [
        Volunteer("o1", "Ingrid", "OSL", "NOK", at("OSL")),
        Volunteer("o2", "Lars", "OSL", "NOK", at("OSL")),
        Volunteer("o3", "Nora", "OSL", "NOK", at("OSL")),
        Volunteer("o4", "Erik", "OSL", "NOK", at(None)),           # working from home throughout
        Volunteer("b1", "Asha", "BLR", "INR", at("BLR")),
        Volunteer("b2", "Ravi", "BLR", "INR", at("BLR")),
        Volunteer("b3", "Meera", "BLR", "INR", at(None)),          # on holiday throughout
        Volunteer("v1", "Sofie", "OSL", "NOK", at("BLR")),         # Oslo employee visiting Bengaluru
    ]


@pytest.fixture
def clock():
    return FixedClock(START)


@pytest.fixture
def chat():
    return FakeChat()


@pytest.fixture
def hr():
    return FakeHR()


@pytest.fixture
def service(clock, chat, hr):
    return SnackService([OSLO, BENGALURU], make_volunteers(), chat, hr, clock)
