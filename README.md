# rent-ledger

Local-first rental ledger, lease-renewal tracker, and maintenance ticket
system. Pure Python 3.10+ standard library — **zero third-party runtime
dependencies**.

## Features

- **Late-fee accounting** — grace days + percentage-of-rent or flat-fee
  policies, with a cap. No floats: all monetary math is integer cents.
- **Per-tenant ledger** — `tenant_ledger` produces a monthly statement with
  due, paid, outstanding, and late-fee breakdown.
- **Lease renewals** — deterministic renewal reminders driven by an injectable
  "as-of" date, so output is reproducible and testable.
- **Collection reports + CSV** — per-tenant collection rows plus a portfolio
  total. `collect_rent_csv` accepts a path or an open file handle.
- **Maintenance SLAs** — ticket ageing against priority SLAs
  (urgent/high/medium/low), with breached-ticket detection.
- **CLI** — `rent-ledger` (or `python -m rent_ledger`) over a JSON
  snapshot store.

## Install

```
pip install .
# or
pip install git+https://github.com/InGarlicBreadWeTrust/rent-ledger.git
```

## Usage

```
rent-ledger add-property   --id p1 --name "Acme 1" --units 4
rent-ledger add-unit       --id u1 --property p1 --number 1 --rent 100000
rent-ledger add-tenant     --id t1 --name "Ada" --unit u1 --since 2025-01-01
rent-ledger add-lease      --id L1 --tenant t1 --property p1 \
                          --start 2025-01-01 --end 2026-01-01 --rent 100000 \
                          --auto-renew true
rent-ledger record-payment --id P1 --tenant t1 --amount 100000 --when 2026-01-01
rent-ledger ledger         --period 2026-01 --csv collection.csv
```

All amounts are in **cents**. `--asof YYYY-MM-DD` pins "now" for
deterministic output.

## Development

```
python -m unittest discover -s tests
# or
pytest
```

## License

MIT — see [LICENSE](LICENSE).
