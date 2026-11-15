"""Rule: a refill nobody completes is handed to someone else."""

from decimal import Decimal

import pytest

from snack_counter import RefillError, RefillStatus


def test_refill_nobody_completes_is_handed_to_someone_else(service, clock, chat):
    refill = service.report_empty("OSL", "o3")
    service.commit(refill.id, "o1")

    clock.advance(hours=25)          # Tuesday 10:00, past the one-working-day window
    service.check_timeouts()

    assert refill.status == RefillStatus.OPEN
    assert refill.buyer is None
    assert refill.offered_to not in (None, "o1")
    assert "o1" in refill.passed
    assert any("handed to someone else" in m for m in chat.messages_to("o1"))


def test_handover_gives_the_reserved_money_back(service, clock):
    month = (2026, 11)
    refill = service.report_empty("OSL", "o3")
    service.commit(refill.id, "o1")
    assert service.budget.remaining("OSL", month) == Decimal("4800")

    clock.advance(hours=25)
    service.check_timeouts()
    assert service.budget.remaining("OSL", month) == Decimal("6000")


def test_unanswered_offer_moves_to_the_next_volunteer(service, clock):
    refill = service.report_empty("OSL", "o3")
    first = refill.offered_to
    clock.advance(hours=3)           # past the 2-office-hour offer window
    service.check_timeouts()
    assert refill.offered_to is not None
    assert refill.offered_to != first


def test_passing_asks_the_next_person_immediately(service):
    refill = service.report_empty("OSL", "o3")
    first = refill.offered_to
    service.pass_offer(refill.id, first)
    assert refill.offered_to not in (None, first)


def test_person_who_dropped_it_can_still_commit_if_it_is_open(service, clock):
    """Being skipped by the rota doesn't stop someone from helping later."""
    refill = service.report_empty("OSL", "o3")
    service.commit(refill.id, "o1")
    clock.advance(hours=25)
    service.check_timeouts()
    assert service.commit(refill.id, "o1") is True


def test_when_everyone_has_passed_the_channel_is_asked(service, chat):
    refill = service.report_empty("OSL", "o3")
    for _ in range(3):              # o1, o2, o3 are in the office
        service.pass_offer(refill.id, refill.offered_to)
    assert refill.offered_to is None
    assert any("Anyone in today" in m for m in chat.messages_to("#snacks-OSL"))


# ---- bought, but the receipt is not uploaded yet -------------------------------
#
# Timeline used below: the buyer commits on Monday 09:00 Oslo time, exactly when the
# office opens. One working day is eight office hours, so the receipt is due Monday
# 17:00 and the reminder goes out two office hours earlier, at Monday 15:00.

NOV = (2026, 11)


def committed(service):
    refill = service.report_empty("OSL", "o3")
    service.commit(refill.id, "o1")
    return refill


def test_buyer_is_reminded_once_before_the_deadline(service, clock, chat):
    refill = committed(service)
    clock.advance(hours=5)                       # Monday 14:00
    service.check_timeouts()
    assert not any("Reminder" in m for m in chat.messages_to("o1"))

    clock.advance(hours=2)                       # Monday 16:00
    service.check_timeouts()
    service.check_timeouts()
    reminders = [m for m in chat.messages_to("o1") if "Reminder" in m]
    assert len(reminders) == 1
    assert "due by Mon 17:00" in reminders[0] and "reply 'bought'" in reminders[0]
    assert refill.status == RefillStatus.COMMITTED


def test_buyer_who_says_nothing_after_the_reminder_is_handed_over(service, clock, chat):
    """Normal hand-over: no receipt and no 'bought', so we treat it as not bought."""
    refill = committed(service)
    clock.advance(hours=7)                       # Monday 16:00: reminded
    service.check_timeouts()
    clock.advance(hours=18)                      # Tuesday 10:00: past the deadline
    service.check_timeouts()

    assert refill.status == RefillStatus.OPEN and refill.buyer is None
    assert refill.offered_to not in (None, "o1")
    assert service.budget.remaining("OSL", NOV) == Decimal("6000")
    assert not chat.messages_to("admin-osl")


def test_buyer_who_has_bought_keeps_the_refill_past_the_deadline(service, clock):
    refill = committed(service)
    service.confirm_bought(refill.id, "o1")
    assert refill.status == RefillStatus.RECEIPT_PENDING

    clock.advance(days=3)                        # Thursday, long past any deadline
    service.check_timeouts()

    assert refill.status == RefillStatus.RECEIPT_PENDING
    assert refill.buyer == "o1"                              # still theirs
    assert refill.offered_to is None and not refill.passed   # nobody else was asked
    assert service.budget.remaining("OSL", NOV) == Decimal("4800")   # money still set aside


def test_nobody_else_can_buy_while_the_receipt_is_pending(service, chat):
    refill = committed(service)
    service.confirm_bought(refill.id, "o1")

    assert service.commit(refill.id, "o2") is False
    assert any("No need to buy" in m for m in chat.messages_to("o2"))
    assert service.report_empty("OSL", "o3") is refill       # no second refill is opened


def test_late_receipt_tells_the_buyer_and_the_admin_once(service, clock, chat):
    refill = committed(service)
    service.confirm_bought(refill.id, "o1")                  # Monday 09:00, receipt due Monday 17:00
    clock.advance(hours=7)                                   # Monday 16:00
    service.check_timeouts()
    assert not chat.messages_to("admin-osl")

    clock.advance(hours=2)                                   # Monday 18:00
    service.check_timeouts()
    service.check_timeouts()
    to_buyer = [m for m in chat.messages_to("o1") if "overdue" in m]
    to_admin = [m for m in chat.messages_to("admin-osl") if "hasn't uploaded the receipt" in m]
    assert len(to_buyer) == 1
    assert len(to_admin) == 1 and "Ingrid" in to_admin[0]
    assert refill.buyer == "o1"


def test_receipt_uploaded_late_is_still_claimed(service, clock, hr):
    refill = committed(service)
    service.confirm_bought(refill.id, "o1")
    clock.advance(days=3)
    service.check_timeouts()                                 # receipt is overdue by now

    service.record_purchase(refill.id, "o1", amount=Decimal("640"), currency="NOK",
                            receipt_image="r.jpg", items=["fruit"])
    assert refill.status == RefillStatus.CLAIM_SUBMITTED
    assert hr.claims[refill.claim_id].amount == Decimal("640")
    assert service.budget.spent("OSL", NOV) == Decimal("640")


def test_saying_bought_gives_a_fresh_day_and_a_new_reminder(service, clock, chat):
    refill = committed(service)
    clock.advance(hours=7)                       # Monday 16:00, one office hour before closing
    service.confirm_bought(refill.id, "o1")
    assert any("by Tue 16:00" in m for m in chat.messages_to("o1"))

    clock.advance(hours=23)                      # Tuesday 15:00, an hour before the new deadline
    service.check_timeouts()
    assert any("please upload the receipt" in m for m in chat.messages_to("o1"))
    assert refill.status == RefillStatus.RECEIPT_PENDING


def test_only_the_buyer_can_say_they_have_bought(service):
    refill = committed(service)
    with pytest.raises(RefillError):
        service.confirm_bought(refill.id, "o2")
    assert refill.status == RefillStatus.COMMITTED


def test_someone_waiting_to_upload_a_receipt_is_not_asked_to_buy_again(service):
    for _ in range(2):                           # Ingrid ends up with two refills she is owed money for
        refill = committed(service)
        service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                                receipt_image="r.jpg", items=[])
    blr = service.report_empty("BLR", "b1")
    service.commit(blr.id, "b1")
    service.confirm_bought(blr.id, "b1")
    recent, last, unpaid, busy = service._recent_refill_stats()
    assert "b1" in busy and unpaid["b1"] == 1
