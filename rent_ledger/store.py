"""Append-only persistence for the ledger.

``LedgerStore`` keeps a JSON snapshot at a path plus one JSONL file per
entity kind next to it. Records are appended (never clobbered); a fresh
handle reloads the snapshot to rebuild the in-memory view.
"""
from __future__ import annotations

import json
import os
from typing import List, TypeVar

from .models import (Property, Unit, Tenant, Lease, MaintenanceTicket,
                     Payment)

T = TypeVar("T", Property, Unit, Tenant, Lease, MaintenanceTicket, Payment)

KIND = {
 "leases": Lease,
 "payments": Payment,
 "tenants": Tenant,
 "properties": Property,
 "units": Unit,
 "tickets": MaintenanceTicket,
}


def _jsonl_path(snap: str, kind: str) -> str:
    base = os.path.dirname(os.path.abspath(snap)) or "."
    return os.path.join(base, kind + ".jsonl")


class LedgerStore:
    """A snapshot + per-kind JSONL append log."""
    def __init__(self, snapshot: str):
        self.snapshot = snapshot
        self.leases: List[Lease] = []
        self.payments: List[Payment] = []
        self.tenants: List[Tenant] = []
        self.properties: List[Property] = []
        self.units: List[Unit] = []
        self.tickets: List[MaintenanceTicket] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.snapshot):
            return
        with open(self.snapshot, encoding="utf-8") as f:
            data = json.load(f)
        for kind, items in data.items():
            cls = KIND.get(kind)
            if not cls:
                continue
            getattr(self, kind).extend(cls.from_dict(o) for o in items)

    def _write_snapshot(self) -> None:
        tmp = self.snapshot + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._snapshot_data(), f, indent=2)
        os.replace(tmp, self.snapshot)

    def _snapshot_data(self) -> dict:
        return {
            "properties": [p.to_dict() for p in self.properties],
            "units": [u.to_dict() for u in self.units],
            "tenants": [t.to_dict() for t in self.tenants],
            "leases": [l.to_dict() for l in self.leases],
            "payments": [p.to_dict() for p in self.payments],
            "tickets": [t.to_dict() for t in self.tickets],
        }

    def _append(self, kind: str, obj) -> None:
        with open(_jsonl_path(self.snapshot, kind), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(obj.to_dict()) + "\n")
        self._write_snapshot()

    def load(self) -> "LedgerStore":
        """Return a fresh store rebuilt from the snapshot on disk."""
        return LedgerStore(self.snapshot)

    def record_property(self, obj: Property) -> None:
        self._record("properties", obj)

    def record_unit(self, obj: Unit) -> None:
        self._record("units", obj)

    def record_tenant(self, obj: Tenant) -> None:
        self._record("tenants", obj)

    def record_lease(self, obj: Lease) -> None:
        self._record("leases", obj)

    def record_payment(self, obj: Payment) -> None:
        self._record("payments", obj)

    def record_ticket(self, obj: MaintenanceTicket) -> None:
        self._record("tickets", obj)

    def add_tenant(self, obj: Tenant) -> None:
        self.record_tenant(obj)

    def add_property(self, obj: Property) -> None:
        self.record_property(obj)

    def add_unit(self, obj: Unit) -> None:
        self.record_unit(obj)

    def record(self, obj, kind: str) -> None:
        self._record(kind, obj)

    def _record(self, kind: str, obj) -> None:
        getattr(self, kind).append(obj)
        self._append(kind, obj)


class LeaseStore(LedgerStore):
    """A store focused on leases."""
    def record(self, obj: Lease) -> None:
        self.record_lease(obj)


class PaymentStore(LedgerStore):
    """A store focused on payments."""
    def record(self, obj: Payment) -> None:
        self.record_payment(obj)


class TicketStore(LedgerStore):
    """A store focused on maintenance tickets."""
    def record(self, obj: MaintenanceTicket) -> None:
        self.record_ticket(obj)


class SnapshotStore(LedgerStore):
    """Generic alias -- everything persists to the snapshot."""
    def record(self, obj, kind: str) -> None:
        self._record(kind, obj)
