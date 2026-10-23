# Build validation

Initial build validated on 2026-10-22. On 2026-10-23 the solver arm, Valency miner and Danus bridge were added (0.2.0), then repeated sampling and uncertainty intervals (0.3.0), live-readiness tooling (0.4.0), and the panel v2 fixes found by the first live runs (0.5.0).

## Offline checks

Deterministic fixtures or a local HTTP stub; no model inference unless a row says so.

| Check | Result |
|---|---|
| Windows, Python 3.12.10 (0.1.0) | 40 tests: 38 passed, 2 Linux-only transport tests skipped |
| Danus WSL, Python 3.14.4 (0.1.0) | All 40 tests passed, including subprocess timeout/tool-contamination tests |
| Windows, Python 3.14.3 (0.2.0) | 58 tests: 56 passed, 2 Linux-only skipped |
| Windows, Python 3.14.3 (0.3.0) | 69 tests: 67 passed, 2 Linux-only skipped |
| WSL Ubuntu, Python 3.14.4 (0.3.0) | All 69 passed, none skipped, including the Linux-only transport tests |
| Windows, Python 3.14.3 (0.4.0) | 77 tests: 75 passed, 2 Linux-only skipped; WSL Ubuntu: all 77 passed |
| Windows and WSL Ubuntu (0.5.0) | 83 tests: Windows 81 passed with 2 Linux-only skipped; WSL Ubuntu all 83 passed |
| Package / startup | Wheel built, installed into an isolated directory, initialized outside the checkout with all 18 Valency records; Danus environment wrapper checked |
| Two-round scripted campaign | 107 reserved calls: one verifier and one solver round, baseline retained in both; one quarantined mined draft |
| Dataset validation | 18 development problems, 18 calibration candidates, both domains represented |
| Connected Valency | Source listing and literature queries succeeded; eighteen metadata records imported, eight with submission dates |
| Standalone Valency adapter | Import/credential/endpoint handling tested offline; no standalone bearer-token request performed |
| Danus bridge | `danus assign` invocation and outcome tracing tested against a fake CLI runner and a synthetic project directory; no live Danus project was modified |

## Live runs

All on 2026-10-23, in WSL Ubuntu against a Danus checkout installed from a Windows folder, with its own ChatGPT login and native verifier. Each smoke run was `benchmark --limit 2 --max-calls 10` on the same two development problems.

| Run | Result |
|---|---|
| Readiness (0.4.0) | `doctor` through `scripts/run.sh`: Linux, Danus environment, `CODEX_BACKEND=chatgpt`, `danus` package, codex binary and ChatGPT login passed; the verifier was down, so `ready` was false. Ready after starting the verifier |
| Smoke 1: three concurrent judges, panel v1 | 10 of 10 calls in 17 minutes. Both solver sessions and both native verifications succeeded, and the native verifier judged both proofs `correct`. All six concurrent judge sessions failed with `workspace routing discovery failed`, so both problems were infrastructure errors. No strict accept |
| Smoke 2: one judge at a time, panel v1 | All 10 calls succeeded with no routing failures. Both candidates received a native `correct` and three `correct` votes at 4/4/4/4, but were recorded as abstentions because three judges wrote `None.` in `reference_concern`. Wall time 65 minutes, about 42 of them apparently while the machine slept during one native call |
| Smoke 3: defaults of 0.5.0 (panel v2, one judge at a time) | All 10 calls succeeded in 21.5 minutes; the run recorded `danus-rsi-panel-v2` and `workers` 1. Both candidates were strict accepts: native `correct` and three `correct` votes at 4/4/4/4. Every judge left `reference_concern` empty, so the prompt instruction alone sufficed and the placeholder rule was not exercised live |

Two development problems with one attempt each show that the live pipeline works, not research capability. No improvement cycle, mining run, audit or Danus handoff has run live yet.

The tests cover paired audit evaluation, false-acceptance controls, abstention/error denominators, domain regression, split/family overlap, single-use audit reservations, active-policy compare-and-swap, rollback, code-version checks, immutable artifact integrity, event-chain integrity, concurrent call budgets, job leases, stale writer rejection, cached resume, bounded retries, schema errors, native HTTP failures, closed-book event auditing, API-key exclusion and report escaping.

The research-arm tests add: arm field locks in both directions; rejection of strategy text that copies development content; the solver gate (gain threshold, errors, per-domain loss, pairing); a solver optimizer prompt without references; rejection without evaluation of a solver proposal that weakens the verifier; solver audit validation, promotion, single use, and the registry shared with verifier audits; mining eligibility by date and category; quarantined mined drafts with provenance and their exposure to audits; code-side citation and domain checks; refusal to import an unsigned review export; dry-run-by-default handoff; refusal of unresolved findings and unsafe targets; and outcome tracing that ignores untraced, torn, path-like and revoked entries.

The reliability tests add: Wilson intervals at known values and edges; the sampled solver gate (threshold over $nk$ attempts, unequal attempt counts, partial per-problem losses) and its equivalence to the single-sample rule at $k=1$; call counts with sampling; withholding of reviewer defects that quote the reference; rejection of mined drafts that repeat known problems; a handoff blocked by a failed `danus status` before any write; `project-missing` sync status; `--samples` misuse rejected before a run is reserved; and the report's per-cycle evidence.

The readiness tests add: `doctor` ready only when every required check passes, a fix reported for each missing prerequisite, API keys withheld from the login probe and absent from output, unreachable verifier and missing `danus` package; `--estimate` equal to the calls a scripted verifier cycle actually reserves, campaign and mining bounds, and no run created; `audit-template` unusable until reviewed, never overwriting, refused inside the repository; and `audit-check` validity, counts, freshness before and after consumption, solver batches, malformed input, and no case content in its output.

The native Linux test copy completed much faster than SQLite on the Windows-mounted filesystem. Prefer storing live WSL state on a native Linux filesystem, for example `--state /home/danus/danus-rsi-state`, while keeping the source checkout wherever convenient. Never run Windows and WSL writers against the same state directory simultaneously.

`docs/demo-report.html` and `docs/demo-report.md` are sanitized summaries of the scripted run. They contain no real model results, credentials, full private audit cases, or claims of scientific progress. Complete local evidence is ignored by Git under `.state/`.

Reproduce core checks with `python scripts/check.py`. GitHub Actions runs this suite and a two-round scripted workflow on Linux/Windows with Python 3.11/3.12. CI also installs the package and checks its console entry point outside the source checkout. No OpenAI or Valency credentials are needed in CI.
