# Build validation

Initial build validated on 2026-10-22. The solver arm, Valency miner and Danus bridge were added and validated on 2026-10-23, followed the same day by repeated sampling, uncertainty intervals, feedback redaction, miner deduplication and the bridge preflight. All inference-related checks below use deterministic fixtures or a local HTTP stub, unless explicitly identified as a read-only Valency call.

| Check | Result |
|---|---|
| Windows, Python 3.12.10 (initial build) | 40 tests executed: 38 passed, 2 Linux-only transport tests skipped |
| Windows, Python 3.14.3 (research arms) | 58 tests executed: 56 passed, 2 Linux-only transport tests skipped |
| Windows, Python 3.14.3 (reliability) | 69 tests executed: 67 passed, 2 Linux-only transport tests skipped |
| Danus WSL, Python 3.14.4 (initial build) | All 40 tests passed, including subprocess timeout/tool-contamination tests |
| Windows, Python 3.14.3 (live readiness) | 77 tests executed: 75 passed, 2 Linux-only transport tests skipped |
| WSL Ubuntu, local Danus checkout (live readiness) | `doctor` through `scripts/run.sh` with `DANUS_ROOT` at the Windows-installed Danus: Linux, Danus environment, `CODEX_BACKEND=chatgpt`, `danus` package, codex binary and ChatGPT login all passed; the verifier service was down, so `ready` was false. No service was started and no model call was made |
| First live smoke run (2026-10-23) | `benchmark --limit 2 --max-calls 10` against the local Danus verifier, 10 of 10 calls in 17 minutes. Both solver sessions and both native verifications succeeded; the native verifier judged both candidate proofs `correct`. All six concurrent judge sessions failed with `workspace routing discovery failed`, so both problems were recorded as infrastructure errors, not as accepts or rejects. No strict accept was awarded |
| WSL Ubuntu, Python 3.14.4 (reliability) | All 69 tests passed, none skipped, including the Linux-only transport tests; scripted demo completed with 107 calls. This is a plain Ubuntu distribution, not the Danus runtime, so no live verifier was involved |
| Package / startup | Wheel built, installed into an isolated directory, initialized outside the checkout; existing Danus environment wrapper checked |
| Two-round scripted campaign | Completed with 107 reserved calls: one verifier and one solver round, baseline retained in both; one quarantined mined draft |
| Dataset validation | 18 development problems, 18 calibration candidates, both domains represented |
| Connected Valency | Source listing and literature queries succeeded; eighteen metadata records imported, eight with submission dates |
| Standalone Valency adapter | Import/credential/endpoint handling tested offline; no standalone bearer-token request performed |
| Danus bridge | `danus assign` invocation and outcome tracing tested against a fake CLI runner and a synthetic project directory; no live Danus project was modified |
| Live Codex/Danus research inference | Not run, honoring the requested offline build |

The tests cover paired audit evaluation, false-acceptance controls, abstention/error denominators, domain regression, split/family overlap, single-use audit reservations, active-policy compare-and-swap, rollback, code-version checks, immutable artifact integrity, event-chain integrity, concurrent call budgets, job leases, stale writer rejection, cached resume, bounded retries, schema errors, native HTTP failures, closed-book event auditing, API-key exclusion and report escaping.

The research-arm tests add: arm field locks in both directions; rejection of strategy text that copies development content; the solver gate (gain threshold, errors, per-domain loss, pairing); a solver optimizer prompt without references; rejection without evaluation of a solver proposal that weakens the verifier; solver audit validation, promotion, single use, and the registry shared with verifier audits; mining eligibility by date and category; quarantined mined drafts with provenance and their exposure to audits; code-side citation and domain checks; refusal to import an unsigned review export; dry-run-by-default handoff; refusal of unresolved findings and unsafe targets; and outcome tracing that ignores untraced, torn, path-like and revoked entries.

The reliability tests add: Wilson intervals at known values and edges; the sampled solver gate (threshold over $nk$ attempts, unequal attempt counts, partial per-problem losses) and its equivalence to the single-sample rule at $k=1$; call counts with sampling; withholding of reviewer defects that quote the reference; rejection of mined drafts that repeat known problems; a handoff blocked by a failed `danus status` before any write; `project-missing` sync status; `--samples` misuse rejected before a run is reserved; and the report's per-cycle evidence.

The readiness tests add: `doctor` ready only when every required check passes, a fix reported for each missing prerequisite, API keys withheld from the login probe and absent from output, unreachable verifier and missing `danus` package; `--estimate` equal to the calls a scripted verifier cycle actually reserves, campaign and mining bounds, and no run created; `audit-template` unusable until reviewed, never overwriting, refused inside the repository; and `audit-check` validity, counts, freshness before and after consumption, solver batches, malformed input, and no case content in its output.

The native Linux test copy completed much faster than SQLite on the Windows-mounted filesystem. Prefer storing live WSL state on a native Linux filesystem, for example `--state /home/danus/danus-rsi-state`, while keeping the source checkout wherever convenient. Never run Windows and WSL writers against the same state directory simultaneously.

`docs/demo-report.html` and `docs/demo-report.md` are sanitized summaries of the scripted run. They contain no real model results, credentials, full private audit cases, or claims of scientific progress. Complete local evidence is ignored by Git under `.state/`.

Reproduce core checks with `python scripts/check.py`. GitHub Actions runs this suite and a two-round scripted workflow on Linux/Windows with Python 3.11/3.12. CI also installs the package and checks its console entry point outside the source checkout. No OpenAI or Valency credentials are needed in CI.
