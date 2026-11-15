"""A walk through one week, printing what people would see in chat.

Run:  python demo.py
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from snack_counter import FakeChat, FakeHR, FixedClock, SnackService, Volunteer
from snack_counter.setup_data import BENGALURU, OSLO

start = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
days = [date(2026, 11, 16) + timedelta(days=i) for i in range(5)]
people = [
    Volunteer("o1", "Ingrid", "OSL", "NOK", {d: "OSL" for d in days}),
    Volunteer("o2", "Lars", "OSL", "NOK", {d: "OSL" for d in days}),
    Volunteer("b1", "Asha", "BLR", "INR", {d: "BLR" for d in days}),
    Volunteer("v1", "Sofie", "OSL", "NOK", {d: "BLR" for d in days}),   # visiting Bengaluru
]
clock, chat, hr = FixedClock(start), FakeChat(), FakeHR()
svc = SnackService([OSLO, BENGALURU], people, chat, hr, clock)
shown = 0


def step(title):
    global shown
    print(f"\n== {title}  [{clock.now():%a %H:%M} UTC]")
    for m in chat.messages[shown:]:
        print(f"   to {m.to:<12} {m.text}")
    shown = len(chat.messages)


r = svc.report_empty("OSL", "o2")
step("Lars reports the Oslo box is empty")

svc.report_empty("OSL", "o1")
step("Ingrid reports it too: no second refill is opened")

clock.advance(hours=3)
svc.check_timeouts()
step("Nobody answered within 2 office hours: the next person is asked")

svc.commit(r.id, "o2")
svc.commit(r.id, "o1")
step("Lars commits; Ingrid tries too and is told not to buy")

clock.advance(hours=2)
svc.record_purchase(r.id, "o2", amount=Decimal("840"), currency="NOK",
                    receipt_image="receipts/osl-1.jpg", items=["bananas", "dark chocolate"])
step("Lars buys, restocks and uploads the receipt: claim goes to HR")

b = svc.report_empty("BLR", "b1")
svc.commit(b.id, "v1")
clock.advance(hours=1)
svc.record_purchase(b.id, "v1", amount=Decimal("2200"), currency="INR",
                    receipt_image="receipts/blr-1.jpg", items=["chakli", "fruit"],
                    left_over=["salted peanuts"])
step("Sofie, visiting from Oslo, refills Bengaluru in INR")

clock.advance(days=3)
hr.approve(r.claim_id)
svc.sync_claims()
step("HR approves Lars's claim 3 days later")

report = svc.monthly_report(2026, 11, {"NOK": Decimal("1"), "INR": Decimal("0.12")})
print("\n== Monthly report for management")
for code, o in report["offices"].items():
    print(f"   {code}: spent {o['spent']} of {o['budget']} {o['currency']}, "
          f"{o['refills']} refill(s), avg {o['avg_hours_empty_to_restocked']} h empty -> restocked, "
          f"{o['awaiting_reimbursement']['claims']} claim(s) still unpaid")
print(f"   Total: {report['total_nok']} NOK (example rate 1 INR = 0.12 NOK)")
