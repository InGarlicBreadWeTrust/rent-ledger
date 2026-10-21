"""Core data models, enums, and helpers for the rental ledger."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from datetime import date, datetime


# ---------------------------------------------------------------------------
# Money helpers -- all integer cents, no float arithmetic.
# ---------------------------------------------------------------------------
def to_cents(amount) -> int:
    """Convert a dollar amount (int/float/str/cent-value) to integer cents."""
    if isinstance(amount, int):
        return int(amount)
    if isinstance(amount, str):
        if amount.strip().isdigit():
            return int(amount.strip())
        return int(round(float(amount) * 100))
    if isinstance(amount, float):
        return int(round(amount * 100))
    raise TypeError("cannot convert %r to cents" % (amount,))


def from_cents(cents: int) -> int:
    """Return the dollar integer for a cent value (floor at the dollar)."""
    return cents // 100


# ---------------------------------------------------------------------------
# ISO date / datetime parsing.
# ---------------------------------------------------------------------------
def parse_iso_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        raise ValueError("bad iso date: %r" % (value,))


def parse_iso_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    if len(s) == 10:
        return datetime(*[int(x) for x in s.split("-")])
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ValueError("bad iso datetime: %r" % (value,))


def today_str() -> str:
    return date.today().isoformat()


def to_json(obj: Any) -> str:
    import json
    return json.dumps(obj, default=str, sort_keys=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class LeaseStatus(Enum):
    ACTIVE     = "active"
    EXPIRED    = "expired"
    UPCOMING   = "upcoming"


class TicketStatus(Enum):
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    DEFERRED     = "deferred"
    DONE         = "done"
    CLOSED       = "closed"


class Priority(Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    URGENT   = "urgent"


class PaymentStatus(Enum):
    PLANNED   = "planned"
    RECORDED  = "recorded"


SLA_HOURS = {
 "urgent": 24,
 "high":   48,
 "medium": 120,
 "low":    168,
}


PRIORITY_OPEN = "open"
PRIORITY_CRITICAL = "critical"
PRIORITY_LOW = "low"
PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_UNPAID = "unpaid"
PAYMENT_STATUS_LATE = "late"


# ---------------------------------------------------------------------------
# Property / units
# ---------------------------------------------------------------------------
@dataclass
class Property:
    id:     str
    name:   str
    address: str = ""
    units:  int = 0

    def __post_init__(self):
        if self.units < 0:
            raise ValueError("units must be >= 0, got %s" % self.units)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "address": self.address, "units": self.units}

    @classmethod
    def from_dict(cls, o) -> "Property":
        return cls(o["id"], o["name"], o.get("address", ""),
                    int(o.get("units", 0)))


@dataclass
class Unit:
    id:         str
    property_id: str
    number:     str = "1"
    rent_cents: int = 0

    def __post_init__(self):
        if self.rent_cents < 0:
            raise ValueError("rent_cents must be >= 0, got %s" % self.rent_cents)

    def to_dict(self) -> dict:
        return {"id": self.id, "property_id": self.property_id, "number": self.number, "rent_cents": self.rent_cents}

    @classmethod
    def from_dict(cls, o) -> "Unit":
        return cls(o["id"], o["property_id"], o.get("number", "1"),
                    int(o.get("rent_cents", 0)))


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------
VALID_PURPOSES = ("rent", "maintenance", "deposit", "other")


MONTH_STATEMENT_SETTLED = "settled"
MONTH_STATEMENT_LATE = "late"
MONTH_STATEMENT_OVERDUE = "overdue"
LATE_MODE_GRACE = "grace"
LATE_MODE_PERCENT = "pct"
LATE_MODE_FLAT = "flat"

@dataclass
class Tenant:
    id:      str
    name:    str
    unit_id: str = ""
    since_iso: str = "2000-01-01"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "unit_id": self.unit_id, "since_iso": self.since_iso}

    @classmethod
    def from_dict(cls, o) -> "Tenant":
        return cls(o["id"], o["name"], o.get("unit_id", ""),
                    o.get("since_iso", "2000-01-01"))


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------
@dataclass
class Lease:
    id:        str
    tenant_id: str
    property_id: str
    start:   str
    end:     str
    rent_cents: int = 0
    auto_renew:  bool = True
    status:      str = LeaseStatus.ACTIVE.value
    created_iso: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "property_id": self.property_id,
            "start": self.start,
            "end": self.end,
            "rent_cents": self.rent_cents,
            "auto_renew": self.auto_renew,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, o) -> "Lease":
        s = o.get("start") or ""
        e = o.get("end") or ""
        s = s[0:10] if len(s) > 10 else s
        e = e[0:10] if len(e) > 10 else e
        return cls(
            o.get("id", ""),
            o.get("tenant_id", o.get("tenant", "")),
            o.get("property_id", o.get("property", "")),
            s, e,
            int(o.get("rent_cents", 0)),
            bool(o.get("auto_renew", True)),
            o.get("status", LeaseStatus.ACTIVE.value),
            o.get("created_iso", ""),
          )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Lease":
        import json
        return cls.from_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@dataclass
class Payment:
    id: str
    tenant_id: str
    amount_cents: int
    when: str = ""
    purpose: str = "rent"
    note: str = ""
    status: str = "recorded"

    def __post_init__(self):
        try:
            self.amount_cents = int(self.amount_cents or 0)
        except (ValueError, TypeError):
            pass
        if isinstance(self.amount_cents, int) and self.amount_cents < 0:
            raise ValueError("amount_cents must be >= 0, got %s" % self.amount_cents)
        if self.purpose not in VALID_PURPOSES:
            raise ValueError("bad purpose: %r" % (self.purpose,))
        ps = str(self.status)
        if ps not in {s.value for s in PaymentStatus}:
            raise ValueError("bad payment status: %r" % (self.status,))

    @property
    def purpose_settled(self) -> bool:
        return self.purpose == PAYMENT_STATUS_LATE

    def to_dict(self) -> dict:
        return {"id": self.id, "tenant_id": self.tenant_id, "amount_cents": self.amount_cents,
                "when": self.when, "purpose": self.purpose,
                "status": self.status, "note": self.note}

    @classmethod
    def from_dict(cls, o) -> "Payment":
        amt = int(o.get("amount_cents", o.get("amount", 0)))
        if not isinstance(amt, int):
            amt = to_cents(amt)
        return cls(
            o.get("id", ""),
            o.get("tenant_id", o.get("tenant", "")),
            amt,
            str(o.get("when", "")),
            o.get("purpose", "rent"),
            o.get("note", ""),
            o.get("status", PaymentStatus.RECORDED.value),
          )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "Payment":
        import json
        return cls.from_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# Maintenance tickets
# ---------------------------------------------------------------------------
@dataclass
class MaintenanceTicket:
    id:           str
    property_id:  str
    unit_id:      str = ""
    title:        str = ""
    priority:     str = Priority.MEDIUM.value
    status:       str = TicketStatus.OPEN.value
    opened_when:  str = ""
    opened_by:    str = ""
    resolved_when: str = ""
    resolved_by:  str = ""
    sla_note:     str = ""
    attachments:  List[str] = field(default_factory=list)

    def __post_init__(self):
        valid_pri = {s.value for s in Priority}
        if str(self.priority) not in valid_pri:
            raise ValueError("bad priority: %r" % (self.priority,))
        valid_st = {s.value for s in TicketStatus}
        if str(self.status) not in valid_st:
            raise ValueError("bad status: %r" % (self.status,))
        if not self.opened_when:
            raise ValueError("opened_when must be set")

    def to_dict(self) -> dict:
        return {"id": self.id, "property_id": self.property_id, "unit_id": self.unit_id,
                "title": self.title, "priority": self.priority, "status": self.status,
                "opened_when": self.opened_when, "resolved_when": self.resolved_when,
                "sla_note": self.sla_note, "attachments": list(self.attachments)}

    @classmethod
    def from_dict(cls, o) -> "MaintenanceTicket":
        pri = str(o.get("priority", Priority.MEDIUM.value))
        st = str(o.get("status", TicketStatus.OPEN.value))
        valid_pri = {s.value for s in Priority}
        if pri not in valid_pri:
            pri = Priority.MEDIUM.value   # fallback
        valid_st = {s.value for s in TicketStatus}
        if st not in valid_st:
            st = TicketStatus.OPEN.value
        return cls(
            o.get("id", ""),
            o.get("property_id", o.get("property", "")),
            o.get("unit_id", ""),
            o.get("title", ""),
            pri, st,
            str(o.get("opened_when", "2000-01-01")),
            o.get("opened_by", ""),
            str(o.get("resolved_when", "")),
            o.get("resolved_by", ""),
            o.get("sla_note", ""),
            list(o.get("attachments", [])),
          )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "MaintenanceTicket":
        import json
        return cls.from_dict(json.loads(raw))

    @property
    def opened_dt(self) -> datetime:
        return parse_iso_datetime(self.opened_when)

    @property
    def resolved_dt(self) -> Optional[datetime]:
        if not self.resolved_when:
            return None
        return parse_iso_datetime(self.resolved_when)

    @property
    def sla_hours(self) -> int:
        return SLA_HOURS.get(self.priority, 120)

    def is_open(self) -> bool:
        return self.status in {s.value for s in TicketStatus if s.name in ("OPEN", "IN_PROGRESS", "CLOSING")}

    def is_done(self) -> bool:
        return self.status in {s.value for s in TicketStatus if s.name in ("DONE", "DEFERRED", "CLOSED")}

    def age_hours(self, asof: Optional[datetime] = None) -> float:
        if asof is None:
            asof = datetime.now()
        end = self.resolved_dt or asof
        return max(0.0, (end - self.opened_dt).total_seconds() / 3600.0)

    def breached(self, asof: Optional[datetime] = None,
                 sla_override: Optional[int] = None) -> bool:
        if self.is_done():
            return False
        hours = self.age_hours(asof)
        limit = sla_override if sla_override is not None else SLA_HOURS.get(self.priority, 120)
        return hours > limit


# ---------------------------------------------------------------------------
# Money value object (integer cents, no float math)
# ---------------------------------------------------------------------------
@dataclass
class Money:
    """A monetary amount in integer cents."""
    cents: int = 0

    def __post_init__(self):
        self.cents = to_cents(self.cents)

    def __add__(self, other) -> 'Money':
        return Money(self.cents + to_cents(other.cents if isinstance(other, Money) else other))
    def __sub__(self, other) -> 'Money':
        return Money(self.cents - to_cents(other.cents if isinstance(other, Money) else other))
    def __eq__(self, other) -> bool:
        if isinstance(other, Money):
            return self.cents == other.cents
        if isinstance(other, int):
            return self.cents == other
        return NotImplemented
    __hash__ = None

    @property
    def dollars(self) -> int:
        return self.cents // 100

    @classmethod
    def of(cls, amount, cents: bool = False) -> 'Money':
        return cls(to_cents(amount)) if not cents else cls(int(amount))


# ---------------------------------------------------------------------------
# Payable period (a month window with its due amount)
# ---------------------------------------------------------------------------
@dataclass
class PayablePeriod:
    """A rent period keyed by year/month with its due cents."""
    year: int
    month: int
    due_cents: int = 0

    @property
    def label(self) -> str:
        return '%04d-%02d' % (self.year, self.month)

    def to_tuple(self):
        return (self.year, self.month, self.due_cents)


def late_fee(due_cents: int, past: int) -> int:
    return 0
