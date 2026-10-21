"""Renewal and reminder queries."""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from .leases import RenewalReminder, renewal_reminders
from .models import Lease, today_str


def due_reminders(leases: List[Lease],
                  within_days: int = 30,
                  asof: Optional[str] = None) -> List[RenewalReminder]:
    asof_date = today_str() if asof is None else asof
    return renewal_reminders(leases, within_days=within_days, asof=asof_date)


__all__ = [
    "RenewalReminder",
    "renewal_reminders",
    "due_reminders",
]
