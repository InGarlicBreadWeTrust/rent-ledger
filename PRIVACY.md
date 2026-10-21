# Privacy

`rent-ledger` handles **no network** and collects **no data** of its own. This page
states exactly what the tool does — and does not — with the data it touches.

## In one line
It reads and writes files on your own disk only, and it phones home to no one.

## What the tool does NOT do
- **No telemetry, no analytics, no crash reporting, no usage tracking.** There is
  nothing in the code that measures, records, or reports what you do.
- **No network of any kind.** No sockets, no HTTP/HTTPS, no background sync.
  (`pyproject.toml` has zero runtime dependencies and the source opens no sockets.)
- **It never uploads your data.** A ledger file cannot leave your machine, because
   the tool has no way to reach a network.

## What the tool DOES touch
Only the files you give it, read or written as you name them:
- a JSON snapshot (plus per-kind `.jsonl` append files) you point it at, and
- reports/reports you opt into (`--csv`, markdown), written only to paths you
  choose.
Nothing is derived, transformed, or aggregated for any purpose beyond building
those reports. The tool does not learn, remember between runs, or index your data.

## Data sensitivity here is the highest in the collection
A rent ledger holds **other people's personal and financial data**: tenant names,
contact details, lease dates, and payment amounts. The tool itself is the weak
link only in that it does not encrypt at rest — there is nothing to leak *via the*
tool, but a leaked *file* is sensitive.

## Your controls
- Store ledger files on an **encrypted volume** (FileVault / LUKS / BitLocker).
- Restrict the data files: `chmod 600` on the `.json` snapshot and the `.jsonl`
   files so only your OS account can read them.
- Treat **exported reports and CSVs as sensitive** — they are human-readable and
   contain the same personal data; write them to a location with access control and
   **do not commit them to a public repository**.
- Retention is entirely yours: delete a file and the data is gone (the tool keeps
   no copy, no backup, no cache).

## Data sharing
None. The tool contacts no third party, has no accounts, no API keys, and no
data-retention policy because it retains no data itself — your data lives only in
the files you create on your own machine.

---

## Independent privacy audit (2026-10-21)

**Performed by:** `InGarlicBreadWeTrust` · **Type:** static source + dependency
review · **Result:** no privacy leakage; posture strong.

- No telemetry / analytics / crash reporting / background sync (none can exist —
   there is no network and no external service configured).
- No network I/O anywhere; zero runtime dependencies.
- No data leaves the machine: the tool neither uploads nor exfiltrates, and the
   ledger file is created only by an explicit write to a user-chosen path.
- No third-party services or accounts.

**Recommendation (not a vulnerability):** because the ledger contains third parties'
   PII and financial data, keep all data files on an **encrypted volume**,
   `chmod 600` them, and **never export reports to a public location**. No code
   change required.
