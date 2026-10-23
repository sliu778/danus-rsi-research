# Live runbook

The path from an installed Danus to a first measured result, in the order that keeps spend small and evidence clean. Every step before step 3 is read-only. Live commands run inside WSL/Linux through `scripts/run.sh`, which sources the Danus environment and uses the Danus Python.

## 0. Point at the Danus installation

`scripts/run.sh` defaults to `/opt/danus`. A Danus checkout installed from a Windows folder (the `Danus.ps1` launcher layout) lives under `/mnt/c/...` instead:

```bash
export DANUS_ROOT=/mnt/c/Users/<you>/.../outputs/Danus
```

Keep run state on the Linux filesystem. SQLite on a Windows mount is slow, and `doctor` flags it:

```bash
STATE=~/danus-rsi-state
```

## 1. Check readiness

```bash
bash scripts/run.sh doctor --state "$STATE"
```

`doctor` makes no model call and starts nothing. It checks Python, Linux, `DANUS_ROOT`, the sourced Danus environment, `CODEX_BACKEND=chatgpt`, the `danus` package, `codex login status`, and that the verifier's `/health` PID matches the Danus pidfile. Optional checks (Valency token, Danus projects) never block. Every failed check comes with its fix. The usual missing piece is the verifier:

```bash
(cd "$DANUS_ROOT" && bash scripts/services.sh up verify)   # or, on Windows: .\Danus.ps1 Start
```

Signing in to ChatGPT (`Danus.ps1 Login` or `bin/codex login --device-auth`) is done by the operator in their own terminal, never by this project.

## 2. Size every run before starting it

Add `--estimate` to any live command. It prints the upper bound on reserved calls from the same problem selection the engine will use, compares it with `--max-calls`, and reserves nothing:

```bash
bash scripts/run.sh improve --arm solver --limit 6 --samples 3 --cycles 1 --max-calls 200 --estimate --state "$STATE"
# upper_bound_calls: 181, fits: true
```

Calls are interface calls. Each one is a fresh model session of up to `call_timeout_seconds` (10 minutes by default) or one native verification; they are not tokens or money. The wall-clock `--deadline` (4 hours by default, at most 24) caps a run, and an interrupted run resumes with `--resume RUN_ID` within its original budget.

## 3. Smoke test: two problems, ten calls

```bash
bash scripts/run.sh benchmark --limit 2 --max-calls 10 --state "$STATE"
```

This exercises the whole live path once: solver session, native verifier, three judges, report. Read `reports/<run>/report.html` and the `calls/` evidence before spending more. Infrastructure errors here are configuration problems, not mathematics.

**Resolved: concurrent judge sessions.** In the first live smoke run (2026-10-23), both solver calls and both native verifications succeeded, but all six judge calls failed. Judges then ran three at a time, and each judge's Codex session logged `failed to refresh available models: request timed out`, retried five times, and ended with `workspace routing discovery failed` after about 170 seconds. A rerun the same day with one judge at a time completed all ten calls without a single routing failure, so one judge at a time (`workers: 1`) is now the default. Raising `workers` through `--config` brings the concurrency back; do it only after a sequential run works on your machine. Calls that fail this way are charged and recorded as infrastructure errors, so `--retry-errors` on the same run needs budget beyond the original `--max-calls`.

**Resolved: "None." as a reference concern.** In that sequential rerun, both candidate proofs received three `correct` votes with perfect scores and a native `correct`, yet both were recorded as abstentions: three of the six judges wrote the literal text `None.` in `reference_concern`, and protocol v1 read any non-empty text as a concern. Protocol `danus-rsi-panel-v2` asks judges to leave the field empty and treats a closed list of placeholders as no concern; any other text still forces abstention. Results recorded under v1 keep their v1 decisions.

**Keep the machine awake.** In the same rerun one native verification spanned 46 minutes of wall time but only 252 seconds of the process's monotonic clock, which is consistent with the computer sleeping mid-call. Long runs survive this, because budgets and leases use wall-clock deadlines, but they take longer than their calls.

## 4. First solver experiment

```bash
bash scripts/run.sh improve --arm solver --limit 6 --samples 3 --cycles 1 --max-calls 200 --state "$STATE"
```

Three attempts per problem, verifier guidance fixed. The report shows strict accepts with 95% Wilson intervals for both policies. At this size, expect wide intervals: a selected branch is a lead, not a result.

## 5. Build a private audit set

Promotion needs a fresh, independently reviewed batch. Start from a worksheet outside the repository:

```bash
bash scripts/run.sh audit-template --arm solver --out ~/private/solver-audit-001.json
```

A reviewer replaces every `REPLACE` field, adds problems up to the minimum (12 problems, 8 families, 5 per domain), sets `review_status` to `independently-reviewed` and signs it. Then check it without consuming it:

```bash
bash scripts/run.sh audit-check ~/private/solver-audit-001.json --state "$STATE"
```

`audit-check` validates structure and balance, rejects overlap with anything this system has exposed, reports whether the batch or any of its problems was already consumed, and prints counts but never case content. Only when it reports `"fresh": true`:

```bash
bash scripts/run.sh audit --file ~/private/solver-audit-001.json --candidate POLICY_ID --samples 3 --max-calls 400 --promote --state "$STATE"
```

The batch is consumed on first use, even if the run fails.

## 6. Grow the benchmark

```bash
bash scripts/run.sh mine --since 2026-08-01 --batches 2 --max-calls 4 --state "$STATE"
bash scripts/run.sh drafts --origin valency-miner --export ~/private/review-001.json --state "$STATE"
# reviewer edits and signs, then:
bash scripts/run.sh import-curriculum ~/private/review-001.json --state "$STATE"
```

## 7. Hand a finding to Danus

```bash
"$DANUS_ROOT/bin/danus" new myproject            # once; the roster is the operator's decision
bash scripts/run.sh findings --state "$STATE"
bash scripts/run.sh handoff FINDING_ID --target myproject/high-1 --state "$STATE"            # dry run
bash scripts/run.sh handoff FINDING_ID --target myproject/high-1 --confirm --state "$STATE"
"$DANUS_ROOT/bin/danus" start myproject/high-1
bash scripts/run.sh handoff-sync --state "$STATE"
```

Read Danus's `docs/security-and-trust.md` before starting workers: upstream workers run with sandbox bypass.
