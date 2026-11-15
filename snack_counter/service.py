"""The refill lifecycle: from "box is empty" to "volunteer is reimbursed".

    report_empty ──> OPEN ──commit──> COMMITTED ──record_purchase──> PURCHASED
                      │  ^                │ (1 working day, no receipt) │
                      │  └────────────────┘ handed to the next person   │ claim sent to HR
                      │                                                 v
                      └─(no budget)─> BLOCKED              CLAIM_SUBMITTED
                        <─(new month)─┘                      │          │
                                                       REIMBURSED  CLAIM_REJECTED

Deadlines count office hours only (see working_hours.py), so nobody is timed
out overnight or over a weekend.

All state changes go through one lock, so two people pressing "I'll buy" at
the same moment can never both succeed. In a real deployment the same rule
would be a conditional update in the database ("set buyer where status is
open"), which gives the same guarantee across several servers.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

from .budget import BudgetLedger
from .fakes import HRUnavailable
from .models import BOX_STILL_EMPTY, Office, Purchase, Refill, RefillStatus, Volunteer
from .selection import choose_buyer
from .working_hours import HOURS_PER_DAY, add_working_time, is_working_day


class RefillError(Exception):
    """An action that isn't allowed in the refill's current state."""


class SnackService:
    def __init__(
        self,
        offices: list[Office],
        volunteers: list[Volunteer],
        chat,
        hr,
        clock,
        *,
        offer_timeout: timedelta = timedelta(hours=2),                      # office hours
        commit_timeout: timedelta = timedelta(hours=HOURS_PER_DAY),         # one working day
        escalate_after: timedelta = timedelta(hours=2 * HOURS_PER_DAY),     # two working days
        max_unpaid_claims: int = 2,
        fairness_window: timedelta = timedelta(days=30),
        hr_max_wait: timedelta = timedelta(days=10),                        # HR's own promise
    ) -> None:
        self.offices = {o.code: o for o in offices}
        self.volunteers = {v.employee_id: v for v in volunteers}
        self.chat = chat
        self.hr = hr
        self.clock = clock
        self.budget = BudgetLedger(self.offices)
        self.refills: dict[str, Refill] = {}
        self.offer_timeout = offer_timeout
        self.commit_timeout = commit_timeout
        self.escalate_after = escalate_after
        self.hr_max_wait = hr_max_wait
        self.max_unpaid_claims = max_unpaid_claims
        self.fairness_window = fairness_window
        self._lock = threading.Lock()
        self._ids = count(1)

    # ------------------------------------------------------------------ helpers

    def _now(self) -> datetime:
        return self.clock.now()

    def _local_today(self, office: str):
        return self._now().astimezone(ZoneInfo(self.offices[office].timezone)).date()

    def _month(self, office: str) -> tuple[int, int]:
        d = self._local_today(office)
        return (d.year, d.month)

    def _deadline(self, office: str, duration: timedelta) -> datetime:
        """`duration` of office time from now, in that office's time zone."""
        return add_working_time(self._now(), duration, self.offices[office].timezone)

    def _local(self, office: str, when: datetime) -> str:
        """A time as people in that office would read it, e.g. 'Tue 11:00'."""
        return when.astimezone(ZoneInfo(self.offices[office].timezone)).strftime("%a %H:%M")

    def active_refill(self, office: str) -> Refill | None:
        for r in self.refills.values():
            if r.office == office and r.status in BOX_STILL_EMPTY:
                return r
        return None

    def _get(self, refill_id: str) -> Refill:
        if refill_id not in self.refills:
            raise RefillError(f"unknown refill {refill_id}")
        return self.refills[refill_id]

    def _name(self, employee_id: str) -> str:
        v = self.volunteers.get(employee_id)
        return v.name if v else employee_id

    # ---------------------------------------------------- 1. box reported empty

    def report_empty(self, office: str, reporter_id: str) -> Refill:
        """Anyone can report an empty box. A second report joins the open one."""
        if office not in self.offices:
            raise RefillError(f"unknown office {office}")
        with self._lock:
            existing = self.active_refill(office)
            if existing:
                who = self._name(existing.buyer) if existing.buyer else "nobody yet"
                self.chat.dm(reporter_id, f"Thanks! This refill is already open ({existing.id}); buyer: {who}.")
                return existing

            refill = Refill(id=f"R-{next(self._ids)}", office=office,
                            reported_by=reporter_id, reported_at=self._now(),
                            escalate_at=self._deadline(office, self.escalate_after))
            refill.log(self._now(), f"reported empty by {reporter_id}")
            self.refills[refill.id] = refill

            if self.budget.spend_cap(office, self._month(office)) is None:
                self._block(refill)
            else:
                self._offer_next(refill)
            return refill

    def _block(self, refill: Refill) -> None:
        o = self.offices[refill.office]
        refill.status = RefillStatus.BLOCKED
        refill.offered_to = None
        refill.log(self._now(), "blocked: monthly budget used up")
        self.chat.post_channel(o.code, "The snack box is empty, but this month's snack budget is used up. "
                                       "The office admin has been asked to decide.")
        self.chat.dm(o.admin_id, f"{refill.id}: {o.name} snack budget is used up for this month. "
                                 "Approve extra spend or wait for next month.")

    # ------------------------------------------------------ 2. choosing a buyer

    def _recent_refill_stats(self):
        since = self._now() - self.fairness_window
        recent: dict[str, int] = {}
        last: dict[str, datetime] = {}
        unpaid: dict[str, int] = {}
        busy: set[str] = set()
        for r in self.refills.values():
            if r.status == RefillStatus.COMMITTED and r.buyer:
                busy.add(r.buyer)
            if r.buyer and r.restocked_at:
                if r.restocked_at >= since:
                    recent[r.buyer] = recent.get(r.buyer, 0) + 1
                if r.buyer not in last or r.restocked_at > last[r.buyer]:
                    last[r.buyer] = r.restocked_at
            if r.buyer and r.status in (RefillStatus.PURCHASED, RefillStatus.CLAIM_SUBMITTED):
                unpaid[r.buyer] = unpaid.get(r.buyer, 0) + 1
        return recent, last, unpaid, busy

    def _offer_next(self, refill: Refill) -> None:
        recent, last, unpaid, busy = self._recent_refill_stats()
        pick = choose_buyer(
            list(self.volunteers.values()), refill.office, self._local_today(refill.office),
            exclude=refill.passed, busy=busy, unpaid_claims=unpaid,
            recent_refills=recent, last_refill=last, max_unpaid_claims=self.max_unpaid_claims,
        )
        refill.status = RefillStatus.OPEN
        if pick is None:
            refill.offered_to = None
            refill.offer_expires_at = None
            refill.channel_asked_on = self._local_today(refill.office)
            refill.log(self._now(), "no volunteer available in the office; asked the channel")
            self.chat.post_channel(refill.office, f"The snack box is empty ({refill.id}) and no volunteer "
                                                  "on the list is in the office. Anyone in today can commit to buy.")
            return
        refill.offered_to = pick.employee_id
        refill.offer_expires_at = self._deadline(refill.office, self.offer_timeout)
        refill.log(self._now(), f"asked {pick.employee_id}")
        cap = self.budget.spend_cap(refill.office, self._month(refill.office))
        cur = self.offices[refill.office].currency
        self.chat.dm(pick.employee_id, f"The snack box is empty ({refill.id}). Can you buy today? "
                                       f"Spend up to {cap} {cur}. Reply 'commit' or 'pass'.")
        self.chat.post_channel(refill.office, f"The snack box is empty. {pick.name} has been asked to buy ({refill.id}).")

    # ---------------------------------------------------- 3. committing to buy

    def commit(self, refill_id: str, employee_id: str) -> bool:
        """Try to become the buyer. Returns False if someone else already is."""
        with self._lock:
            refill = self._get(refill_id)
            if employee_id not in self.volunteers:
                raise RefillError("only registered volunteers can commit to buy")
            if refill.status != RefillStatus.OPEN:
                who = self._name(refill.buyer) if refill.buyer else "nobody"
                self.chat.dm(employee_id, f"{refill.id} is already taken care of (buyer: {who}). No need to buy.")
                return False

            month = self._month(refill.office)
            cap = self.budget.spend_cap(refill.office, month)
            if cap is None:
                self._block(refill)
                self.chat.dm(employee_id, "Please don't buy: the monthly snack budget is used up.")
                return False

            self.budget.reserve(refill.office, month, refill.id, cap)
            refill.status = RefillStatus.COMMITTED
            refill.buyer = employee_id
            refill.spend_cap = cap
            refill.budget_month = month
            refill.commit_expires_at = self._deadline(refill.office, self.commit_timeout)
            refill.offered_to = None
            refill.offer_expires_at = None
            refill.log(self._now(), f"{employee_id} committed, cap {cap}")
            cur = self.offices[refill.office].currency
            self.chat.post_channel(refill.office, f"{self._name(employee_id)} is buying snacks ({refill.id}). "
                                                  "Nobody else needs to.")
            self.chat.dm(employee_id, f"Thanks! Spend up to {cap} {cur} and upload the receipt "
                                      f"by {self._local(refill.office, refill.commit_expires_at)}.")
            return True

    def pass_offer(self, refill_id: str, employee_id: str) -> None:
        """The asked volunteer says they can't; ask the next person straight away."""
        with self._lock:
            refill = self._get(refill_id)
            if refill.status == RefillStatus.OPEN and refill.offered_to == employee_id:
                refill.passed.add(employee_id)
                refill.log(self._now(), f"{employee_id} passed")
                self._offer_next(refill)

    # -------------------------------------------- 4. timeouts and hand-overs

    def check_timeouts(self) -> None:
        """Run regularly (e.g. every 15 minutes). Moves stuck refills along."""
        with self._lock:
            now = self._now()
            for refill in list(self.refills.values()):
                if refill.status not in BOX_STILL_EMPTY:
                    continue
                today = self._local_today(refill.office)

                if refill.status == RefillStatus.BLOCKED:
                    # A new month brings a new budget: start asking again.
                    if self.budget.spend_cap(refill.office, self._month(refill.office)) is not None:
                        refill.log(now, "budget available again; reopened")
                        self._offer_next(refill)

                elif refill.status == RefillStatus.COMMITTED:
                    if now >= refill.commit_expires_at:
                        self._hand_over(refill)

                elif refill.offered_to:
                    if now >= refill.offer_expires_at:
                        refill.passed.add(refill.offered_to)
                        refill.log(now, f"offer to {refill.offered_to} expired")
                        self._offer_next(refill)

                elif refill.channel_asked_on != today and is_working_day(today):
                    # Everyone had passed or was away. It's a new working day,
                    # with different people in the office, so start over.
                    refill.passed.clear()
                    refill.log(now, "new working day; asking again")
                    self._offer_next(refill)

                self._escalate_if_stuck(refill)

    def _hand_over(self, refill: Refill) -> None:
        """The buyer ran out of time: free the money and ask the next person."""
        old = refill.buyer
        self.budget.release(refill.office, refill.budget_month, refill.id)
        refill.passed.add(old)
        refill.buyer = None
        refill.spend_cap = None
        refill.budget_month = None
        refill.commit_expires_at = None
        refill.log(self._now(), f"{old} did not complete in time; handing over")
        self.chat.dm(old, f"{refill.id} has been handed to someone else. Please don't buy for it now.")
        self._offer_next(refill)

    def _escalate_if_stuck(self, refill: Refill) -> None:
        """The backstop: a box empty for two working days goes to a named person."""
        if refill.escalated or refill.status == RefillStatus.BLOCKED:   # admin already knows
            return
        if self._now() < refill.escalate_at:
            return
        refill.escalated = True
        o = self.offices[refill.office]
        refill.log(self._now(), "escalated to the office admin")
        self.chat.dm(o.admin_id, f"{refill.id}: the {o.name} snack box has been empty since "
                                 f"{self._local(o.code, refill.reported_at)} and is still not restocked.")

    # ----------------------------------------- 5. bought, restocked, claimed

    def record_purchase(self, refill_id: str, employee_id: str, *, amount: Decimal, currency: str,
                        receipt_image: str, items: list[str],
                        left_over: list[str] | None = None) -> Refill:
        with self._lock:
            refill = self._get(refill_id)
            if refill.status != RefillStatus.COMMITTED or refill.buyer != employee_id:
                raise RefillError("only the committed buyer can record the purchase")
            office = self.offices[refill.office]
            if currency != office.currency:
                raise RefillError(f"receipts for {office.name} must be in {office.currency}")
            if amount <= 0:
                raise RefillError("amount must be positive")
            if not receipt_image:
                raise RefillError("a receipt image is required")

            now = self._now()
            refill.purchase = Purchase(amount, currency, receipt_image, list(items), now,
                                       list(left_over or []))
            refill.over_cap = amount > refill.spend_cap
            # The volunteer has already paid, so we always record the real
            # amount and always claim it. Going over the cap is flagged for
            # the admin, never used to leave someone out of pocket.
            self.budget.settle(refill.office, refill.budget_month, refill.id, amount)
            refill.status = RefillStatus.PURCHASED
            refill.restocked_at = now
            refill.log(now, f"purchased {amount} {currency}" + (" (over cap)" if refill.over_cap else ""))
            self.chat.post_channel(office.code, f"Snacks restocked by {self._name(employee_id)}. Thank you!")
            if refill.over_cap:
                self.chat.dm(office.admin_id, f"{refill.id}: spent {amount} {currency}, above the agreed "
                                              f"cap of {refill.spend_cap} {currency}.")
            self._submit_claim(refill)
            return refill

    def _submit_claim(self, refill: Refill) -> None:
        p = refill.purchase
        try:
            refill.claim_id = self.hr.create_claim(
                employee_id=refill.buyer, amount=p.amount, currency=p.currency,
                description=f"Snack refill {refill.office} {p.purchased_at.date().isoformat()} ({refill.id})",
                receipt_image=p.receipt_image,
            )
        except HRUnavailable:
            refill.log(self._now(), "HR unavailable; claim will be retried")
            return  # stays PURCHASED; sync_claims retries
        refill.status = RefillStatus.CLAIM_SUBMITTED
        refill.claim_sent_at = self._now()
        refill.log(self._now(), f"claim {refill.claim_id} sent to HR")
        self.chat.dm(refill.buyer, f"Your reimbursement claim {refill.claim_id} for "
                                   f"{p.amount} {p.currency} has been sent to HR.")

    # ------------------------------------------------ 6. following the claim

    def sync_claims(self) -> None:
        """Run regularly. Retries failed submissions and picks up HR decisions."""
        with self._lock:
            for refill in self.refills.values():
                if refill.status == RefillStatus.PURCHASED:
                    self._submit_claim(refill)
                elif refill.status == RefillStatus.CLAIM_SUBMITTED:
                    try:
                        status = self.hr.get_status(refill.claim_id)
                    except HRUnavailable:
                        continue
                    if status == "approved":
                        refill.status = RefillStatus.REIMBURSED
                        refill.reimbursed_at = self._now()
                        refill.log(self._now(), "reimbursed")
                        self.chat.dm(refill.buyer, f"Claim {refill.claim_id} was approved. Thanks for refilling!")
                    elif status == "rejected":
                        refill.status = RefillStatus.CLAIM_REJECTED
                        refill.log(self._now(), "claim rejected by HR")
                        admin = self.offices[refill.office].admin_id
                        self.chat.dm(refill.buyer, f"HR rejected claim {refill.claim_id}. The office admin will follow up.")
                        self.chat.dm(admin, f"{refill.id}: HR rejected claim {refill.claim_id}; please follow up.")
                    elif (not refill.claim_overdue_flagged
                            and self._now() - refill.claim_sent_at > self.hr_max_wait):
                        # The volunteer shouldn't have to chase their own money.
                        refill.claim_overdue_flagged = True
                        refill.log(self._now(), "claim overdue at HR; admin told")
                        admin = self.offices[refill.office].admin_id
                        self.chat.dm(admin, f"{refill.id}: claim {refill.claim_id} for {self._name(refill.buyer)} has "
                                            f"waited more than {self.hr_max_wait.days} days at HR; please chase it.")

    # --------------------------------------------------- 7. monthly report

    def monthly_report(self, year: int, month: int, rate_to_nok: dict[str, Decimal]) -> dict:
        """One report for management: each office in its own currency, plus a
        combined total in NOK using the rates passed in for that month."""
        offices = {}
        total_nok = Decimal(0)
        for code, o in self.offices.items():
            spent = self.budget.spent(code, (year, month))
            done = [r for r in self.refills.values()
                    if r.office == code and r.budget_month == (year, month) and r.restocked_at]
            hours = [(r.restocked_at - r.reported_at).total_seconds() / 3600 for r in done]
            items: dict[str, int] = {}
            left_over: dict[str, int] = {}
            by_person: dict[str, int] = {}
            for r in done:
                by_person[r.buyer] = by_person.get(r.buyer, 0) + 1
                for item in r.purchase.items:
                    items[item] = items.get(item, 0) + 1
                for item in r.purchase.left_over:
                    left_over[item] = left_over.get(item, 0) + 1
            unpaid = [r for r in done if r.status in (RefillStatus.PURCHASED, RefillStatus.CLAIM_SUBMITTED)]
            paid_days = [(r.reimbursed_at - r.restocked_at).total_seconds() / 86400
                         for r in done if r.reimbursed_at]
            offices[code] = {
                "currency": o.currency,
                "budget": o.monthly_budget,
                "spent": spent,
                "refills": len(done),
                "over_cap_refills": sum(1 for r in done if r.over_cap),
                "avg_hours_empty_to_restocked": round(sum(hours) / len(hours), 1) if hours else None,
                "items_bought": items,
                "items_left_over": left_over,     # bought but still there at the next refill
                "refills_by_person": by_person,
                "awaiting_reimbursement": {"claims": len(unpaid),
                                           "amount": sum((r.purchase.amount for r in unpaid), Decimal(0))},
                "avg_days_to_reimburse": round(sum(paid_days) / len(paid_days), 1) if paid_days else None,
            }
            total_nok += spent * rate_to_nok[o.currency]
        return {"month": f"{year}-{month:02d}", "offices": offices,
                "total_nok": total_nok.quantize(Decimal("0.01"))}
