# Security posture of `rent-ledger`

`rent-ledger` is an **offline** rent-ledger tracker. It reads and writes only
files on the user's own disk and is the one tool in this collection that stores
**sensitive personal data** (tenant names, lease terms, payment amounts). This
page is the threat model and the deliberate design guards.

## Threat model

| Input / asset | Trusted? | Why it is safe |
| --- | --- | --- |
| Ledger files on disk | Yes (user's own) | Read/written in-process; no content is ever executed. |
| CLI arguments (paths, amounts, names) | No, but low risk | Parsed as text/numbers and stored; never `eval`'d, `exec`'d, or sent anywhere. |
| Filesystem paths named by the user | Yes | Written with default OS permissions; no world-writable mode is ever set. |

## Design principles

1. **No code execution.** The package contains no `eval`, `exec`, `compile`,
   `subprocess`, `os.system`, `pickle`, `marshal`, or `ctypes`. A ledger file is
   always treated as *data* — it is parsed with the stdlib `json` module and can
   never run code.
2. **No network, no telemetry.** The package has **zero** runtime dependencies and
   never opens a socket, calls a URL, or spawns a process. A ledger file cannot be
   exfiltrated by this tool because the tool has no network capability.
3. **Atomic, crash-safe persistence.** Snapshots are written to a temporary file
   and then `os.replace`-moved into place, so a crash mid-write cannot corrupt the
   ledger. Appends to the per-kind JSONL files are line-delimited.
4. **No hardcoded secrets.** There are no credentials, API keys, or tokens in the
   source.

## Recommendations for this tool specifically

Because it holds personal financial data, operate the data with the same care as a
bank statement:
- restrict the data file to your account: `chmod 600 ledger.json` (and the sibling
  `.jsonl` files), and keep everything on an **encrypted volume** (FileVault /
  LUKS / Windows BitLocker). This tool does **not** encrypt at rest — that is the
  operating system's job; do not treat "local" as "safe" without disk encryption.
- The CSV/markdown **reports** (`reports.py`) are human-readable and may leak
  tenant names, addresses, and amounts; export them to a location with the same
  restricted permissions, and avoid committing them to a public repository.

## Reporting a vulnerability

Open an issue labelled `security`. Describe the version (`python -m rent_ledger
--version`), the command or file that triggered it, and a redacted example. Do not
include real tenant names, amounts, or addresses.

---

## Independent security audit (2026-10-21)

**Performed by:** `InGarlicBreadWeTrust` · **Type:** static source + dependency
review · **Result:** no vulnerabilities found.

**Method:** static review of every `.py` source, the `pyproject.toml` build
config, and the dependency graph; grep for the runtime-risk surface
(`subprocess`, `os.system`, `eval`/`exec`/`compile`, `pickle`/`marshal`,
`ctypes`, sockets/network).

**Findings for `rent-ledger`:**
- No `subprocess`, `os.system`, `exec`, `eval`, `compile`, `pickle`, `marshal`,
  or `ctypes` present.
- No network I/O (no sockets, no HTTP, no telemetry).
- No hardcoded secrets or credentials.
- No build-time backdoor: stock `setuptools` build-meta, no custom hooks or
  `setup.py` side-effects.
- Persistence uses an **atomic temp-file + `os.replace`** snapshot plus
  line-delimited JSONL appends — crash-safe; no world-writable mode is set.

**Verdict:** strong posture, with the one standing recommendation noted above:
restrict the data-file permissions and keep it on an encrypted volume, and treat
exported reports as sensitive. No code changes required.
