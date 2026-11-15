"""Rule: one empty box leads to exactly one buyer, never two."""

import threading

from snack_counter import RefillStatus


def test_two_people_cannot_both_commit_to_the_same_refill(service):
    refill = service.report_empty("OSL", "o2")
    assert service.commit(refill.id, "o1") is True
    assert service.commit(refill.id, "o3") is False
    assert refill.buyer == "o1"
    assert refill.status == RefillStatus.COMMITTED


def test_simultaneous_commits_only_one_wins(service):
    refill = service.report_empty("OSL", "o2")
    results = {}
    start = threading.Barrier(3)

    def try_commit(person):
        start.wait()
        results[person] = service.commit(refill.id, person)

    threads = [threading.Thread(target=try_commit, args=(p,)) for p in ("o1", "o2", "o3")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results.values()) == 1
    assert refill.buyer in results and results[refill.buyer] is True


def test_second_empty_report_joins_the_open_refill(service, chat):
    first = service.report_empty("OSL", "o2")
    second = service.report_empty("OSL", "o3")
    assert first is second
    assert len([r for r in service.refills.values() if r.office == "OSL"]) == 1
    assert any("already open" in m for m in chat.messages_to("o3"))


def test_loser_is_told_not_to_buy(service, chat):
    refill = service.report_empty("OSL", "o2")
    service.commit(refill.id, "o1")
    service.commit(refill.id, "o3")
    assert any("No need to buy" in m for m in chat.messages_to("o3"))


def test_offices_are_independent(service):
    osl = service.report_empty("OSL", "o1")
    blr = service.report_empty("BLR", "b1")
    assert osl.id != blr.id
    assert service.commit(osl.id, "o1") and service.commit(blr.id, "b1")
