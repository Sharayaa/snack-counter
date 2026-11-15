"""Rule: the person asked is in the office today, and the work is shared fairly."""

from decimal import Decimal


def test_only_people_in_the_office_today_are_asked(service):
    refill = service.report_empty("OSL", "o2")
    assert refill.offered_to in {"o1", "o2", "o3"}     # o4 is working from home


def test_visitor_from_the_other_office_can_be_asked(service):
    for person in ("b1", "b2"):
        refill = service.report_empty("BLR", person)
        service.commit(refill.id, person)
        service.record_purchase(refill.id, person, amount=Decimal("1000"), currency="INR",
                                receipt_image="r.jpg", items=["chips"])
    refill = service.report_empty("BLR", "b1")
    assert refill.offered_to == "v1"                   # Sofie is visiting from Oslo


def test_rota_prefers_whoever_has_refilled_least(service, clock):
    first = service.report_empty("OSL", "o2")
    assert first.offered_to == "o1"
    service.commit(first.id, "o1")
    service.record_purchase(first.id, "o1", amount=Decimal("800"), currency="NOK",
                            receipt_image="r.jpg", items=["fruit"])

    clock.advance(days=1)
    second = service.report_empty("OSL", "o3")
    assert second.offered_to != "o1"


def test_people_waiting_on_two_reimbursements_are_not_asked(service, clock):
    for _ in range(2):
        refill = service.report_empty("OSL", "o2")
        service.commit(refill.id, "o1")          # o1 volunteers directly both times
        service.record_purchase(refill.id, "o1", amount=Decimal("500"), currency="NOK",
                                receipt_image="r.jpg", items=["nuts"])
        clock.advance(hours=1)
    # o1 now has 2 unpaid claims and must not be asked again until HR pays.
    refill = service.report_empty("OSL", "o2")
    asked = []
    while refill.offered_to is not None:
        asked.append(refill.offered_to)
        service.pass_offer(refill.id, refill.offered_to)
    assert "o1" not in asked
    assert set(asked) == {"o2", "o3"}
