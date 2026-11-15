"""Rule: a refill moves all the way from "empty" to "reimbursed", and stalls are handled."""

from decimal import Decimal

import pytest

from snack_counter import RefillError, RefillStatus


def test_full_journey_from_empty_to_reimbursed(service, hr, chat, clock):
    refill = service.report_empty("OSL", "o2")
    assert refill.status == RefillStatus.OPEN and refill.offered_to == "o1"

    assert service.commit(refill.id, "o1")
    clock.advance(hours=3)
    service.record_purchase(refill.id, "o1", amount=Decimal("820"), currency="NOK",
                            receipt_image="receipts/r1.jpg", items=["bananas", "chocolate"])
    assert refill.status == RefillStatus.CLAIM_SUBMITTED

    claim = hr.claims[refill.claim_id]
    assert (claim.employee_id, claim.amount, claim.currency) == ("o1", Decimal("820"), "NOK")
    assert claim.receipt_image == "receipts/r1.jpg"

    clock.advance(days=4)
    hr.approve(refill.claim_id)
    service.sync_claims()
    assert refill.status == RefillStatus.REIMBURSED
    assert any("approved" in m for m in chat.messages_to("o1"))


def test_only_the_buyer_can_record_the_purchase(service):
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")
    with pytest.raises(RefillError):
        service.record_purchase(refill.id, "o2", amount=Decimal("500"), currency="NOK",
                                receipt_image="r.jpg", items=[])


def test_a_receipt_is_required(service):
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")
    with pytest.raises(RefillError):
        service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                                receipt_image="", items=[])


def test_new_refill_can_open_once_the_box_is_restocked(service):
    first = service.report_empty("OSL", "o2")
    service.commit(first.id, "o1")
    service.record_purchase(first.id, "o1", amount=Decimal("500"), currency="NOK",
                            receipt_image="r.jpg", items=[])
    second = service.report_empty("OSL", "o2")
    assert second.id != first.id


def test_claim_is_retried_when_hr_is_down(service, hr):
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")
    hr.available = False
    service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                            receipt_image="r.jpg", items=[])
    assert refill.status == RefillStatus.PURCHASED and refill.claim_id is None

    hr.available = True
    service.sync_claims()
    assert refill.status == RefillStatus.CLAIM_SUBMITTED and refill.claim_id


def test_rejected_claim_reaches_the_buyer_and_the_admin(service, hr, chat):
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")
    service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                            receipt_image="r.jpg", items=[])
    hr.reject(refill.claim_id, "receipt unreadable")
    service.sync_claims()
    assert refill.status == RefillStatus.CLAIM_REJECTED
    assert any("rejected" in m for m in chat.messages_to("o1"))
    assert any("rejected" in m for m in chat.messages_to("admin-osl"))
