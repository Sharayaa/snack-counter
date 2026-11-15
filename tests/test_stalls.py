"""Rule: a box never sits empty quietly, and nobody is timed out while they are away."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from snack_counter import FixedClock, RefillStatus, SnackService
from snack_counter.setup_data import BENGALURU, OSLO

from conftest import make_volunteers

FRIDAY_1630_OSLO = datetime(2026, 11, 20, 15, 30, tzinfo=timezone.utc)


@pytest.fixture
def friday(chat, hr):
    clock = FixedClock(FRIDAY_1630_OSLO)
    return SnackService([OSLO, BENGALURU], make_volunteers(), chat, hr, clock), clock


def test_offer_does_not_run_out_over_the_weekend(friday):
    service, clock = friday
    refill = service.report_empty("OSL", "o2")
    first = refill.offered_to

    clock.advance(days=2, hours=16)          # Monday 08:30: nobody has had a working minute to answer
    service.check_timeouts()
    assert refill.offered_to == first and not refill.passed

    clock.advance(hours=2, minutes=30)       # Monday 11:00: two office hours have now passed
    service.check_timeouts()
    assert refill.offered_to != first and first in refill.passed


def test_friday_commitment_lasts_until_monday(friday):
    service, clock = friday
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")

    clock.advance(days=2)                    # Sunday afternoon
    service.check_timeouts()
    assert refill.status == RefillStatus.COMMITTED and refill.buyer == "o1"

    clock.advance(days=1, hours=1)           # Monday 17:30, a full working day after committing
    service.check_timeouts()
    assert refill.status == RefillStatus.OPEN and refill.buyer is None


def test_buyer_is_told_the_deadline_in_local_time(service, chat):
    refill = service.report_empty("BLR", "b1")       # Monday 13:30 in Bengaluru
    service.commit(refill.id, "b1")
    assert any("by Tue 13:30" in m for m in chat.messages_to("b1"))


def test_when_everyone_passed_the_next_working_day_starts_over(service, clock):
    refill = service.report_empty("OSL", "o3")
    for _ in range(3):
        service.pass_offer(refill.id, refill.offered_to)
    assert refill.offered_to is None

    clock.advance(hours=4)                   # still Monday: don't nag the same people again
    service.check_timeouts()
    assert refill.offered_to is None

    clock.advance(hours=20)                  # Tuesday 09:00
    service.check_timeouts()
    assert refill.offered_to is not None and not refill.passed


def test_nobody_is_asked_again_on_a_weekend(friday, chat):
    service, clock = friday
    refill = service.report_empty("OSL", "o2")
    for _ in range(3):
        service.pass_offer(refill.id, refill.offered_to)
    sent = len(chat.messages)

    clock.advance(days=1)                    # Saturday
    service.check_timeouts()
    assert refill.offered_to is None and len(chat.messages) == sent

    clock.advance(days=2)                    # Monday
    service.check_timeouts()
    assert refill.offered_to is not None


def test_box_empty_for_two_working_days_goes_to_the_admin_once(service, clock, chat):
    refill = service.report_empty("OSL", "o3")       # Monday 09:00
    clock.advance(days=1, hours=7)                   # Tuesday 16:00: not yet two working days
    service.check_timeouts()
    assert not chat.messages_to("admin-osl")

    clock.advance(hours=2)                           # Tuesday 18:00: Monday and Tuesday have both gone by
    service.check_timeouts()
    service.check_timeouts()
    alerts = [m for m in chat.messages_to("admin-osl") if "empty since Mon 09:00" in m]
    assert len(alerts) == 1 and refill.escalated


def test_restocked_box_is_never_escalated(service, clock, chat):
    refill = service.report_empty("OSL", "o3")
    service.commit(refill.id, "o1")
    service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                            receipt_image="r.jpg", items=[])
    clock.advance(days=5)
    service.check_timeouts()
    assert not chat.messages_to("admin-osl")


def test_claim_stuck_at_hr_past_ten_days_is_chased_by_the_admin(service, clock, chat):
    refill = service.report_empty("OSL", "o3")
    service.commit(refill.id, "o1")
    service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                            receipt_image="r.jpg", items=[])
    clock.advance(days=10)
    service.sync_claims()
    assert not chat.messages_to("admin-osl")         # ten days is still within HR's promise

    clock.advance(days=1)
    service.sync_claims()
    service.sync_claims()
    chases = [m for m in chat.messages_to("admin-osl") if "more than 10 days" in m]
    assert len(chases) == 1 and "Ingrid" in chases[0]
