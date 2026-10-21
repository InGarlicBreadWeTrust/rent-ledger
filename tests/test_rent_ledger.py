"""Unit + CLI smoke tests for rent-ledger.

Covers: exact integer-cents money, on-time vs past-grace vs capped late fees,
lease-renewal flagging, ticket SLA breach/aging, CSV rent-collection, model
validation, JSONL/snapshot round-trip, and CLI smoke. Deterministic via
injected ``now``/``asof`` -- no network, no real clock at test time.
"""
import contextlib
import io
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from rent_ledger import (
     LateFeePolicy,
     Lease,
     LeaseStatus,
     MaintenanceTicket,
     Payment,
     PaymentStatus,
     Priority,
     Property,
     TicketStatus,
     Tenant,
     Unit,
     collect_rent_csv,
     lease_status,
    lease_renewal_report,
    maintenance_aging_report,
    rent_collection,
    tenant_ledger,
    renewal_reminders,
    is_breached,
    sla_breached,
    LedgerStore,
)
from rent_ledger.cli import main
from rent_ledger.leases import days_remaining
from rent_ledger.models import parse_iso_date, parse_iso_datetime


def _lease(tenant_id="t1", pstart="2026-01-01", pend="2026-12-31",
           rent=100000, auto_renew=True):
     return Lease(id="L1", tenant_id=tenant_id, property_id="p1",
              start=pstart, end=pend, rent_cents=rent, auto_renew=auto_renew)


# Exact cent math: a $1000 lease with a $1000 payment settles to exactly 0.
class TestMoney(unittest.TestCase):
      def test_fully_paid_is_zero(self):
         lease = _lease(rent=100000)
         pay = Payment("P1", "t1", 100000, "2026-01-05")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              period_start=date(2026,1,1),
                              period_end=date(2026,1,31),
                              policy=LateFeePolicy())
         self.assertEqual(stmt.due, 100000)
         self.assertEqual(stmt.paid, 100000)
         self.assertEqual(stmt.balance, 0)
         self.assertTrue(stmt.is_settled)

      def test_partial_payment_leaves_exact_remaining(self):
         lease = _lease(rent=100000)
         pay = Payment("P1", "t1", 40000, "2026-01-20")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy())
         self.assertEqual(stmt.due, 100000)
         self.assertEqual(stmt.paid, 40000)
         self.assertEqual(stmt.balance, 60000)
         self.assertEqual(stmt.outstanding, 60000)
         self.assertFalse(stmt.is_settled)

      def test_overpaid_shows_overpaid_cents(self):
         lease = _lease(rent=100000)
         pay = Payment("P1", "t1", 120000, "2026-01-05")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy())
         self.assertEqual(stmt.balance, -20000)
         self.assertEqual(stmt.overpaid, 20000)


# Late-fee policy: on-time=0, past-grace=5%, and a hard cap.
class TestLateFee(unittest.TestCase):
      def test_no_fee_on_time(self):
         lease = _lease(rent=100000)
         pay = Payment("P1", "t1", 100000, "2026-01-01")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy(grace_days=0))
         self.assertEqual(stmt.late_fee, 0)

      def test_one_day_past_grace_is_five_percent(self):
         lease = _lease(rent=1000000)
         # grace 1 day, paid 1 day past due -> 5% of 1,000,000 cents = 50,000
         pay = Payment("P1", "t1", 1000000, "2026-01-02")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy(grace_days=1,
                                                  mode="pct", pct=5))
         self.assertEqual(stmt.late_fee, 50000)
         self.assertTrue(stmt.late)

      def test_flat_fee_mode(self):
         lease = _lease(rent=100000)
         pay = Payment("P1", "t1", 100000, "2026-01-10")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy(grace_days=0,
                                                   mode="flat",
                                                   flat_cents=5000))
         self.assertEqual(stmt.late_fee, 5000)

      def test_pct_fee_is_capped_by_max_cents(self):
         lease = _lease(rent=100000)
         pay = Payment("P1", "t1", 100000, "2026-01-10")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy(grace_days=0,
                                                   mode="pct", pct=50,
                                                   max_cents=2500))
         self.assertEqual(stmt.late_fee, 2500)

      def test_grace_period_avoids_fee(self):
         lease = _lease(rent=100000)
         # paid 3 days late but inside a 7-day grace window -> no fee
         pay = Payment("P1", "t1", 100000, "2026-01-04")
         stmt = tenant_ledger([lease], [pay], "t1",
                              month_start="2026-01-01",
                              policy=LateFeePolicy(grace_days=7,
                                                   mode="pct", pct=5))
         self.assertEqual(stmt.late_fee, 0)
         self.assertFalse(stmt.late)


# Lease status and renewal flagging.
class TestLeases(unittest.TestCase):
      def _now(self):
         return date(2026,1,1)

      def test_active_and_expired_and_upcoming(self):
         now = self._now()
         active = Lease("a","t1","p1","2025-06-01","2026-12-31",100000)
         expired = Lease("e","t1","p1","2024-01-01","2025-12-31",100000)
         upcoming = Lease("u","t1","p1","2026-03-01","2026-12-31",100000)
         self.assertEqual(lease_status(active, now), LeaseStatus.ACTIVE.value)
         self.assertEqual(lease_status(expired, now),
                          LeaseStatus.EXPIRED.value)
         self.assertEqual(lease_status(upcoming, now),
                          LeaseStatus.UPCOMING.value)
         self.assertEqual(days_remaining(upcoming), 85)

      def test_renewal_20_days_flagged(self):
         now = self._now()
         lease = Lease("n1","t1","p1","2025-01-01","2026-01-21",100000,
                       auto_renew=True)
         reminders = renewal_reminders([lease], within_days=30, asof=now)
         self.assertEqual(len(reminders), 1)
         self.assertEqual(reminders[0].days_remaining, 20)
         self.assertTrue(reminders[0].auto_renew)

      def test_renewal_90_days_not_flagged(self):
         now = self._now()
         lease = Lease("n2","t1","p1","2025-01-01","2026-03-31",100000,
                       auto_renew=True)
         reminders = renewal_reminders([lease], within_days=30, asof=now)
         self.assertEqual(len(reminders), 0)

      def test_non_renewing_still_flagged(self):
         now = self._now()
         lease = Lease("n3","t1","p1","2025-01-01","2026-01-15",100000,
                       auto_renew=False)
         reminders = renewal_reminders([lease], within_days=30, asof=now)
         self.assertEqual(len(reminders), 1)
         self.assertFalse(reminders[0].auto_renew)

      def test_lease_renewal_report_text(self):
         now = self._now()
         lease = Lease("n4","t2","p1","2025-01-01","2026-01-10",50000,
                       auto_renew=True)
         text = lease_renewal_report([lease], within_days=30, asof=now)
         self.assertIn("n4", text)
         self.assertIn("auto-renew", text)


# Ticket SLA + aging.
class TestTickets(unittest.TestCase):
      def _now(self):
         return datetime(2026,1,10,12,0,0)

      def test_urgent_30_hours_breached(self):
         now = self._now()
         opened = now - timedelta(hours=30)
         t = MaintenanceTicket("M1","p1","", "Leak", "urgent", "open",
                               opened_when=opened.isoformat())
         self.assertTrue(is_breached(t, asof=now))
         self.assertTrue(sla_breached([t], asof=now)[0].breached)

      def test_medium_5_days_not_breached(self):
         now = self._now()
         opened = now - timedelta(days=5)
         t = MaintenanceTicket("M2","p1","", "Paint", "medium", "open",
                               opened_when=opened.isoformat())
         self.assertFalse(is_breached(t, asof=now))
         self.assertEqual(len(sla_breached([t], asof=now)), 0)

      def test_high_72_hours_breached(self):
         now = self._now()
         opened = now - timedelta(hours=72)
         t = MaintenanceTicket("M3","p1","","Door", "high", "open",
                               opened_when=opened.isoformat())
         self.assertTrue(is_breached(t, asof=now))

      def test_aging_report_lists_oldest(self):
         import datetime as _dt
         now = _dt.datetime(2026,1,10)
         t1 = MaintenanceTicket("M4","p1","","Old","medium","open",
                               opened_when="2026-01-01")
         t2 = MaintenanceTicket("M5","p1","","New","urgent","open",
                               opened_when="2026-01-09")
         text = maintenance_aging_report([t1, t2], asof=now)
         self.assertTrue(text.index("M4") < text.index("M5"),
                         "oldest ticket should appear first")


# Reports: rent-collection and CSV.
class TestReports(unittest.TestCase):
      def setUp(self):
         self.leases = [_lease("t1","2026-01-01","2026-12-31",100000,
                                auto_renew=True),
                       Lease("L2","t2","p1","2026-01-01","2026-12-31",
                             150000, auto_renew=False)]
         self.payments = [
             Payment("P1","t1",100000,"2026-01-05"),
             Payment("P2","t2",0,"2026-01-05"),
          ]
         self.properties = [Property("p1","Maple","1 St",2)]
         self.units = [Unit("u1","p1","1A",100000),
                       Unit("u2","p1","2A",150000)]
         self.tenants = [Tenant("t1","Ada","u1"),
                         Tenant("t2","Bo","u2")]

      def test_collection_rows_per_tenant_plus_total(self):
         rows, total = rent_collection(
             self.payments, self.leases, self.properties, self.units,
             self.tenants, "2026-01", policy=LateFeePolicy())
         self.assertEqual(len(rows), 2)
         self.assertEqual(len(rows) + 1, 2 + 1)
         self.assertEqual(total["due_cents"], 250000)
         self.assertEqual(total["paid_cents"], 100000)
         self.assertEqual(total["balance_cents"], 150000)
         self.assertEqual(total["status"], "outstanding")

      def test_csv_has_header_and_rows(self):
         out = io.StringIO()
         rows, total = collect_rent_csv(
             out, self.payments, self.leases, self.properties,
             self.units, self.tenants, "2026-01", policy=LateFeePolicy())
         text = out.getvalue()
         lines = [ln for ln in text.splitlines() if ln.strip()]
         self.assertEqual(len(lines), 1 + 2 + 1)  # header + 2 tenants + total
         self.assertIn("2026-01", text)
         self.assertTrue(any(ln.startswith("PORTFOLIO") for ln in lines))


# Model validation.
class TestValidation(unittest.TestCase):
      def test_negative_cents_rejected(self):
         self.assertRaises(ValueError,
             lambda: Unit("u","p","1", rent_cents=-1))
         self.assertRaises(ValueError,
             lambda: Payment("p","t", amount_cents=-100, when="2026-01-01"))
         self.assertRaises(ValueError,
             lambda: Property("p","N","", units=-1))

      def test_invalid_enum_rejected(self):
         lease = _lease()
         self.assertRaises(ValueError,
            lambda: MaintenanceTicket("m","p1","","x","banana",
                   "open", "2026-01-01"))
         self.assertRaises(ValueError,
            lambda: Payment("p","t","2026-01-01", purpose="banana"))

      def test_parse_bad_date_rejected(self):
         self.assertRaises(ValueError,
             lambda: parse_iso_date("not-a-date"))

      def test_coerce_float_rounds_to_half(self):
         self.assertEqual(round(1000.05 * 100), 100005)


# Store round-trip.
class TestStore(unittest.TestCase):
      def setUp(self):
         self.dir = tempfile.mkdtemp()
         self.snap = os.path.join(self.dir, "snap.json")

      def tearDown(self):
         for f in os.listdir(self.dir):
             os.remove(os.path.join(self.dir, f))

      def test_jsonl_appends_and_reloads(self):
         store = LedgerStore(self.snap)
         store.record_lease(_lease("t1"))
         store.record_payment(Payment("P1","t1",100000,"2026-01-05"))
         store.add_tenant(Tenant("t1","Ada","u1"))
         self.assertTrue(os.path.exists(self.snap))
         self.assertTrue(os.path.exists(
             os.path.join(self.dir, "leases.jsonl")))
         # fresh handle reloads everything
         store2 = LedgerStore(self.snap).load()
         self.assertEqual(len(store2.leases), 1)
         self.assertEqual(len(store2.payments), 1)
         self.assertEqual(len(store2.tenants), 1)
         self.assertEqual(store2.leases[0].tenant_id, "t1")

      def test_append_only_does_not_clobber(self):
         store = LedgerStore(self.snap)
         store.record_payment(Payment("P1","t1",100,"2026-01-01"))
         store.record_payment(Payment("P2","t1",200,"2026-01-01"))
           # a second, independent store appends and keeps both records
         store2 = LedgerStore(self.snap)
         store2.record_payment(Payment("P3","t1",300,"2026-01-01"))
         self.assertEqual(len(store2.load().payments), 3)


# CLI smoke.
class TestCli(unittest.TestCase):
      def setUp(self):
         self.dir = tempfile.mkdtemp()
         self.snap = os.path.join(self.dir, "snap.json")

      def tearDown(self):
         for f in os.listdir(self.dir):
             os.remove(os.path.join(self.dir, f))

      def _run(self, argv):
         buf = io.StringIO()
         with contextlib.redirect_stdout(buf):
             code = main(argv)
         return code, buf.getvalue()

      def test_no_command_prints_help_and_returns_zero(self):
         code, _ = self._run([])
         self.assertEqual(code, 0)

      def test_add_and_late_fee_via_cli(self):
         args = [
             "add-property", "--id", "p1", "--name", "Maple",
             "--snap", self.snap]
         self.assertEqual(self._run(args)[0], 0)
         self.assertEqual(self._run([
             "add-unit","--id","u1","--property","p1","--number","1A",
             "--rent","100000","--snap",self.snap])[0], 0)
         self.assertEqual(self._run([
             "add-tenant","--id","t1","--name","Ada","--unit","u1",
             "--snap",self.snap])[0], 0)
         self.assertEqual(self._run([
             "add-lease","--id","L1","--tenant","t1","--property","p1",
             "--start","2026-01-01","--end","2026-12-31","--rent","100000",
             "--snap",self.snap])[0], 0)
         code, out = self._run([
             "record-payment","--id","P1","--tenant","t1","--amount","100000",
             "--when","2026-01-10","--snap",self.snap])
         self.assertEqual(code, 0)
         # 1 month, paid on the 10th, grace 0, 5% of 100000 = 5000
         code, out = self._run([
             "late-fee","--tenant","t1","--period","2026-01",
             "--grace","0","--pct","5","--asof","2026-06-01","--snap",
             self.snap])
         self.assertEqual(code, 0)
         self.assertEqual(out.strip(), "5000")

      def test_help_exit_code_zero(self):
         # argparse --help raises SystemExit(0); capture and assert
         try:
             self._run(["--help"])
             self.fail("--help should raise SystemExit")
         except SystemExit as exc:
             self.assertEqual(exc.code, 0)

      def test_ledger_and_reminders_smoke(self):
         self.assertEqual(self._run([
             "add-property","--id","p1","--name","M","--snap",self.snap])[0],0)
         self.assertEqual(self._run([
             "add-tenant","--id","t1","--name","Ada","--unit","",
             "--snap",self.snap])[0],0)
         self.assertEqual(self._run([
             "add-lease","--id","L1","--tenant","t1","--property","p1",
             "--start","2026-01-01","--end","2026-01-15","--rent","100000",
             "--snap",self.snap])[0],0)
         code, out = self._run([
             "ledger","--period","2026-01","--snap",self.snap])
         self.assertEqual(code, 0)
         self.assertIn("t1", out)
         code, out = self._run([
             "renewals","--within","30","--asof","2026-01-01","--snap",
             self.snap])
         self.assertEqual(code, 0)


if __name__ == "__main__":
     unittest.main()
