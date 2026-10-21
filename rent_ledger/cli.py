"""rent-ledger command-line interface."""
from __future__ import annotations

import argparse
import sys

from .ledger import LateFeePolicy, tenant_ledger
from .models import (
     Lease, MaintenanceTicket, Payment, Property, Tenant, Unit,
     parse_iso_date,
)
from .reports import (
     collect_rent_csv,
     lease_renewal_report,
     maintenance_aging_report,
     rent_collection,
     reminders_report,
)
from .store import LedgerStore
from .tickets import by_status, sla_breached


def _asof(a):
    return parse_iso_date(a.asof) if getattr(a, "asof", None) else None


def load_store(a):
    return LedgerStore(a.snap).load()


def cmd_add_property(a):
    store = load_store(a)
    prop = Property(id=a.id, name=a.name or a.id,
                    address=a.address, units=a.units)
    store.add_property(prop)
    print("added property %s" % prop.id)
    return 0


def cmd_add_unit(a):
    store = load_store(a)
    unit = Unit(id=a.id, property_id=a.property,
                number=a.number, rent_cents=a.rent)
    store.add_unit(unit)
    print("added unit %s (%d cents/mo)" % (unit.id, unit.rent_cents))
    return 0


def cmd_add_tenant(a):
    store = load_store(a)
    tenant = Tenant(id=a.id, name=a.name,
                    unit_id=a.unit, since_iso=a.since)
    store.add_tenant(tenant)
    print("added tenant %s" % tenant.id)
    return 0


def cmd_add_lease(a):
    store = load_store(a)
    lease = Lease(
    id=a.id, tenant_id=a.tenant, property_id=a.property,
    start=a.start, end=a.end,
    rent_cents=a.rent,
    auto_renew=(str(getattr(a, "auto_renew", "false")).lower() == "true"),
    )
    store.record_lease(lease)
    print("added lease %s" % lease.id)
    return 0


def cmd_add_ticket(a):
    store = load_store(a)
    ticket = MaintenanceTicket(
        id=a.id, property_id=a.property,
        unit_id=a.unit or "",
        title=a.title, priority=a.priority, status=a.status,
        opened_when=a.opened, opened_by=a.by or "",
        )
    store.record_ticket(ticket)
    print("added ticket %s" % ticket.id)
    return 0


def cmd_record_payment(a):
    store = load_store(a)
    payment = Payment(
        id=a.id, tenant_id=a.tenant,
        amount_cents=a.amount, when=a.when,
        purpose=a.purpose, status=a.status,
        )
    store.record_payment(payment)
    print("recorded payment %s (%d cents)" %
            (payment.id, payment.amount_cents))
    return 0


def _policy_from_args(a):
    cap = a.cap if hasattr(a, "cap") else None
    if getattr(a, "flat", None) is not None:
        return LateFeePolicy(grace_days=a.grace, mode="flat",
                             flat_cents=a.flat, max_cents=cap)
    return LateFeePolicy(grace_days=a.grace, mode="pct",
                         pct=a.pct, max_cents=cap)


def cmd_late_fee(a):
    store = load_store(a)
    policy = _policy_from_args(a)
    stmt = tenant_ledger(
        store.leases, store.payments,
        a.tenant,
        month_start=a.period + "-01",
        policy=policy)
    print("%d" % stmt.late_fee)
    return 0


def cmd_ledger(a):
    store = load_store(a)
    policy = _policy_from_args(a)
    asof = _asof(a)
    if getattr(a, "csv", None):
        with open(a.csv, "w", encoding="utf-8") as handle:
            rows, _total = collect_rent_csv(
                handle, store.payments, store.leases,
                store.properties, store.units,
                policy=policy, asof=asof)
        print("wrote %d tenant rows + total to %s"
              % (len(rows), a.csv))
        return 0
    rows, _total = rent_collection(
        store.payments, store.leases,
        store.properties, store.units,
        policy=policy, asof=asof)
    for r in rows:
        print("    tenant=%s due=%9d paid=%9d bal=%9d  %s"
              % (r.get("tenant_id", "?"),
                 r.get("due_cents", 0),
                 r.get("paid_cents", 0),
                 r.get("outstanding_cents", 0),
                 r.get("status", "?")))
    return 0


def cmd_renewals(a):
    store = load_store(a)
    print(lease_renewal_report(
        store.leases, within_days=a.within, asof=_asof(a)))
    return 0


def cmd_maint(a):
    store = load_store(a)
    asof = _asof(a)
    if a.aging:
        print(maintenance_aging_report(store.tickets, asof=asof))
        return 0
    tickets = by_status(store.tickets, status=a.status)
    for t in tickets:
        print("  %s  [%s/%s]  %s"
              % (t.id, t.priority, t.status, t.title))
    print("  (%d tickets)" % len(tickets))
    return 0


def cmd_reminders(a):
    store = load_store(a)
    print(reminders_report(
        store.leases,
        threshold_days=a.within, asof=_asof(a)))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="rent-ledger",
        description="Local-first rental ledger, leases, and maintenance tracker.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--snap", default="snap.json",
        help="snapshot JSON path (jsonl ledgers are sibling files)")
    common.add_argument("--asof", default=None,
        help="ISO date to treat as 'now' (deterministic output)")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    sp = sub.add_parser("add-property", parents=[common])
    sp.add_argument("--id", required=True)
    sp.add_argument("--name", default="")
    sp.add_argument("--address", default="")
    sp.add_argument("--units", type=int, default=0)

    sp = sub.add_parser("add-unit", parents=[common])
    sp.add_argument("--id", required=True)
    sp.add_argument("--property", required=True)
    sp.add_argument("--number", default="1")
    sp.add_argument("--rent", type=int, required=True,
                    help="rent in cents")

    sp = sub.add_parser("add-tenant", parents=[common])
    sp.add_argument("--id", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--unit", required=True)
    sp.add_argument("--since", default="2000-01-01")

    sp = sub.add_parser("add-lease", parents=[common])
    sp.add_argument("--id", required=True)
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--property", required=True)
    sp.add_argument("--start", required=True, help="YYYY-MM-DD")
    sp.add_argument("--end", required=True, help="YYYY-MM-DD")
    sp.add_argument("--rent", type=int, required=True,
                    help="rent in cents")
    sp.add_argument("--auto-renew", dest="auto_renew",
                    action="store", const="true", default="false",
                    nargs="?", choices=["true", "false"])

    sp = sub.add_parser("add-ticket", parents=[common])
    sp.add_argument("--id", required=True)
    sp.add_argument("--property", required=True)
    sp.add_argument("--unit", default="")
    sp.add_argument("--title", required=True)
    sp.add_argument("--priority", default="medium",
        choices=["low", "medium", "high", "urgent"])
    sp.add_argument("--status", default="open",
        choices=["open", "in_progress", "deferred", "done"])
    sp.add_argument("--opened", default="2020-01-01", help="YYYY-MM-DD")
    sp.add_argument("--by", default="")

    sp = sub.add_parser("record-payment", parents=[common])
    sp.add_argument("--id", required=True)
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--amount", type=int, required=True,
                    help="amount in cents")
    sp.add_argument("--when", required=True, help="YYYY-MM-DD")
    sp.add_argument("--purpose", default="rent",
        choices=["rent", "maintenance", "deposit", "other"])
    sp.add_argument("--status", default="recorded",
        choices=["planned", "recorded"])

    sp = sub.add_parser("late-fee", parents=[common])
    sp.add_argument("--tenant", required=True)
    sp.add_argument("--period", required=True, help="YYYY-MM")
    sp.add_argument("--grace", type=int, default=0)
    sp.add_argument("--pct", type=int, default=5)
    sp.add_argument("--flat", type=int, default=None,
                    help="flat fee in cents")
    sp.add_argument("--cap", type=int, default=None,
                    help="fee cap in cents")

    sp = sub.add_parser("ledger", parents=[common])
    sp.add_argument("--period", required=True, help="YYYY-MM")
    sp.add_argument("--csv", default=None, metavar="OUT")
    sp.add_argument("--grace", type=int, default=0)
    sp.add_argument("--pct", type=int, default=5)
    sp.add_argument("--flat", type=int, default=None)
    sp.add_argument("--cap", type=int, default=None)

    sp = sub.add_parser("renewals", parents=[common])
    sp.add_argument("--within", type=int, default=30)

    sp = sub.add_parser("maint", parents=[common])
    sp.add_argument("--status", default="open")
    sp.add_argument("--aging", action="store_true")

    sp = sub.add_parser("reminders", parents=[common])
    sp.add_argument("--within", type=int, default=30)

    return p


HANDLERS = {
     "add-property": cmd_add_property,
     "add-unit": cmd_add_unit,
     "add-tenant": cmd_add_tenant,
     "add-lease": cmd_add_lease,
     "add-ticket": cmd_add_ticket,
     "record-payment": cmd_record_payment,
     "late-fee": cmd_late_fee,
     "ledger": cmd_ledger,
     "renewals": cmd_renewals,
     "maint": cmd_maint,
     "reminders": cmd_reminders,
}


def main(argv=None):
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    handler = HANDLERS.get(args.command)
    if handler is None:
        parser.error("unknown command: %r" % args.command)
    try:
        return handler(args)
    except (ValueError, KeyError, OSError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
