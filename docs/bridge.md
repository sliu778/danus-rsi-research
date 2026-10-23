# Danus fact-graph bridge

Research findings in this repository are proposals: a model panel and a native check reviewed them once, outside any fact graph. The bridge sends a finding to a running Danus project as a worker assignment, so that Danus workers re-derive it and the Danus verifier decides what becomes a fact. It then reads the outcome back.

## Boundary

| Action | How | Never |
|---|---|---|
| Assign | `danus assign <project>/<worker> --stdin`, replacing that worker's `TASK.md` | write the fact graph, global memory or `master_guidance` |
| Observe | read `<project>/global_memory/verification.jsonl` and `<project>/fact_graph/facts/<id>.md` | read worker-local memory |
| Start/stop | left to the operator or the Danus main agent | start, stop or re-roster workers |

Assignment is a dry run unless `--confirm` is given. The dry run prints the exact `TASK.md` text, target and command, so the operator can read it before replacing a worker's current task. Each confirmed handoff is recorded with its finding, target, task digest and CLI output.

## Workflow

```bash
# Inside the Danus WSL distribution, with an existing project and worker roster.
python -m danus_rsi findings                      # choose a finding ID
python -m danus_rsi handoff FINDING_ID --target myproject/high-1            # dry run
python -m danus_rsi handoff FINDING_ID --target myproject/high-1 --confirm  # writes TASK.md
/opt/danus/bin/danus start myproject/high-1       # operator decision
# Later:
python -m danus_rsi handoff-sync
```

By default only `panel-supported proposal` findings can be handed off. `--allow-unresolved` sends an unsupported finding as an open subproblem, and the task text says so.

## Tracing

The assignment asks the worker to pass `source_id="<handoff ID>"` to every `fact_submit` for this subproblem. Danus records every verdict in global memory with that `source_id`, whether it was accepted or rejected. `handoff-sync` collects those entries per handoff and counts:

- **verified facts**: a `correct` verdict whose `fact_id` file exists in `fact_graph/facts/`. A revoked fact is moved out of that directory, so it drops out at the next sync;
- **native rejections**: `wrong` verdicts;
- **status**: `danus-verified`, `submitted-unverified` or `pending`.

Each sync stores one timestamped snapshot, and later research rounds (`run`, `demo`) receive the latest snapshot's verified facts as planner memory, labeled with their `fact_id`. Those are the only prior results the planner sees as established. Panel-supported findings remain proposals.

Run `handoff-sync` between runs. A sync changes planner memory, so syncing while an interrupted run is waiting to be resumed makes its cached planner request differ, and resume refuses it.

A worker that omits `source_id` produces facts the bridge cannot attribute. The worker may also re-prove the claim in a different form. Missing traces mean "not observed", not "not proved"; check the project's fact graph directly when in doubt.

## Paths

`--danus-root` defaults to `DANUS_ROOT`, then `/opt/danus`. Projects are found at `DANUS_AGENTS_ROOT` when set, as Danus itself does, otherwise `<root>/runtime/projects`. Targets must have the form `<project>/<worker>` with simple names; anything else is refused before a command runs.

## Trust

The Danus verifier is also an informal model judgment, not a proof kernel. A `danus-verified` outcome means the finding passed a second, independent verification path inside a fact graph with cascade revocation. It does not mean a formal certificate or an expert review.
