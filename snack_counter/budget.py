"""Monthly budget per office, kept in that office's own currency.

Money is counted in two steps:
  1. When someone commits to buy, their spending cap is *reserved*, so two
     refills in the same month can't both plan to use the same money.
  2. When the receipt comes in, the reservation is replaced by the *actual*
     amount spent.
Converting between currencies only happens in the management report, never
in the budget check, so a change in exchange rate can't make a budget wrong.
"""

from __future__ import annotations

from decimal import Decimal

from .models import Office

Month = tuple[int, int]  # (year, month)


class BudgetLedger:
    def __init__(self, offices: dict[str, Office]) -> None:
        self._offices = offices
        self._reserved: dict[tuple[str, Month], dict[str, Decimal]] = {}
        self._spent: dict[tuple[str, Month], dict[str, Decimal]] = {}

    def reserved(self, office: str, month: Month) -> Decimal:
        return sum(self._reserved.get((office, month), {}).values(), Decimal(0))

    def spent(self, office: str, month: Month) -> Decimal:
        return sum(self._spent.get((office, month), {}).values(), Decimal(0))

    def remaining(self, office: str, month: Month) -> Decimal:
        budget = self._offices[office].monthly_budget
        return budget - self.reserved(office, month) - self.spent(office, month)

    def spend_cap(self, office: str, month: Month) -> Decimal | None:
        """How much the next buyer may spend, or None if there isn't enough left.

        The cap is the usual maximum purchase, lowered to whatever is left in
        the budget. If even the smallest useful purchase doesn't fit, the
        refill is blocked and a person decides.
        """
        o = self._offices[office]
        left = self.remaining(office, month)
        if left < o.typical_min:
            return None
        return min(o.typical_max, left)

    def reserve(self, office: str, month: Month, refill_id: str, amount: Decimal) -> None:
        self._reserved.setdefault((office, month), {})[refill_id] = amount

    def release(self, office: str, month: Month, refill_id: str) -> None:
        self._reserved.get((office, month), {}).pop(refill_id, None)

    def settle(self, office: str, month: Month, refill_id: str, actual: Decimal) -> None:
        """Replace the reservation with the real amount from the receipt."""
        self.release(office, month, refill_id)
        self._spent.setdefault((office, month), {})[refill_id] = actual
