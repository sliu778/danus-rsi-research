# Danus RSI Research

Research agents for graduate mathematics and theoretical physics that improve their own strategies, but only through checks they cannot move. Built on [Danus](https://github.com/frenzymath/Danus) and its native verifier, with literature from [Valency](https://www.valency.io/) and arXiv.

**Status: experimental, version 0.5.0.** Tested offline on Windows and Linux. The live path was smoke-tested on 2026-10-23 against a local Danus verifier: two development problems, both strict accepts. No improvement cycle has run live yet, and no research result or capability gain is claimed.

## How it works

Three things improve, and each one has its own gate:

| What improves | How it is measured | What stays fixed |
|---|---|---|
| **Verifier strategy** (the judges' guidance) | Balanced accuracy on proofs already labeled valid or invalid | Solver strategy |
| **Solver strategy** (how answers are written) | Strict accepts of fresh solutions, with *k* attempts per problem | Verifier guidance, so a solver cannot win by loosening its own check |
| **The benchmark** | New problems drafted from recent papers | Nothing is admitted until a person reviews and signs it |

A **strict accept** needs the Danus native verifier *and* three independent judges (correctness, adversarial, completeness) to agree that a proof is correct. Disagreement or doubt is an abstention, and failed calls are infrastructure errors, never wrong answers.

A proposed change first has to beat the current strategy on the same development problems. That only moves an *experimental branch*. To become the *active policy*, it must also win on a fresh, private, single-use audit set reviewed by a person. Research findings can be handed to Danus workers, and only facts the Danus verifier accepts into its fact graph return to later planning as established results.

Every model session is fresh and text-only: no code execution, browsing or tools. Agents can change strategy text and suggest draft problems; they can never change labels, gates, budgets or code.

## What you need

| To… | You need |
|---|---|
| Try it offline (scripted demo, tests, reports) | Python 3.11+. Nothing else: the core uses only the standard library |
| Run live model calls | Linux or WSL, an installed [Danus](https://github.com/frenzymath/Danus) signed in with a ChatGPT subscription, and its verifier service |
| Search Valency directly | Optional: `pip install '.[valency]'` and a `VALENCY_TOKEN` from your Valency settings |

Live runs use the Danus Codex login and never fall back to an API key.

## 1. Try it offline (no credentials)

```bash
git clone https://github.com/sliu778/danus-rsi-research.git
cd danus-rsi-research
python -m danus_rsi demo --cycles 2 --limit 4     # scripted run: research, both improvement arms, mining
python -m danus_rsi status                        # runs, policies, drafts, integrity check
python scripts/check.py                           # the test suite
```

The demo uses fixed scripted answers, not a model, and its judges disagree on purpose, so nothing is ever accepted. Its report is written under `.state/reports/<run id>/` as HTML, Markdown and JSON; [docs/demo-report.html](docs/demo-report.html) is an example. The repository is private, so cloning needs GitHub access.

Optionally `python -m pip install -e .` gives you a `danus-rsi` command in place of `python -m danus_rsi`.

## 2. Set up live runs

Run live commands inside Linux or WSL through `scripts/run.sh`. It sources the Danus environment and uses the Danus Python, so the `danus` package and Codex login are available.

**Point at your Danus installation.** The default is `/opt/danus`. If Danus was installed from a Windows folder and runs through WSL, point at that folder instead:

```bash
export DANUS_ROOT=/mnt/c/Users/<you>/path/to/Danus     # skip if Danus is at /opt/danus
STATE=~/danus-rsi-state                                 # keep run state on the Linux filesystem
```

From Windows, open the shell with `wsl -d <your distribution>` and `cd` into this repository under `/mnt/c/...`. Keep `--state` on the Linux side: SQLite on a Windows mount is slow.

**Check readiness.** `doctor` makes no model call and starts nothing. It reports every prerequisite with a fix for each one that fails:

```bash
bash scripts/run.sh doctor --state "$STATE"
```

**Start the verifier** if `doctor` says it is down:

```bash
(cd "$DANUS_ROOT" && bash scripts/services.sh up verify)
```

If `doctor` reports a missing login, sign in once in your own terminal with `"$DANUS_ROOT/bin/codex" login --device-auth`, or your Danus launcher's login command. This project never handles your credentials.

**Size every run first.** Add `--estimate` to any live command to print the most calls it can reserve, checked against `--max-calls`, without starting anything:

```bash
bash scripts/run.sh benchmark --limit 2 --max-calls 10 --estimate --state "$STATE"
```

## 3. Everyday workflow

All commands below take `--state "$STATE"`; it is omitted here for brevity.

**Smoke test: two problems, at most 10 calls (about 20–25 minutes).**

```bash
bash scripts/run.sh benchmark --limit 2 --max-calls 10
```

Open the report it prints. Infrastructure errors at this stage are configuration problems; see [Troubleshooting](#troubleshooting).

**Improve the verifier** (fixed labeled candidates; solver strategy held fixed):

```bash
bash scripts/run.sh improve --arm verifier --cycles 1 --limit 8 --max-calls 80
```

**Improve the solver** (fresh attempts judged under fixed verifier guidance). Use several attempts per problem so one lucky sample cannot decide:

```bash
bash scripts/run.sh improve --arm solver --cycles 1 --limit 6 --samples 3 --max-calls 200
```

**Run a research campaign.** Each round plans subproblems, solves, critiques and judges them, then runs one improvement cycle; `--arm alternate` switches arms between rounds:

```bash
bash scripts/run.sh run --objective 'Sufficient hypotheses for controlled EFT power counting on curved backgrounds' \
  --domain theoretical-physics --cycles 2 --limit 6 --arm alternate --max-calls 256
```

**Read results.** Every run prints its report path. Reports show each decision and, for improvement cycles, the numbers behind it with 95% intervals, for example `strict accepts 2/18 [0.03, 0.33] → 6/18 [0.16, 0.56]`. The intervals describe noise; they never decide a gate.

```bash
bash scripts/run.sh status          # runs, policy IDs, unreviewed drafts
bash scripts/run.sh report RUN_ID   # regenerate a report
```

**Resume an interrupted run** with the exact same command plus its run ID. The original budget and deadline still apply:

```bash
bash scripts/run.sh improve --arm solver --cycles 1 --limit 6 --samples 3 --max-calls 200 --resume RUN_ID
# add --retry-errors to retry failed calls once (each retry needs unused budget)
```

## 4. Grow the benchmark

The miner drafts problems from recent papers. Drafts stay quarantined until a person checks them against the full paper.

```bash
bash scripts/run.sh mine --since 2026-08-01 --batches 2 --max-calls 4
bash scripts/run.sh drafts --origin valency-miner                        # list drafts
bash scripts/run.sh drafts --origin valency-miner --export ~/private/review-001.json
```

In the exported file, the reviewer edits or deletes each task, optionally adds labeled candidate proofs, then sets `"review_status": "independently-reviewed"` and `"reviewer"`. Then:

```bash
bash scripts/run.sh import-curriculum ~/private/review-001.json
```

Imported tasks become development data only; they can never be used as audit problems.

## 5. Promote a policy

Improvement cycles only move an experimental branch. To make a candidate the active policy, audit it on problems this system has never seen.

1. **Write a worksheet outside the repository:**
   ```bash
   bash scripts/run.sh audit-template --arm solver --out ~/private/solver-audit-001.json
   ```
2. **A reviewer fills it in and signs it.** A solver audit needs at least 12 problems, 8 families and 5 per domain. A verifier audit needs at least 20 labeled cases, 10 families, and 5 valid and 5 invalid per domain.
3. **Check it without using it up:**
   ```bash
   bash scripts/run.sh audit-check ~/private/solver-audit-001.json
   ```
   Continue only when it reports `"fresh": true`.
4. **Run the audit.** Take the candidate policy ID from the improvement report or `status`:
   ```bash
   bash scripts/run.sh audit --file ~/private/solver-audit-001.json --candidate POLICY_ID \
     --samples 3 --max-calls 400 --promote
   ```
   A batch is consumed on first use, even if the run fails.
5. **Undo if needed:**
   ```bash
   bash scripts/run.sh promote EVALUATION_ID     # activate an eligible audit later
   bash scripts/run.sh rollback POLICY_ID        # return to any previously active policy
   ```

Keep audit files private and out of version control.

## 6. Literature with Valency

```bash
python -m danus_rsi literature                                      # list stored records
python -m danus_rsi literature --import-file valency-export.json     # import a connector result
python -m danus_rsi literature --query 'compact self-adjoint operators norm attainment'   # needs VALENCY_TOKEN
```

The repository ships 18 real Valency metadata records, 8 of them dated recent papers for the miner. Records are literature leads, never evidence of correctness. `run --refresh-literature` searches before planning; otherwise research uses stored records. See [docs/valency.md](docs/valency.md).

## 7. Hand findings to Danus

A finding the panel supports is still a proposal. To get a real fact, hand it to a Danus worker and let the Danus verifier decide.

```bash
bash scripts/run.sh findings                                            # pick a finding ID
bash scripts/run.sh handoff FINDING_ID --target myproject/high-1        # dry run: shows the exact TASK.md
bash scripts/run.sh handoff FINDING_ID --target myproject/high-1 --confirm
"$DANUS_ROOT/bin/danus" start myproject/high-1                          # your decision
bash scripts/run.sh handoff-sync                                        # read the verifier's outcomes
```

The handoff only replaces that worker's `TASK.md` through `danus assign`. It never writes the fact graph, never starts workers, and never reads worker-local memory. Read Danus's `docs/security-and-trust.md` before starting workers. See [docs/bridge.md](docs/bridge.md).

## Command reference

| Command | What it does | Model calls |
|---|---|---|
| `init` | Create state with the development suite and Valency seed | no |
| `status` | Runs, policies, unreviewed drafts, event-chain check | no |
| `doctor` | Check every live prerequisite | no |
| `demo` | Scripted end-to-end run | scripted only |
| `benchmark` | Solve and judge development problems | yes |
| `improve` | Verifier or solver improvement cycles (`--arm`, `--samples`) | yes |
| `run` | Research campaign with improvement after each round | yes |
| `mine` | Draft benchmark problems from recent papers | yes |
| `drafts` | List or export quarantined drafts | no |
| `import-curriculum` | Import reviewed development problems | no |
| `audit-template` | Write a private audit worksheet | no |
| `audit-check` | Validate an audit file and check freshness | no |
| `audit` | Audit a candidate (`--promote` to activate on success) | yes |
| `promote` / `rollback` | Change the active policy | no |
| `literature` | List, import or search Valency records | no |
| `findings` | List research findings | no |
| `handoff` / `handoff-sync` | Send a finding to Danus / read outcomes | no |
| `report` | Regenerate a run's report | no |

Every model-calling command accepts `--max-calls`, `--deadline` (seconds, at most 86400), `--estimate`, `--resume`, `--retry-errors`, `--policy` and `--config`. Run `python -m danus_rsi <command> --help` for all options.

## Budgets and configuration

A **call** is one model session (up to 10 minutes) or one native verification (up to 16 minutes). It is not a token count or a price.

| Work | Calls |
|---|---|
| Benchmark, per problem | 5 |
| Verifier cycle, *c* labeled candidates | 8*c* + 1 |
| Solver cycle, *n* problems × *k* samples | 10*nk* + 1 |
| Research round | at most 23 |
| Mining batch | 1 |
| Verifier audit, *a* cases + *r* regression cases | 8(*a* + *r*) |
| Solver audit, *p* problems × *k* samples | 10*pk* |

`--config FILE` overrides any of these defaults:

```json
{"model": "gpt-6-astra", "effort": "xhigh", "workers": 1, "max_calls": 160, "deadline_seconds": 14400,
 "call_timeout_seconds": 600, "verify_timeout_seconds": 960, "verify_url": "http://127.0.0.1:8091/verify"}
```

`workers` is how many judges run at once (at most 3). Keep it at 1 unless a sequential run works on your machine and you have tested more.

## Where things are stored

| What | Where |
|---|---|
| Runs, jobs, budgets, policies, lineage, audit reservations | `<state>/research.sqlite3` |
| Every call's request, result, events and errors | `<state>/calls/<run>/` |
| Reports (HTML, Markdown, full JSON) | `<state>/reports/<run>/` |
| Development problems and Valency seed | `danus_rsi/data/` |
| Private audit and review files | Anywhere outside the repository |

`<state>` is `.state/` by default, which git ignores. Back it up as a whole while nothing is writing to it, and never point Windows and WSL processes at the same state at the same time.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `doctor` says not ready | Apply the `fix` shown for each failed check |
| `live Danus transport requires Linux/WSL` | Run through `bash scripts/run.sh` inside Linux or WSL |
| Verifier unavailable, or PID mismatch | `(cd "$DANUS_ROOT" && bash scripts/services.sh up verify)` |
| Judge calls fail with `workspace routing discovery failed` | Concurrent sessions; keep `workers` at 1 (the default) |
| Unanimous `correct` votes but `abstain` | Read `reference_concern` in `report.json`: any real concern abstains by design |
| A run takes far longer than its calls | The machine slept; keep it awake for long runs |
| `persistent call budget or run deadline exhausted` | Start a new run with a larger `--max-calls` or `--deadline`; a resumed run keeps its original budget and deadline |
| `audit batch already consumed` | Batches are single-use; build a fresh one |
| Slow state operations under WSL | Use a `--state` path on the Linux filesystem, not `/mnt/c` |

The [live runbook](docs/live-runbook.md) records what the first live runs found and how each issue was fixed.

## Guarantees and limits

- Correctness decisions are made by code from structured verdicts; agents cannot edit gates, labels, budgets or code.
- Budgets, deadlines and single-use audits persist across interruptions. Hashes detect accidental changes to state, not deliberate tampering by someone with file access.
- The verifier and judges are model judgments in one model family, not a formal proof kernel; their errors can be correlated.
- Benchmark labels are authored examples, not expert-certified. The gates use fixed thresholds, not significance tests.
- Nothing here establishes novelty or publishes anything. Findings, even unanimous ones, remain proposals for expert review.

## Further reading

[Protocol and gates](docs/protocol.md) · [Architecture](docs/architecture.md) · [Live runbook](docs/live-runbook.md) · [Danus bridge](docs/bridge.md) · [Valency](docs/valency.md) · [Environment](docs/environment.md) · [Validation record](docs/validation.md) · [Provenance](docs/provenance.md)

Licensed under Apache-2.0.
