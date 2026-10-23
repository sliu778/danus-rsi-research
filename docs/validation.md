# Build validation

Initial build validated on 2026-10-22. The solver arm, Valency miner and Danus bridge were added and validated on 2026-10-23. All inference-related checks below use deterministic fixtures or a local HTTP stub, unless explicitly identified as a read-only Valency call.

| Check | Result |
|---|---|
| Windows, Python 3.12.10 (initial build) | 40 tests executed: 38 passed, 2 Linux-only transport tests skipped |
| Windows, Python 3.14.3 (research arms) | 58 tests executed: 56 passed, 2 Linux-only transport tests skipped |
| Danus WSL, Python 3.14.4 (initial build) | All 40 tests passed, including subprocess timeout/tool-contamination tests; the research-arm additions have not yet been run under WSL |
| Package / startup | Wheel built, installed into an isolated directory, initialized outside the checkout; existing Danus environment wrapper checked |
| Two-round scripted campaign | Completed with 107 reserved calls: one verifier and one solver round, baseline retained in both; one quarantined mined draft |
| Dataset validation | 18 development problems, 18 calibration candidates, both domains represented |
| Connected Valency | Source listing and literature queries succeeded; eighteen metadata records imported, eight with submission dates |
| Standalone Valency adapter | Import/credential/endpoint handling tested offline; no standalone bearer-token request performed |
| Danus bridge | `danus assign` invocation and outcome tracing tested against a fake CLI runner and a synthetic project directory; no live Danus project was modified |
| Live Codex/Danus research inference | Not run, honoring the requested offline build |

The tests cover paired audit evaluation, false-acceptance controls, abstention/error denominators, domain regression, split/family overlap, single-use audit reservations, active-policy compare-and-swap, rollback, code-version checks, immutable artifact integrity, event-chain integrity, concurrent call budgets, job leases, stale writer rejection, cached resume, bounded retries, schema errors, native HTTP failures, closed-book event auditing, API-key exclusion and report escaping.

The research-arm tests add: arm field locks in both directions; rejection of strategy text that copies development content; the solver gate (gain threshold, errors, per-domain loss, pairing); a solver optimizer prompt without references; rejection without evaluation of a solver proposal that weakens the verifier; solver audit validation, promotion, single use, and the registry shared with verifier audits; mining eligibility by date and category; quarantined mined drafts with provenance and their exposure to audits; code-side citation and domain checks; refusal to import an unsigned review export; dry-run-by-default handoff; refusal of unresolved findings and unsafe targets; and outcome tracing that ignores untraced, torn, path-like and revoked entries.

The native Linux test copy completed much faster than SQLite on the Windows-mounted filesystem. Prefer storing live WSL state on a native Linux filesystem, for example `--state /home/danus/danus-rsi-state`, while keeping the source checkout wherever convenient. Never run Windows and WSL writers against the same state directory simultaneously.

`docs/demo-report.html` and `docs/demo-report.md` are sanitized summaries of the scripted run. They contain no real model results, credentials, full private audit cases, or claims of scientific progress. Complete local evidence is ignored by Git under `.state/`.

Reproduce core checks with `python scripts/check.py`. GitHub Actions runs this suite and a two-round scripted workflow on Linux/Windows with Python 3.11/3.12. CI also installs the package and checks its console entry point outside the source checkout. No OpenAI or Valency credentials are needed in CI.
