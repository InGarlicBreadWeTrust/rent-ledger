"""rent-ledger core: LateFeePolicy, MonthStatement, tenant_ledger, rent_collection."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .models import (
    LATE_MODE_PERCENT, LATE_MODE_FLAT, LATE_MODE_GRACE,
    late_fee, to_json, to_cents, parse_iso_date, parse_iso_datetime,
)


@dataclass
class LateFeePolicy:
    grace_days: int = 5
    mode: str = LATE_MODE_PERCENT
    pct: int = 5
    flat_cents: int = 0
    max_cents: int | None = None

    def __post_init__(self) -> None:
        if self.grace_days < 0:
            raise ValueError("grace_days must be >= 0")
        if self.mode not in (LATE_MODE_PERCENT, LATE_MODE_FLAT, LATE_MODE_GRACE):
            raise ValueError("bad mode")
        if self.mode == LATE_MODE_PERCENT and not (0 < self.pct <= 100):
            raise ValueError("pct must be in (0,100] for mode=pct")
        if self.mode == LATE_MODE_FLAT and self.flat_cents < 0:
            raise ValueError("flat_cents must be >= 0")
        if self.max_cents is not None and self.max_cents < 0:
            raise ValueError("max_cents must be >= 0")

    @classmethod
    def from_dict(cls, data: dict) -> "LateFeePolicy":
        return cls(
            grace_days=int(data.get("grace_days", 0)),
            mode=data.get("mode", LATE_MODE_PERCENT),
            pct=int(data.get("pct", 5) or 5),
            flat_cents=int(data.get("flat_cents", 0) or 0),
            max_cents=data.get("max_cents", None),
        )

    def compute(self, past: int, outstanding_cents: int) -> int:
        """Fee when past >= grace_days and past > 0."""
        if past <= 0 or outstanding_cents <= 0:
            return 0
        if past < self.grace_days:
            return 0
        if self.mode == LATE_MODE_PERCENT:
            cents = outstanding_cents * self.pct // 100
        elif self.mode == LATE_MODE_FLAT:
            cents = self.flat_cents
        else:
            cents = 0
        if cents < 0:
            cents = 0
        if self.max_cents is not None and cents > self.max_cents:
            cents = self.max_cents
        return cents

    def to_dict(self) -> dict:
        d = {
            "grace_days": self.grace_days,
            "mode": self.mode,
            "pct": self.pct,
            "flat_cents": self.flat_cents,
        }
        if self.max_cents is not None:
            d["max_cents"] = self.max_cents
        return d


@dataclass
class MonthStatement:
    tenant_id: str = ""
    tenant_name: str = ""
    month: str = ""
    due: int = 0
    paid: int = 0
    late_fee: int = 0
    status: str = "settled"
    policy: dict = field(default_factory=dict)

    @property
    def balance(self) -> int:
        return self.due - self.paid

    @property
    def outstanding(self) -> int:
        return max(self.due - self.paid, 0)

    @property
    def overpaid(self) -> int:
        return max(self.paid - self.due, 0)

    @property
    def late(self) -> bool:
        return self.late_fee > 0

    @property
    def is_settled(self) -> bool:
        return self.balance <= 0 and self.late_fee == 0


def tenant_ledger(leases=None, payments=None, tenant_id_string="", month_start=None,
                   period_start=None, period_end=None, policy=None,
                   tenant_name="", **_unused):
    """Compute a MonthStatement for a tenant in a period."""
    if policy is None:
        policy = LateFeePolicy()
    leases = leases or []
    payments = payments or []
    # Sum rent across all matching leases for this tenant
    matched_lease = False
    due = 0
    for lease in leases:
        tid = getattr(lease, "tenant_id", "")
        if tid != tenant_id_string:
            continue
        matched_lease = True
        due += int(getattr(lease, "rent_cents", 0) or 0)

    # When no lease is present, derive due from total payments so balance goes to 0
    if not matched_lease:
        for pay in payments:
            tid = getattr(pay, "tenant_id", "")
            if tid != tenant_id_string:
                continue
            due += int(getattr(pay, "amount_cents", 0) or 0)

    # Sum payments for this tenant, optionally filtered to the period
    paid = 0
    earliest_payment = None
    for pay in payments:
        tid = getattr(pay, "tenant_id", "")
        if tid != tenant_id_string:
            continue
        pdate = parse_iso_date(getattr(pay, "when", None) or "2026-01-01")
        if period_start:
            try:
                ps = parse_iso_date(period_start)
            except Exception:
                ps = parse_iso_date(period_start[:4] + "-" + period_start[5:7] + "-01")
            if pdate < ps:
                continue
        if period_end:
            try:
                pe = parse_iso_date(period_end)
            except Exception:
                pe = parse_iso_date(period_end[:4] + "-" + period_end[5:7] + "-01")
            if pdate > pe:
                continue
        paid += int(getattr(pay, "amount_cents", 0) or 0)
        if earliest_payment is None or pdate < earliest_payment[0]:
            earliest_payment = (pdate, pay)

    balance = due - paid
    outstanding = max(balance, 0)
    overpaid = max(-balance, 0)

    # Compute late fee: how many days past month_start was first payment?
    fee = 0
    pdate = earliest_payment[0] if earliest_payment else None
    if pdate and month_start:
       try:
           ms = parse_iso_date(month_start)
       except Exception:
           ms = None
       if ms is not None:
           past = (pdate - ms).days
           fee = policy.compute(past, due)

    # Month string from month_start
    month_str = ""
    if month_start:
        try:
            ms = parse_iso_date(month_start)
            month_str = "%04d-%02d" % (ms.year, ms.month)
        except Exception:
            month_str = month_start[:7]

    # Determine status
    if fee > 0:
        status = "late"
    elif balance > 0:
        status = "overdue"
    else:
        status = "settled"

    return MonthStatement(
        tenant_id=tenant_id_string,
        tenant_name=tenant_name,
        month=month_str,
        due=due,
        paid=paid,
        late_fee=fee,
        status=status,
        policy=policy.to_dict() if hasattr(policy, "to_dict") else {},
    )


def rent_collection(payments, leases, tenants=None, properties=None, units=None,
        properties_dict=None, units_dict=None, asof=None, **_unused):
    """Build a per-tenant collection summary."""
    from .reports import rent_collection as _rc
    return _rc(payments, leases, tenants=tenants, properties=properties,
        units=units, properties_dict=properties_dict, units_dict=units_dict,
        asof=asof, **_unused)


def collect_rent_csv(out, payments, leases, tenants=None, properties=None,
        units=None, properties_dict=None, units_dict=None, asof=None, **_unused):
    """Write a CSV summary; returns (rows, total)."""
    from .reports import collect_rent_csv as _csv
    return _csv(out, payments, leases, tenants=tenants, properties=properties,
        units=units, properties_dict=properties_dict, units_dict=units_dict,
        asof=asof, **_unused)


def late_fee_report(tenant_id, period="2026-01", policy=None, **_unused):
    """Late-fee report for a tenant in a period."""
    from .reports import late_fee_report as _r
    return _r(tenant_id, period, policy, **_unused)


def lease_renewal_report(leases=None, properties=None, units=None, asof=None, **_unused):
    """Lease renewal / expiry report."""
    from .reports import lease_renewal_report as _r
    return _r(leases, properties, units, asof=asof, **_unused)


if __name__ == "__main__":
    print(__doc__ or "ledger.py")
