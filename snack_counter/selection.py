"""Choosing who to ask to buy.

Rules, in order:
  1. Only volunteers who are physically at that office today
     (this includes visitors from the other office, and excludes people
     working from home or on holiday).
  2. Skip anyone who already let this refill run out, anyone busy with
     another open refill, and anyone still waiting for too many
     reimbursements, so nobody ends up carrying a lot of the company's costs.
  3. Among the rest, ask the person who has done the fewest refills
     recently; if tied, the one whose last refill was longest ago; if still
     tied, by employee id so the result is predictable.
"""

from __future__ import annotations

from datetime import date, datetime

from .models import Volunteer


def choose_buyer(
    volunteers: list[Volunteer],
    office: str,
    day: date,
    *,
    exclude: set[str],
    busy: set[str],
    unpaid_claims: dict[str, int],
    recent_refills: dict[str, int],
    last_refill: dict[str, datetime],
    max_unpaid_claims: int,
) -> Volunteer | None:
    candidates = [
        v for v in volunteers
        if v.location_on(day) == office
        and v.employee_id not in exclude
        and v.employee_id not in busy
        and unpaid_claims.get(v.employee_id, 0) < max_unpaid_claims
    ]
    if not candidates:
        return None
    oldest = datetime.min.replace(tzinfo=None)

    def fairness(v: Volunteer):
        last = last_refill.get(v.employee_id)
        last_key = last.replace(tzinfo=None) if last else oldest
        return (recent_refills.get(v.employee_id, 0), last_key, v.employee_id)

    return min(candidates, key=fairness)
