"""Rule: budgets are checked before anyone buys, and totals are right in both currencies."""

from decimal import Decimal

import pytest

from snack_counter import RefillError, RefillStatus

NOV = (2026, 11)


def buy(service, office, person, amount, currency, reporter=None):
    refill = service.report_empty(office, reporter or person)
    assert service.commit(refill.id, person)
    service.record_purchase(refill.id, person, amount=Decimal(amount), currency=currency,
                            receipt_image="receipt.jpg", items=["snacks"])
    return refill


def test_spend_cap_is_the_usual_maximum(service):
    refill = service.report_empty("OSL", "o1")
    service.commit(refill.id, "o1")
    assert refill.spend_cap == Decimal("1200")


def test_committing_reserves_money_so_it_cannot_be_spent_twice(service):
    refill = service.report_empty("BLR", "b1")
    service.commit(refill.id, "b1")
    assert service.budget.remaining("BLR", NOV) == Decimal("12000")


def test_receipt_replaces_the_reservation_with_the_real_amount(service):
    buy(service, "OSL", "o1", "750", "NOK")
    assert service.budget.spent("OSL", NOV) == Decimal("750")
    assert service.budget.reserved("OSL", NOV) == Decimal("0")
    assert service.budget.remaining("OSL", NOV) == Decimal("5250")


def test_cap_shrinks_to_what_is_left_near_the_end_of_the_month(service):
    for person in ("o1", "o2", "o3", "o1"):
        buy(service, "OSL", person, "1200", "NOK")
    refill = service.report_empty("OSL", "o2")       # 6000 - 4800 = 1200 left
    service.commit(refill.id, "o2")
    assert refill.spend_cap == Decimal("1200")
    service.record_purchase(refill.id, "o2", amount=Decimal("900"), currency="NOK",
                            receipt_image="r.jpg", items=["fruit"])
    nxt = service.report_empty("OSL", "o3")           # 300 left, exactly the minimum
    service.commit(nxt.id, "o3")
    assert nxt.spend_cap == Decimal("300")


def test_refill_is_blocked_when_too_little_budget_is_left(service, chat):
    for person in ("o1", "o2", "o3", "o1", "o2"):
        buy(service, "OSL", person, "1150", "NOK")   # 5750 spent, 250 left (< 300 minimum)
    refill = service.report_empty("OSL", "o3")
    assert refill.status == RefillStatus.BLOCKED
    assert refill.offered_to is None
    assert any("budget is used up" in m for m in chat.messages_to("admin-osl"))
    assert service.commit(refill.id, "o3") is False


def test_overspend_is_still_reimbursed_but_flagged(service, hr, chat):
    refill = buy(service, "OSL", "o1", "1350", "NOK")    # cap was 1200
    assert refill.over_cap is True
    assert refill.status == RefillStatus.CLAIM_SUBMITTED
    assert hr.claims[refill.claim_id].amount == Decimal("1350")
    assert any("above the agreed cap" in m for m in chat.messages_to("admin-osl"))


def test_budgets_are_kept_in_each_office_currency(service):
    buy(service, "OSL", "o1", "1000", "NOK")
    buy(service, "BLR", "b1", "2500", "INR")
    assert service.budget.spent("OSL", NOV) == Decimal("1000")
    assert service.budget.spent("BLR", NOV) == Decimal("2500")
    assert service.budget.remaining("OSL", NOV) == Decimal("5000")
    assert service.budget.remaining("BLR", NOV) == Decimal("12500")


def test_monthly_report_totals_both_currencies(service):
    buy(service, "OSL", "o1", "1000", "NOK")
    buy(service, "OSL", "o2", "600", "NOK")
    buy(service, "BLR", "b1", "2500", "INR")
    report = service.monthly_report(2026, 11, {"NOK": Decimal("1"), "INR": Decimal("0.12")})
    assert report["offices"]["OSL"]["spent"] == Decimal("1600")
    assert report["offices"]["BLR"]["spent"] == Decimal("2500")
    assert report["offices"]["OSL"]["refills"] == 2
    assert report["total_nok"] == Decimal("1900.00")         # 1600 + 2500 x 0.12


def test_receipt_in_the_wrong_currency_is_refused(service):
    refill = service.report_empty("BLR", "b1")
    service.commit(refill.id, "b1")
    with pytest.raises(RefillError, match="must be in INR"):
        service.record_purchase(refill.id, "b1", amount=Decimal("100"), currency="NOK",
                                receipt_image="r.jpg", items=[])
    assert service.budget.spent("BLR", NOV) == Decimal("0")


def test_visitor_is_charged_to_the_office_they_refilled(service, hr):
    """Sofie (paid in NOK) buys in Bengaluru: INR claim, Bengaluru budget."""
    for person in ("b1", "b2"):
        buy(service, "BLR", person, "1000", "INR")
    refill = buy(service, "BLR", "v1", "1500", "INR")
    claim = hr.claims[refill.claim_id]
    assert claim.employee_id == "v1" and claim.currency == "INR" and claim.amount == Decimal("1500")
    assert service.budget.spent("BLR", NOV) == Decimal("3500")
    assert service.budget.spent("OSL", NOV) == Decimal("0")


def test_blocked_refill_reopens_when_the_new_month_brings_budget(service, clock):
    for person in ("o1", "o2", "o3", "o1", "o2"):
        buy(service, "OSL", person, "1150", "NOK")   # 250 NOK left in November
    refill = service.report_empty("OSL", "o3")
    assert refill.status == RefillStatus.BLOCKED

    clock.advance(days=15)                           # Tuesday 1 December
    service.check_timeouts()
    assert refill.status == RefillStatus.OPEN
    assert refill.offered_to is not None
    assert service.commit(refill.id, refill.offered_to)
    assert refill.budget_month == (2026, 12)
    assert service.budget.spent("OSL", NOV) == Decimal("5750")   # November is untouched


def test_report_shows_who_refilled_and_what_is_still_owed(service, hr, clock):
    paid = buy(service, "OSL", "o1", "1000", "NOK")
    buy(service, "OSL", "o2", "600", "NOK")
    clock.advance(days=4)
    hr.approve(paid.claim_id)
    service.sync_claims()

    osl = service.monthly_report(2026, 11, {"NOK": Decimal("1"), "INR": Decimal("0.12")})["offices"]["OSL"]
    assert osl["refills_by_person"] == {"o1": 1, "o2": 1}
    assert osl["awaiting_reimbursement"] == {"claims": 1, "amount": Decimal("600")}
    assert osl["avg_days_to_reimburse"] == 4.0


def test_report_shows_what_is_bought_and_what_is_left_uneaten(service):
    for person, items, left in (("o1", ["bananas", "liquorice"], []),
                                ("o2", ["bananas", "nuts"], ["liquorice"]),
                                ("o3", ["bananas"], ["liquorice"])):
        refill = service.report_empty("OSL", person)
        service.commit(refill.id, person)
        service.record_purchase(refill.id, person, amount=Decimal("400"), currency="NOK",
                                receipt_image="r.jpg", items=items, left_over=left)
    osl = service.monthly_report(2026, 11, {"NOK": Decimal("1"), "INR": Decimal("0.12")})["offices"]["OSL"]
    assert osl["items_bought"] == {"bananas": 3, "liquorice": 1, "nuts": 1}
    assert osl["items_left_over"] == {"liquorice": 2}
