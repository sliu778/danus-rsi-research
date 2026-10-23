# Dependencies and startup

## Core

Python 3.11+ and the standard library are sufficient for state management, offline demonstrations, reports and tests. The package has no mandatory third-party dependencies. An editable installation is optional when running from this checkout.

| Use | Dependency |
|---|---|
| Offline core / report / scripted workflow | Python 3.11+ with SQLite |
| Live research and evaluation | Existing Danus installation and its Python package |
| Model access | Authenticated Codex CLI using ChatGPT subscription |
| Native verification | Existing loopback Danus verifier service |
| Standalone Valency retrieval | Optional `mcp>=2.3,<3`, `httpx2>=2,<3`, `VALENCY_TOKEN` |
| GitHub publication / cloning private repository | Git and authenticated GitHub access |

The installed Danus environment inspected for this build uses Python 3.14.4, Codex CLI 0.163.0, MCP 2.3.0 and httpx2 2.16.0. These are observed versions, not a promise that arbitrary future versions preserve the same contracts. The optional dependency range is not a complete lockfile. Core tests also run on Windows Python 3.12; CI exercises Python 3.11 and 3.12 on Linux and Windows.

## Existing workstation

The original runtime is `/opt/danus` inside WSL distribution `Danus`, user `danus`. The new project checkout is separate from that runtime:

```powershell
wsl -d Danus -u danus
```

Then in the Linux shell:

```bash
cd /mnt/c/Users/Simo-/Documents/Codex/2026-10-20/i/outputs/danus-rsi-research
bash scripts/run.sh demo --cycles 2 --limit 4
```

`scripts/run.sh` sources `/opt/danus/scripts/env.sh` and uses `/opt/danus/runtime/venv/bin/python` when that installation exists. Set `DANUS_ROOT` for another location, including a checkout installed from a Windows folder and run through WSL (`DANUS_ROOT=/mnt/c/.../Danus`). `bash scripts/run.sh doctor` reports every live prerequisite in one read-only pass. [The live runbook](live-runbook.md) goes from there to a first result. Without an existing installation it uses `PYTHON_BIN`, or `python3`, for core commands; it does not install or alter Danus automatically.

To inspect the existing live prerequisites:

```bash
source /opt/danus/scripts/env.sh
python -c 'from danus import codex; print(codex.resolve_bin())'
/opt/danus/bin/codex login status
curl --fail http://127.0.0.1:8091/health
```

If needed, sign in with `/opt/danus/bin/codex login --device-auth`, then start the verifier using `(cd /opt/danus && bash scripts/services.sh up verify)`. Subscription sign-in was not repeated as part of this build, and no live model run was requested. A connection in the desktop application does not by itself authenticate the separate Danus runtime.

The script imports the existing runtime environment; live preflight checks that `CODEX_BACKEND=chatgpt`, confirms the CLI login reports ChatGPT, and verifies that the HTTP health PID matches the deployment's `runtime/run/verify.pid`. Inherited API-key variables are removed from candidate/judge subprocess environments. The native service uses its own existing environment; its expected model is recorded, but the service does not expose independently verifiable model identity.

## Resource planning

One benchmark problem uses five reserved calls: candidate generation, native check, and three judges. One verifier development cycle uses $8n+1$ calls for $n$ fixed calibration candidates. One solver development cycle uses $10nk+1$ calls for $n$ problems and $k$ samples, or $5nk+1$ when the proposal is rejected before evaluation. A mining batch uses one call. A research round adds a curator, planner and one to three subproblems; each uses researcher, critic, optional one-shot repair, native verifier and three judges. The scripted two-round demonstration (verifier round, solver round, one mining batch) uses 107 reservations.

A verifier audit with $a$ cases and $r$ regression cases needs $8(a+r)$ reservations. With the minimum 20-case audit and 18 starter calibration candidates this is 304 calls, so the example uses `--max-calls 512`. A solver audit with $p$ problems and $k$ samples needs $10pk$: the 12-problem minimum needs 120 calls at $k=1$ and 360 at $k=3$. Limits count interface calls, not native-service internal model turns or tokens. `handoff` and `handoff-sync` make no model calls.

For `--resume`, retain the same options and add the original run ID. Changing the selection, code, suite, policy, model, backend provenance or budget invalidates resume. The original deadline is not renewed. An expired run must be replaced with a new explicitly budgeted run. Audit batches are never resumable.

Use `python scripts/check.py` for offline tests. It confines temporary files to `.state/test-tmp/`, which also avoids restricted Windows system-temp directory issues. Linux-only subprocess tests are skipped on Windows and exercised in Linux CI/WSL.
