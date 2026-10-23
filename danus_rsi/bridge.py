"""Hand research findings to Danus workers and read back native verifier outcomes.

The only write is `danus assign`, which replaces one worker's TASK.md. This module
never writes the fact graph or global memory, never starts workers, and never
reads worker-local memory. Outcomes come from the project's shared global-memory
`verification` trace and fact files, read-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time

from .protocol import digest, require

TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
FACT_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


def danus_root(value=None):
    return Path(value or os.environ.get("DANUS_ROOT", "/opt/danus"))


def project_dir(root, project):
    agents = os.environ.get("DANUS_AGENTS_ROOT")
    return (Path(agents) if agents else root / "runtime" / "projects") / project


def handoff_text(handoff_id, finding):
    """A worker assignment. The candidate is labeled as an unverified draft from outside the swarm."""
    task, solution = finding["finding"]["task"], finding["finding"]["solution"]
    supported = finding["finding"]["status"] == "panel-supported proposal"
    lines = [
        "# Assignment from danus-rsi-research",
        "",
        f"Handoff ID: `{handoff_id}`",
        "",
        "## Subproblem",
        "",
        task["prompt"],
        "",
        "## Candidate from the research pipeline (unverified)",
        "",
        ("An external three-judge model panel and a native check supported this candidate. That is informal "
         "review, not a fact: no step below may be cited as established." if supported else
         "This candidate was NOT supported by the external review; treat it as an open subproblem and expect defects."),
        "",
        "**Claim.** " + solution["claim"],
        "",
        "**Proposed argument.**",
        "",
        solution["proof"],
        "",
        "## What to do",
        "",
        "1. `fact_search` and `gm_search` first; do not duplicate an existing fact or a recorded dead end.",
        "2. Re-derive the argument yourself, splitting it into lemmas you can verify. Repair or refute it; "
        "a counterexample is a valid outcome and belongs in global memory.",
        f"3. Submit each verified step with `fact_submit`, passing `source_id=\"{handoff_id}\"` so the outcome "
        "can be traced back to this handoff.",
        "4. If the claim is false or unprovable as stated, submit the corrected statement instead and record why.",
    ]
    return "\n".join(lines) + "\n"


def assign(store, finding_id, target, root=None, confirm=False, allow_unresolved=False, runner=subprocess.run):
    """Dry run unless `confirm`: replacing a worker's TASK.md is the operator's decision."""
    require(TARGET.fullmatch(target or "") is not None, "target must be <project>/<worker>")
    finding = store.get(finding_id, "research_finding")
    status = finding["finding"]["status"]
    require(status == "panel-supported proposal" or allow_unresolved,
            "finding is not panel-supported; pass --allow-unresolved to hand it off as an open subproblem")
    root = danus_root(root)
    handoff_id = "rsi" + digest({"finding": finding_id, "target": target})[:24]
    text = handoff_text(handoff_id, finding)
    plan = {"handoff_id": handoff_id, "finding": finding_id, "target": target, "finding_status": status,
            "command": [str(root / "bin" / "danus"), "assign", target, "--stdin"], "task_digest": digest(text)}
    if not confirm:
        return plan | {"assigned": False, "task_text": text, "note": "dry run; rerun with --confirm to write the worker's TASK.md"}
    completed = runner(plan["command"], input=text, capture_output=True, text=True, timeout=60)
    require(completed.returncode == 0, "danus assign failed: " + (completed.stderr or completed.stdout or "")[-2000:].strip())
    record = plan | {"assigned_at": time.time(), "danus_output": (completed.stdout or "")[-2000:]}
    store.put("danus_handoff", record)
    store.event("danus_handoff", {"handoff": handoff_id, "finding": finding_id, "target": target})
    return record | {"assigned": True}


def _verification_entries(directory):
    path = directory / "global_memory" / "verification.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # A torn final line from a concurrent append is not evidence.
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def sync(store, root=None):
    """Read each handoff's native outcomes; record a fact only if its file exists in the graph."""
    root = danus_root(root)
    outcomes = []
    # Re-assigning the same finding to the same worker reuses its handoff ID.
    handoffs = {item["body"]["handoff_id"]: item["body"] for item in store.artifacts("danus_handoff")}
    for handoff in handoffs.values():
        directory = project_dir(root, handoff["target"].split("/", 1)[0])
        traced = [e for e in _verification_entries(directory)
                  if isinstance(e.get("links"), dict) and e["links"].get("source_id") == handoff["handoff_id"]]
        facts, rejections = [], 0
        for entry in traced:
            fact_id = entry.get("fact_id")
            if entry.get("verdict") == "correct" and isinstance(fact_id, str) and FACT_ID.fullmatch(fact_id):
                path = directory / "fact_graph" / "facts" / (fact_id + ".md")
                # A revoked fact is moved out of facts/, so absence means not (or no longer) established.
                if path.exists():
                    facts.append({"fact_id": fact_id, "statement": entry.get("claim", "")})
            elif entry.get("verdict") == "wrong":
                rejections += 1
        outcomes.append({"handoff_id": handoff["handoff_id"], "finding": handoff["finding"], "target": handoff["target"],
                         "verified_facts": facts, "native_rejections": rejections, "traced_submissions": len(traced),
                         "status": "danus-verified" if facts else ("submitted-unverified" if traced else "pending")})
    # One timestamped snapshot per sync, so a later revocation supersedes an earlier fact.
    snapshot = store.put("danus_sync", {"synced_at": time.time(), "danus_root": str(root), "outcomes": outcomes})
    return {"kind": "handoff-sync", "snapshot": snapshot, "outcomes": outcomes}


def verified_memory(store):
    """Planner memory entries for facts the Danus native verifier accepted, as of the latest sync."""
    syncs = store.artifacts("danus_sync")
    if not syncs:
        return []
    return [{"claim": fact["statement"], "status": "Danus fact graph: native verifier accepted",
             "fact_id": fact["fact_id"], "evidence_id": outcome["finding"]}
            for outcome in syncs[-1]["body"]["outcomes"] for fact in outcome["verified_facts"]]
