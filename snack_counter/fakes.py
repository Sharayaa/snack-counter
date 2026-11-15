"""Stand-ins for the outside world: the clock, the chat tool and the HR system.

The real system would call the company's chat API and the HR provider's API.
Keeping them behind these small classes means the core logic can be tested
without either, and the real versions can be swapped in later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import count


class FixedClock:
    """A clock the tests control, so timeouts can be checked without waiting."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("use a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now += timedelta(**kwargs)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class ChatMessage:
    to: str        # an employee id, or "#snacks-OSL" / "#snacks-BLR" for an office channel
    text: str


class FakeChat:
    """Records messages instead of sending them."""

    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []

    def post_channel(self, office_code: str, text: str) -> None:
        self.messages.append(ChatMessage(f"#snacks-{office_code}", text))

    def dm(self, employee_id: str, text: str) -> None:
        self.messages.append(ChatMessage(employee_id, text))

    def messages_to(self, who: str) -> list[str]:
        return [m.text for m in self.messages if m.to == who]


@dataclass
class HRClaim:
    id: str
    employee_id: str
    amount: Decimal
    currency: str
    description: str
    receipt_image: str
    status: str = "pending"          # pending, approved, rejected
    reason: str | None = None


class HRUnavailable(Exception):
    """Raised when the HR system cannot be reached."""


class FakeHR:
    """Behaves like the outside HR system described in the brief.

    It accepts a claim with amount, currency, description, receipt image and
    employee id. Approval happens later (1 to 10 days in real life); tests
    call approve() or reject() to simulate that. HR pays the employee in their
    payroll currency, so we always send the receipt currency and let HR convert.
    """

    def __init__(self) -> None:
        self.claims: dict[str, HRClaim] = {}
        self.available = True
        self._ids = count(1)

    def create_claim(self, *, employee_id: str, amount: Decimal, currency: str,
                     description: str, receipt_image: str) -> str:
        if not self.available:
            raise HRUnavailable("HR system did not respond")
        if not (employee_id and receipt_image and description) or amount <= 0:
            raise ValueError("HR needs employee id, a positive amount, a description and a receipt")
        claim_id = f"HR-{next(self._ids)}"
        self.claims[claim_id] = HRClaim(claim_id, employee_id, amount, currency,
                                        description, receipt_image)
        return claim_id

    def get_status(self, claim_id: str) -> str:
        if not self.available:
            raise HRUnavailable("HR system did not respond")
        return self.claims[claim_id].status

    # Used by tests to play the role of the HR team.
    def approve(self, claim_id: str) -> None:
        self.claims[claim_id].status = "approved"

    def reject(self, claim_id: str, reason: str) -> None:
        self.claims[claim_id].status = "rejected"
        self.claims[claim_id].reason = reason
