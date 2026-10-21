"""
tickets.py: ticket lifecycle, SLA breach tracking, and TicketView.
"""
__all__ = [
       "TicketView",
       "OPEN_STATUSES",
       "DONE_STATUSES",
       "is_breached",
       "sla_breached",
       "sla_hours_for",
       "maintenance_aging_report",
]

from datetime import date, datetime

from .models import (
       parse_iso_date,
       parse_iso_datetime,
       SLA_HOURS,
       PRIORITY_OPEN,
       TicketStatus,
)

OPEN_STATUSES = {TicketStatus.OPEN.value, TicketStatus.IN_PROGRESS.value}
DONE_STATUSES = {TicketStatus.DEFERRED.value, TicketStatus.DONE.value}


def _as_date(value):
       if isinstance(value, datetime):
           return value
       if isinstance(value, date):
           return value
       if isinstance(value, str) and value:
           return parse_iso_datetime(value)
       return datetime(2026, 1, 1)


def sla_hours_for(priority: str) -> int:
       """SLA hours for a priority level."""
       p = (priority or "medium").lower()
       return SLA_HOURS.get(p, 120)


class TicketView:
       """Read-only view over a MaintenanceTicket, with SLA helpers."""

       def __init__(self, ticket, asof=None):
           self.ticket = ticket
           self.id = getattr(ticket, "id", "")
           self.property_id = getattr(ticket, "property_id", "")
           self.unit_id = getattr(ticket, "unit_id", "")
           self.title = getattr(ticket, "title", "")
           self.priority = getattr(ticket, "priority", "medium")
           self.status = getattr(ticket, "status", "open")
           self.opened_when = getattr(ticket, "opened_when", "2026-01-01")
           self.resolved_when = getattr(ticket, "resolved_when", "")
           self.resolved_by = getattr(ticket, "resolved_by", "")
           self.notes = getattr(ticket, "notes", "")
           if asof is not None:
               self._asof = asof

       @property
       def is_closed(self) -> bool:
           return str(self.status) in {
               TicketStatus.CLOSED.value,
               TicketStatus.DEFERRED.value,
               TicketStatus.DONE.value,
           }

       @property
       def is_open(self) -> bool:
           return str(self.status) in {
               TicketStatus.OPEN.value,
               TicketStatus.IN_PROGRESS.value,
           }

       @property
       def sla_hours(self) -> int:
           return sla_hours_for(self.priority)

       @property
       def is_breached(self) -> bool:
           asof = getattr(self, "_asof", None) or datetime(2026, 1, 1)
           if isinstance(asof, str):
               asof = parse_iso_date(asof)
           return self.breached(asof=asof) > 0

       def opened_dt(self) -> datetime:
           return _as_date(self.opened_when)

       def age_hours(self, asof=None, now=None) -> int:
           ref = asof or now or datetime(2026, 1, 31)
           opened = self.opened_dt()
           if isinstance(ref, str):
               ref = parse_iso_date(ref)
           if isinstance(ref, date) and not isinstance(ref, datetime):
               ref = datetime(ref.year, ref.month, ref.day)
           if isinstance(opened, date) and not isinstance(opened, datetime):
               opened = datetime(opened.year, opened.month, opened.day)
           delta = (ref - opened).total_seconds() / 3600.0
           return int(delta)

       def breached(self, asof=None, now=None, sla_hours=None) -> int:
           ref = asof or now
           if ref is None:
               ref = datetime(2026, 1, 31)
           h = int(sla_hours) if sla_hours is not None else self.sla_hours
           age = self.age_hours(asof=ref, now=ref)
           if self.is_closed and self.resolved_when:
               resolved = _as_date(self.resolved_when)
               if isinstance(resolved, (date, datetime)):
                   if isinstance(resolved, date) and not isinstance(resolved, datetime):
                       resolved = datetime(resolved.year, resolved.month, resolved.day)
                   age = int((resolved - self.opened_dt()).total_seconds() / 3600.0)
           return max(0, age - h)

       def to_dict(self) -> dict:
           return {
               "id": self.id,
               "property_id": self.property_id,
               "unit_id": self.unit_id,
               "title": self.title,
               "priority": self.priority,
               "status": self.status,
               "opened_when": str(self.opened_when),
               "resolved_when": str(self.resolved_when or ""),
               "sla_hours": self.sla_hours,
               "breached": self.breached(),
           }


def sla_breached(tickets, asof=None, now=None, sla_hours=None):
    """Return list of breached tickets from a collection."""
    if not isinstance(tickets, list):
        tickets = [tickets]
    results = []
    for t in tickets:
        view = TicketView(t, asof=asof or now)
        h = int(sla_hours) if sla_hours is not None else view.sla_hours
        age = view.age_hours(asof=asof, now=now)
        if view.is_closed:
            continue
        if age > h:
            results.append(t)
    return results


def is_breached(ticket, asof=None, now=None, sla_hours=None) -> bool:
    """True when a ticket has passed its SLA window."""
    view = TicketView(ticket, asof=asof or now)
    h = int(sla_hours) if sla_hours is not None else view.sla_hours
    age = view.age_hours(asof=asof or now, now=asof or now)
    return age > h


def maintenance_aging_report(tickets: list, asof=None):
    """Return aged open maintenance tickets, oldest first, as a string."""
    lines = []
    for t in tickets or []:
        view = TicketView(t, asof=asof)
        if view.is_open:
            lines.append(f"{view.id} {view.priority} {view.title}")
    lines.sort(key=lambda s: s.split()[0] if s else "")
    return "\n".join(lines)



def by_status(tickets, status):
     """Filter tickets by a single status string."""
     return [t for t in tickets if getattr(t, "status", "") == status]


if __name__ == "__main__":
     print(__doc__ or "tickets.py")
