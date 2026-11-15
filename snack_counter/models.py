"""The data the system keeps: offices, volunteers and refills."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class RefillStatus(str, Enum):
    """Where a refill is in its life, from "empty" to "reimbursed"."""

    OPEN = "open"                        # box reported empty, waiting for someone to commit
    COMMITTED = "committed"              # exactly one volunteer has committed to buy
    RECEIPT_PENDING = "receipt_pending"  # the buyer says they have bought; receipt not uploaded yet
    BLOCKED = "blocked"                  # no budget left this month, office admin asked to decide
    PURCHASED = "purchased"              # bought and restocked, claim not yet accepted by HR
    CLAIM_SUBMITTED = "claim_submitted"  # claim is with HR (1 to 10 days)
    REIMBURSED = "reimbursed"            # HR approved and paid
    CLAIM_REJECTED = "claim_rejected"    # HR said no, a person must follow up


# While a refill is in one of these states it is still being dealt with, and
# no second refill can be opened for that office. RECEIPT_PENDING is included
# so that nobody else is asked to buy while the buyer still owes a receipt.
BOX_STILL_EMPTY = {RefillStatus.OPEN, RefillStatus.COMMITTED, RefillStatus.RECEIPT_PENDING,
                   RefillStatus.BLOCKED}


@dataclass(frozen=True)
class Office:
    code: str               # "OSL" or "BLR"
    name: str
    currency: str           # budget and receipt currency, "NOK" or "INR"
    timezone: str           # used to decide which calendar day "today" is
    monthly_budget: Decimal
    typical_min: Decimal    # smallest useful purchase
    typical_max: Decimal    # usual upper limit for one purchase
    admin_id: str           # person who decides when the budget runs out


@dataclass
class Volunteer:
    employee_id: str
    name: str
    home_office: str
    payroll_currency: str
    # Where the volunteer is on a given day: an office code, or None when
    # working from home or on holiday. A visitor simply has the other office
    # on the days they are there.
    schedule: dict[date, str | None] = field(default_factory=dict)

    def location_on(self, day: date) -> str | None:
        return self.schedule.get(day)


@dataclass
class Purchase:
    amount: Decimal
    currency: str
    receipt_image: str          # a file reference; the image itself lives elsewhere
    items: list[str]            # what was bought, so we can see what gets eaten
    purchased_at: datetime
    # What was still in the box when it was refilled: the snacks people don't eat.
    left_over: list[str] = field(default_factory=list)


@dataclass
class Refill:
    id: str
    office: str
    reported_by: str
    reported_at: datetime
    status: RefillStatus = RefillStatus.OPEN

    # Who has been asked, and until when.
    offered_to: str | None = None
    offer_expires_at: datetime | None = None

    # Who committed to buy, their deadline for uploading the receipt, and how
    # much they may spend.
    buyer: str | None = None
    commit_expires_at: datetime | None = None
    remind_at: datetime | None = None       # when to remind the buyer about that deadline
    reminded: bool = False
    receipt_overdue_flagged: bool = False   # buyer and admin already told the receipt is late
    spend_cap: Decimal | None = None
    budget_month: tuple[int, int] | None = None   # (year, month) the money counts against

    # People who let an offer or a commitment run out on this refill. Cleared
    # each working day, because who is in the office changes from day to day.
    passed: set[str] = field(default_factory=set)
    # The day the whole office channel was asked because nobody was left to ask.
    channel_asked_on: date | None = None
    # When the office admin is told the box is still empty, and whether they were.
    escalate_at: datetime | None = None
    escalated: bool = False

    purchase: Purchase | None = None
    over_cap: bool = False
    # Sent to HR with the claim. If we have to send the same claim twice, HR
    # can see it is the same one and not pay it twice. Unlike the refill id
    # (R-1, R-2, ...) it is unique even after the service restarts.
    claim_reference: str = field(default_factory=lambda: f"snack-refill-{uuid.uuid4().hex}")
    claim_id: str | None = None
    claim_sent_at: datetime | None = None
    claim_overdue_flagged: bool = False   # admin already told HR is taking too long
    restocked_at: datetime | None = None
    reimbursed_at: datetime | None = None

    # A plain log of what happened, for the walkthrough and for debugging.
    history: list[tuple[datetime, str]] = field(default_factory=list)

    def log(self, when: datetime, what: str) -> None:
        self.history.append((when, what))
