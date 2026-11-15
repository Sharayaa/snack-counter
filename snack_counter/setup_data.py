"""The two offices from the brief, with the budgets and typical purchases given."""

from decimal import Decimal

from .models import Office

OSLO = Office(
    code="OSL", name="Oslo", currency="NOK", timezone="Europe/Oslo",
    monthly_budget=Decimal("6000"), typical_min=Decimal("300"), typical_max=Decimal("1200"),
    admin_id="admin-osl",
)

BENGALURU = Office(
    code="BLR", name="Bengaluru", currency="INR", timezone="Asia/Kolkata",
    monthly_budget=Decimal("15000"), typical_min=Decimal("500"), typical_max=Decimal("3000"),
    admin_id="admin-blr",
)
