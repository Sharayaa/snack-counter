"""Rule: a refill nobody completes is handed to someone else."""

from decimal import Decimal

from snack_counter import RefillStatus


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
