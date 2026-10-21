"""
reports.py: human-readable reports and CSV export.
"""
__all__ = [
    "late_remediation_report",
    "renewal_reminders_text",
    "reminders_report",
    "late_reminders_report",
    "lease_renewal_report",
    "rent_collection",
    "collect_rent_csv",
    "maintenance_aging_report",
    "late_fee_report",
]

from .models import (
    Property, Unit, Lease, Payment, MaintenanceTicket,
    to_cents, from_cents, late_fee,
    parse_iso_datetime,
)
from .leases import (
    LEASE_STATUS_ACTIVE,
    renewal_reminders,
    parse_iso_date,
)
from .ledger import tenant_ledger, LateFeePolicy, MonthStatement
from .tickets import sla_hours_for, sla_breached, TicketView, is_breached

import csv
import io


def late_remediation_report(
    leases: list,
    now=None,
    asof=None,
     *,
    threshold_days: int = 30,
      **_unused,
) -> str:
    """Remediation summary for late/upcoming leases."""
    ref = asof
    if ref is None:
        ref = now
    if ref is None:
        ref = parse_iso_date("2026-01-01")
    if isinstance(ref, str):
        ref = parse_iso_date(ref)
    lines_out = []
    for lease in leases or []:
        end = parse_iso_date(lease.end)
        rem = (end - ref).days
        if rem > threshold_days:
            continue
        past = -rem if rem < 0 else 0
        fee = late_fee(lease.rent_cents, past)
        status = "LATE" if rem < 0 else "UPCOMING"
        ar = getattr(lease, "auto_renew", False)
        ar_flag = "auto-renew: yes" if ar else "auto-renew: no"
        lines_out.append(
            "{id} {status} {rem}d fee: ${fee:,.2f} {ar}".format(
                id=lease.id, status=status, rem=rem,
                fee=from_cents(fee), ar=ar_flag,
            )
        )
    if not lines_out:
        return "All leases within policy."
    return "\n".join(lines_out)


def renewal_report(leases, now=None, asof=None, threshold_days=30, within_days=None, **_unused):
    text = late_remediation_report(leases, now, asof, threshold_days=threshold_days)
    return text


renewal_reminders_text = renewal_report
reminders_report = renewal_report
late_reminders_report = renewal_report
lease_renewal_report = renewal_report


def rent_collection(
    payments: list,
    leases: list,
    properties=None,
    units=None,
    tenants=None,
    period: str = "2026-01-01",
      *,
    properties_dict: dict | None = None,
    units_dict: dict | None = None,
    policy=None,
    asof=None,
      **_unused,
) -> tuple[list[dict], dict]:
    """Build per-tenant collection rows. Returns (rows, total_dict)."""
    policy = policy or LateFeePolicy()
    if properties_dict is None:
        properties_dict = {}
        for p in properties or []:
            pid = getattr(p, "id", p) if not isinstance(p, dict) else p.get("id", "")
            properties_dict[pid] = p
    if units_dict is None:
        units_dict = {}
        for u in units or []:
            uid = getattr(u, "id", u) if not isinstance(u, dict) else u.get("id", "")
            units_dict[uid] = u

    def _lookup(d, key, default):
        v = (d or {}).get(key, default)
        if isinstance(v, dict):
            return v.get("name", default)
        return v

    from collections import defaultdict
    tenant_payments: dict[str, list] = defaultdict(list)
    for pay in payments or []:
        tenant_payments[pay.tenant_id].append(pay)
    tenant_leases: dict[str, list] = defaultdict(list)
    for lease in leases or []:
        tenant_leases[lease.tenant_id].append(lease)

    rows = []
    due_total = 0
    paid_total = 0
    for tid in sorted(tenant_leases.keys()):
        llist = tenant_leases[tid]
        plist = tenant_payments.get(tid, [])
        due = 0
        for lease in llist:
            due += int(getattr(lease, "rent_cents", 0) or 0)
        paid = 0
        for pay in plist:
            paid += int(getattr(pay, "amount_cents", 0) or 0)
        outstanding = max(due - paid, 0)
        l0 = llist[0]
        pid = getattr(l0, "prop_id", getattr(l0, "property_id", ""))
        uid = getattr(l0, "unit_id", "")
        uinfo = units_dict.get(uid, {})
        if isinstance(uinfo, dict):
            unit_label = str(uinfo.get("number", uid))
        else:
            unit_label = str(getattr(uinfo, "number", uid))
        row = {
            "tenant_id": tid,
            "period": period,
            "due_cents": due,
            "paid_cents": paid,
            "outstanding_cents": outstanding,
            "lease_count": len(llist),
            "payment_count": len(plist),
            "property_id": pid,
            "property_name": _lookup(properties_dict, pid, ""),
            "unit_id": uid,
            "unit_label": unit_label,
            "status": "outstanding" if outstanding > 0 else "settled",
        }
        rows.append(row)
        due_total += due
        paid_total += paid
    balance_total = max(due_total - paid_total, 0)
    total = {
        "due_cents": due_total,
        "paid_cents": paid_total,
        "balance_cents": balance_total,
        "status": "outstanding" if balance_total > 0 else "settled",
    }
    return rows, total


def _write_csv(buf, payments, leases, properties, units, tenants, period, policy):
    """Write the rent-collection CSV to ``buf``; return (rows, total_dict)."""
    rows, total = rent_collection(
        payments, leases, properties, units, tenants, period, policy=policy,
    )
    w = csv.writer(buf)
    w.writerow(["tenant_id", "period", "due", "paid", "outstanding", "status"])
    for row in rows:
        w.writerow([
            row["tenant_id"],
            row["period"],
            row["due_cents"],
            row["paid_cents"],
            row["outstanding_cents"],
            row["status"],
        ])
    w.writerow([
        "PORTFOLIO",
        period,
        total["due_cents"],
        total["paid_cents"],
        total["balance_cents"],
        total["status"],
    ])
    return rows, total


def collect_rent_csv(
    out,
    payments: list,
    leases: list,
    properties=None,
    units=None,
    tenants=None,
    period: str = "2026-01-01",
      *,
    policy=None,
    asof=None,
      **_unused,
) -> tuple[list[dict], dict]:
    """Collect and write CSV. ``out`` may be a path or an open file handle."""
    policy = policy or LateFeePolicy()
    if hasattr(out, "write"):
        return _write_csv(out, payments, leases, properties, units, tenants, period, policy)
    with open(out, "w", newline="") as f:
        return _write_csv(f, payments, leases, properties, units, tenants, period, policy)


def late_fee_report(
    leases: list,
    payments: list,
    month_start: str = "2026-01-01",
    period_start: int | None = None,
    period_end: int | None = None,
    asof: "date | None" = None,
    policy: "LateFeePolicy | None" = None,
      **_unused,
) -> int:
    p = policy or LateFeePolicy()
    total = 0
    for lease in leases or []:
        tl = tenant_ledger(
            leases, payments, lease.tenant_id,
            month_start=month_start,
            period_start=period_start,
            period_end=period_end,
            policy=p,
            asof=asof,
        )
        total = total + int(getattr(tl, "late_fee", 0) or 0)
    return total


def maintenance_aging_report(tickets: list, asof=None):
    """Return aged open maintenance tickets sorted by age descending."""
    rows = []
    for t in tickets or []:
        view = TicketView(t)
        if view.is_open:
            rows.append({
                "id": view.id,
                "property_id": view.property_id,
                "unit_id": view.unit_id,
                "title": view.title,
                "priority": view.priority,
                "status": view.status,
                "opened_when": str(view.opened_when),
                "age_hours": view.age_hours(asof),
                "sla_hours": view.sla_hours,
                "breached": is_breached(t, asof=asof),
            })
    return sorted(rows, key=lambda r: r["age_hours"], reverse=True)


if __name__ == "__main__":
    print(__doc__ or "reports.py")
