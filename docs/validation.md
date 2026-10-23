# Build validation

Validated on 2026-10-22. All inference-related checks below use deterministic fixtures or a local HTTP stub, unless explicitly identified as a read-only Valency call.

| Check | Result |
|---|---|
| Windows, Python 3.12.10 | 40 tests executed: 38 passed, 2 Linux-only transport tests skipped |
| Danus WSL, Python 3.14.4 | All 40 tests passed, including subprocess timeout/tool-contamination tests |
| Package / startup | Wheel built, installed into an isolated directory, initialized outside the checkout; existing Danus environment wrapper checked |
| Two-round scripted campaign | Completed with 98 reserved calls; baseline retained; unreviewed drafts quarantined |
| Dataset validation | 18 development problems, 18 calibration candidates, both domains represented |
| Connected Valency | Source listing and literature queries succeeded; ten metadata records imported |
| Standalone Valency adapter | Import/credential/endpoint handling tested offline; no standalone bearer-token request performed |
| Live Codex/Danus research inference | Not run, honoring the requested offline build |

The tests cover paired audit evaluation, false-acceptance controls, abstention/error denominators, domain regression, split/family overlap, single-use audit reservations, active-policy compare-and-swap, rollback, code-version checks, immutable artifact integrity, event-chain integrity, concurrent call budgets, job leases, stale writer rejection, cached resume, bounded retries, schema errors, native HTTP failures, closed-book event auditing, API-key exclusion and report escaping.

The native Linux test copy completed much faster than SQLite on the Windows-mounted filesystem. Prefer storing live WSL state on a native Linux filesystem, for example `--state /home/danus/danus-rsi-state`, while keeping the source checkout wherever convenient. Never run Windows and WSL writers against the same state directory simultaneously.

`docs/demo-report.html` and `docs/demo-report.md` are sanitized summaries of the scripted run. They contain no real model results, credentials, full private audit cases, or claims of scientific progress. Complete local evidence is ignored by Git under `.state/`.

Reproduce core checks with `python scripts/check.py`. GitHub Actions runs this suite and a two-round scripted workflow on Linux/Windows with Python 3.11/3.12. CI also installs the package and checks its console entry point outside the source checkout. No OpenAI or Valency credentials are needed in CI.
