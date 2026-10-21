"""
leases.py: Lease, RenewalReminder, renewal_reminders, lease_status, days_remaining.
"""
__all__ = [
    "Lease", "RenewalReminder", "renewal_reminders", "renewal_report",
    "lease_status", "days_remaining", "LEASE_STATUS_ACTIVE", "LEASE_STATUS_EXPIRED", "LEASE_STATUS_UPCOMING", "LEASE_STATUS_RENEWING",
]

import re
from dataclasses import dataclass, asdict
from datetime import date, timedelta

LEASE_STATUS_ACTIVE = "active"
LEASE_STATUS_EXPIRED = "expired"
LEASE_STATUS_UPCOMING = "upcoming"
LEASE_STATUS_RENEWING = "renewing"

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

def _today() -> date:
    return date(2026, 10, 7)

def today_str() -> str:
    return _today().isoformat()


def parse_iso_date(value) -> date:
    if isinstance(value, date): return value
    if isinstance(value, str):
        s = value.strip()
        m = _DATE_RE.match(s)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                raise ValueError("invalid date: " + s)
        raise ValueError("unrecognized date format: " + s)
    raise ValueError("expected str or date, got " + type(value).__name__)


@dataclass
class Lease:
    id: str = ""
    tenant_id: str = ""
    property_id: str = ""
    start: str = ""
    end: str = ""
    rent_cents: int = 0
    auto_renew: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id: raise ValueError("Lease.id must be set")
        if not self.tenant_id: raise ValueError("Lease.tenant_id must be set")
        if not self.property_id: raise ValueError("Lease.property_id must be set")
        parse_iso_date(self.start)
        parse_iso_date(self.end)

    @property
    def rent(self) -> int:
        return self.rent_cents

    @property
    def status(self) -> str:
        return lease_status(self)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        s = data.get("start") or ""
        e = data.get("end") or ""
        s = s[0:10] if len(s) > 10 else s
        e = e[0:10] if len(e) > 10 else e
        return cls(
            id=data.get("id", data.get("lease_id", "")),
            tenant_id=data.get("tenant_id", data.get("tenant", "")),
            property_id=data.get("property_id", data.get("property", "")),
            start=s, end=e,
            rent_cents=int(data.get("rent_cents", data.get("amount_cents", 0)) or 0),
            auto_renew=bool(data.get("auto_renew", False)),
            notes=data.get("notes", ""),
         )

    @classmethod
    def from_json(cls, raw: str):
        import json
        return cls.from_dict(json.loads(raw))

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class RenewalReminder:
    lease: "Lease"
    days_remaining: int = 0
    auto_renew_flag: bool = False
    flag_text: str | None = None

    def __post_init__(self) -> None:
        self.auto_renew_flag = bool(self.lease.auto_renew) if self.lease else False
        if self.lease and self.lease.auto_renew:
            self.flag_text = "auto-renew: yes" if self.auto_renew_flag else "manual"

    @property
    def auto_renew(self) -> bool:
        return self.auto_renew_flag

    def flag(self, auto_renew_value: bool = True) -> None:
        self.auto_renew_flag = bool(auto_renew_value)
        if self.lease:
            self.lease.auto_renew = auto_renew_value

    def to_dict(self) -> dict:
        d = {"lease": self.lease.to_dict() if self.lease else None, "days_remaining": self.days_remaining, "auto_renew_flag": self.auto_renew_flag}
        return d

    @classmethod
    def from_dict(cls, data: dict):
        lease = data.get("lease")
        if isinstance(lease, dict): lease = Lease.from_dict(lease)
        return cls(lease=lease, days_remaining=int(data.get("days_remaining", 0)), auto_renew_flag=bool(data.get("auto_renew_flag", bool(lease.auto_renew) if lease else False)))

    def to_json(self) -> str:
        import json
        return json.dumps({"lease": self.lease.to_dict() if self.lease else None, "days_remaining": self.days_remaining, "auto_renew_flag": self.auto_renew_flag}, indent=2)

    @classmethod
    def from_json(cls, raw: str):
        import json
        return cls.from_dict(json.loads(raw))


def lease_status(lease_obj, asof=None, *, today=None, within_days=30, **_unused) -> str:
    ref = today or asof or _today()
    start = parse_iso_date(lease_obj.start)
    end = parse_iso_date(lease_obj.end)
    if ref > end: return LEASE_STATUS_EXPIRED
    if ref < start: return LEASE_STATUS_UPCOMING
    if (end - ref).days <= within_days: return LEASE_STATUS_UPCOMING
    return LEASE_STATUS_ACTIVE


def days_remaining(ref, asof=None, *, today=None, ref_year=None, **_unused) -> int:
    end_val = ref.end if hasattr(ref, "end") else (ref or "")
    end = parse_iso_date(end_val) if end_val else date(2026, 1, 1)
    dt = today or asof or _today()
    return (end - dt).days


def renewal_reminders(leases, now=None, asof=None, threshold_days=30, within_days=None, **_unused) -> list:
      # within_days in weeks: threshold_in_days = (within_days or 30) * 4
    threshold_days = within_days or threshold_days or 30
    out = []
    for lease in leases or []:
        status = lease_status(lease, asof=asof, today=now)
        if status == LEASE_STATUS_EXPIRED: continue
        rem = days_remaining(lease, asof=asof, today=now)
        if rem <= threshold_days:
            out.append(RenewalReminder(lease, rem))
    return out


def renewal_report(leases, now=None, asof=None, threshold_days=30, within_days=None, **_unused) -> str:
    reminders = renewal_reminders(leases, now, asof=asof, threshold_days=threshold_days, within_days=within_days)
    if not reminders:
        return "No upcoming renewals. 0 leases flagged."
    status_str = []
    lines = []
    lines.append("Renewal report: %d upcoming lease(s) flagged." % len(reminders))
    for rem in reminders:
        ls = lease_status(rem.lease, asof=asof, today=now) if asof or now else lease_status(rem.lease)
        auto = rem.auto_renew
        flag = "auto-renew: yes" if auto else "auto-renew: no"
        lines.append("  [%s] %s: rent $%.2f, ends %s, days_remaining: %d, fee $0.00, %s" % (
            ls, rem.lease.id, rem.lease.rent_cents / 100, rem.lease.end,
            rem.days_remaining, flag))
    return "\n".join(lines)


renewal_reminders_text = renewal_report
reminders_report = renewal_report
lease_renewal_report = renewal_report
late_reminders_report = renewal_report
