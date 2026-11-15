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


def purchased_refill(service, **kwargs):
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")
    service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                            receipt_image="r.jpg", items=[], **kwargs)
    return refill


def test_hr_timeout_after_saving_the_claim_does_not_create_a_duplicate(service, hr, chat):
    """HR saves the claim but its reply is lost. The retry must find that claim, not make a second."""
    hr.lose_next_reply = True
    refill = purchased_refill(service)

    # HR has the claim, but we never heard back, so we don't know its id yet.
    assert len(hr.claims) == 1
    assert refill.status == RefillStatus.PURCHASED and refill.claim_id is None

    service.sync_claims()                                # the retry

    assert len(hr.claims) == 1                           # still exactly one claim at HR
    assert refill.status == RefillStatus.CLAIM_SUBMITTED
    assert refill.claim_id == next(iter(hr.claims))      # and we now hold the original's id
    assert len([m for m in chat.messages_to("o1") if "has been sent to HR" in m]) == 1


def test_retrying_many_times_still_leaves_one_claim(service, hr):
    hr.lose_next_reply = True
    refill = purchased_refill(service)
    for _ in range(5):
        service.sync_claims()
    assert len(hr.claims) == 1
    assert hr.claims[refill.claim_id].amount == Decimal("500")


def test_claim_carries_the_refills_reference(service, hr):
    refill = purchased_refill(service)
    assert refill.claim_reference
    assert hr.claims[refill.claim_id].reference == refill.claim_reference


def test_each_refill_gets_its_own_reference_and_its_own_claim(service, hr):
    first = purchased_refill(service)
    second = purchased_refill(service)
    assert first.claim_reference != second.claim_reference
    assert first.claim_id != second.claim_id
    assert len(hr.claims) == 2


def test_hr_returns_the_existing_claim_for_a_repeated_reference(hr):
    details = dict(employee_id="o1", amount=Decimal("500"), currency="NOK",
                   description="Snack refill", receipt_image="r.jpg", reference="ref-1")
    first = hr.create_claim(**details)
    again = hr.create_claim(**details)
    assert again == first
    assert len(hr.claims) == 1
