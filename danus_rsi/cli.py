"""Command line entry point; all live runs require an explicit command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import bridge
from .agents import LiveAgents, ScriptedAgents
from .engine import DEFAULT_CONFIG, Engine, code_hash, initialize, load_suite, validate_config
from .protocol import digest, read_json, require, save_json, validate_suite
from .report import write_report
from .store import BudgetExceeded, Store
from .valency import eligible_papers, import_snapshot, search

DEMO_MINING_SINCE = "2026-08-01"


def parser():
    p = argparse.ArgumentParser(description="Danus research agents and evaluated verifier improvement")
    sub = p.add_subparsers(dest="command", required=True)
    def command(name, help_text, live=False):
        q = sub.add_parser(name, help=help_text)
        q.add_argument("--state", default=".state", help="local SQLite/evidence directory")
        if live:
            q.add_argument("--config", type=Path)
            q.add_argument("--max-calls", type=int)
            q.add_argument("--deadline", type=int, help="wall-clock budget in seconds, up to 86400")
            q.add_argument("--resume", help="resume a non-audit run with an identical manifest")
            q.add_argument("--retry-errors", action="store_true", help="retry cached transport errors once within the original budget")
            q.add_argument("--policy", help="policy artifact ID; defaults to the active version")
        return q
    command("init", "initialize state, development data and Valency seed records")
    command("status", "show runs, policies, drafts and event integrity")
    lit = command("literature", "query Valency or import a connector result/export")
    action = lit.add_mutually_exclusive_group()
    action.add_argument("--query")
    action.add_argument("--import-file", type=Path)
    lit.add_argument("--limit", type=int, default=10)
    arms = ["verifier", "solver", "alternate"]
    demo = command("demo", "run deterministic fixtures without credentials", True)
    demo.add_argument("--cycles", type=int, default=2)
    demo.add_argument("--limit", type=int, default=4)
    demo.add_argument("--arm", choices=arms, default="alternate", help="improvement arm after each research round")
    bench = command("benchmark", "solve and judge public development problems", True)
    bench.add_argument("--limit", type=int, default=4)
    rsi = command("improve", "recursively propose/evaluate development strategies", True)
    rsi.add_argument("--cycles", type=int, default=2)
    rsi.add_argument("--limit", type=int, default=8)
    rsi.add_argument("--arm", choices=arms[:2], default="verifier", help="verifier: labeled calibration; solver: verifier-gated solve rate")
    rsi.add_argument("--samples", type=int, default=1, help="solver arm: independent attempts per problem (1..5)")
    run = command("run", "run a research campaign with development RSI after each round", True)
    run.add_argument("--objective", required=True)
    run.add_argument("--domain", choices=["mathematics", "theoretical-physics"], default="theoretical-physics")
    run.add_argument("--cycles", type=int, default=1)
    run.add_argument("--limit", type=int, default=8)
    run.add_argument("--arm", choices=arms, default="verifier", help="improvement arm after each research round")
    run.add_argument("--samples", type=int, default=1, help="solver arm: independent attempts per problem (1..5)")
    run.add_argument("--refresh-literature", action="store_true", help="query Valency before the campaign (requires standalone token)")
    mine = command("mine", "draft benchmark tasks from recent Valency records (quarantined)", True)
    mine.add_argument("--since", required=True, help="only papers first submitted on/after this ISO date")
    mine.add_argument("--query", help="fresh standalone Valency search before mining (requires VALENCY_TOKEN)")
    mine.add_argument("--batches", type=int, default=1)
    mine.add_argument("--batch-size", type=int, default=6)
    drafts = command("drafts", "list quarantined benchmark drafts or export them for independent review")
    drafts.add_argument("--origin", help="only drafts from this origin, e.g. valency-miner")
    drafts.add_argument("--export", type=Path, help="write a pending-review development-suite file")
    command("findings", "list research findings and their review status")
    handoff = command("handoff", "assign a research finding to a Danus worker via `danus assign`")
    handoff.add_argument("finding")
    handoff.add_argument("--target", required=True, help="<project>/<worker>")
    handoff.add_argument("--danus-root", help="Danus installation; defaults to DANUS_ROOT or /opt/danus")
    handoff.add_argument("--allow-unresolved", action="store_true", help="hand off an unsupported finding as an open subproblem")
    handoff.add_argument("--confirm", action="store_true", help="actually replace the worker's TASK.md; otherwise dry run")
    sync = command("handoff-sync", "read Danus verifier outcomes for handed-off findings (read-only)")
    sync.add_argument("--danus-root", help="Danus installation; defaults to DANUS_ROOT or /opt/danus")
    audit = command("audit", "evaluate on a fresh independently reviewed private batch (verifier or solver, by file split)", True)
    audit.add_argument("--candidate", required=True)
    audit.add_argument("--file", type=Path, required=True)
    audit.add_argument("--promote", action="store_true")
    audit.add_argument("--samples", type=int, default=1, help="solver audits: independent attempts per problem (1..5)")
    promote = command("promote", "activate a previously eligible live audit evaluation")
    promote.add_argument("evaluation")
    rollback = command("rollback", "restore a previously active policy")
    rollback.add_argument("policy")
    curriculum = command("import-curriculum", "import reviewed development tasks; never treat them as holdout")
    curriculum.add_argument("file", type=Path)
    report = command("report", "regenerate a local report")
    report.add_argument("run_id")
    return p


def effective_suite(store):
    suite = load_suite()
    known = {t["id"]: t for t in suite["tasks"]}
    for entry in store.artifacts("reviewed_curriculum"):
        for task in entry["body"]["tasks"]:
            require(task["id"] not in known or known[task["id"]] == task, "imported curriculum collides with an existing task")
            known[task["id"]] = task
    suite["tasks"] = list(known.values())
    return validate_suite(suite)


def export_drafts(drafts, path):
    """A review worksheet, not a curriculum: import-curriculum rejects it until a reviewer signs it."""
    tasks = []
    for draft in drafts:
        body = draft["body"]
        tasks.append(dict(body["task"], draft_id=draft["id"], origin=body.get("origin", "verifier-optimizer"),
                          source_papers=body.get("source_papers", []), review_notes=body.get("review_notes", "")))
    save_json(path, {"split": "development", "review_status": "pending-review", "reviewer": "",
                     "provenance": "Unreviewed model drafts exported for independent review. Check every statement, "
                                   "hypothesis and reference against the cited full papers; edit or delete tasks, then set "
                                   "review_status=independently-reviewed and reviewer before import-curriculum.",
                     "tasks": tasks})
    return str(path)


def execute(args):
    store = Store(args.state)
    initial = initialize(store)
    if args.command == "init":
        return initial | {"state": str(store.directory)}
    if args.command == "status":
        return initial | {"runs": store.runs(), "policies": [p["id"] for p in store.artifacts("policy")],
                          "unreviewed_drafts": len(store.artifacts("benchmark_draft")), "event_chain_head": store.check_integrity()}
    if args.command == "literature":
        if args.query:
            return {"snapshot": import_snapshot(store, search(args.query, args.limit))}
        if args.import_file:
            value = read_json(args.import_file)
            return {"snapshots": [import_snapshot(store, v) for v in value.get("snapshots", [value])]}
        return {"papers": store.artifacts("paper")}
    if args.command == "promote":
        store.promote(args.evaluation, code_hash(), digest(effective_suite(store)))
        return {"active_policy": store.active()}
    if args.command == "rollback":
        store.rollback(args.policy)
        return {"active_policy": store.active()}
    if args.command == "import-curriculum":
        value = validate_suite(read_json(args.file))
        require(value.get("review_status") == "independently-reviewed" and bool(value.get("reviewer")), "curriculum needs independent review and a reviewer identity")
        existing = {t["id"]: t for t in effective_suite(store)["tasks"]}
        require(all(t["id"] not in existing or existing[t["id"]] == t for t in value["tasks"]), "curriculum changes an existing immutable task ID")
        key = store.put("reviewed_curriculum", value)
        store.put("development_suite", value)
        return {"curriculum": key, "tasks": len(value["tasks"])}
    if args.command == "report":
        saved = next((r["body"] for r in store.artifacts("run_result") if r["body"]["run_id"] == args.run_id), None)
        require(saved is not None, "no saved result for this run")
        return write_report(store, args.run_id, saved["result"])
    if args.command == "drafts":
        selected = [d for d in store.artifacts("benchmark_draft") if args.origin is None or d["body"].get("origin") == args.origin]
        if args.export:
            return {"export": export_drafts(selected, args.export), "tasks": len(selected)}
        return {"drafts": [{"id": d["id"], "origin": d["body"].get("origin", "verifier-optimizer"), "title": d["body"]["task"]["title"],
                            "domain": d["body"]["task"]["domain"], "review_status": d["body"]["review_status"]} for d in selected]}
    if args.command == "findings":
        return {"findings": [{"id": f["id"], "run": f["body"]["run"], "status": f["body"]["finding"]["status"],
                              "domain": f["body"]["finding"]["task"]["domain"], "title": f["body"]["finding"]["task"]["title"]}
                             for f in store.artifacts("research_finding")]}
    if args.command == "handoff":
        return bridge.assign(store, args.finding, args.target, args.danus_root, args.confirm, args.allow_unresolved)
    if args.command == "handoff-sync":
        return bridge.sync(store, args.danus_root)
    config = dict(DEFAULT_CONFIG)
    if args.config:
        override = read_json(args.config)
        require(set(override) <= set(config), "unknown configuration field")
        config.update(override)
    if args.max_calls is not None:
        config["max_calls"] = args.max_calls
    if args.deadline is not None:
        config["deadline_seconds"] = args.deadline
    validate_config(config)
    require(not hasattr(args, "cycles") or 1 <= args.cycles <= 5, "cycles must be 1..5")
    require(not hasattr(args, "samples") or 1 <= args.samples <= 5, "samples must be 1..5")
    require(not (args.command == "improve" and args.arm == "verifier" and args.samples != 1),
            "--samples applies to the solver arm; verifier cases are fixed candidates")
    suite = effective_suite(store)
    policy = args.policy or store.active()
    store.get(policy, "policy")
    if args.command == "audit":
        require(args.resume is None, "audit batches are single-use; interrupted audits need a fresh batch")
    if args.command == "run" and args.refresh_literature:
        import_snapshot(store, search(args.objective, 10))
    if args.command == "mine" and args.query:
        import_snapshot(store, search(args.query, 20))
    papers = None
    if args.command in ("mine", "demo"):
        papers = eligible_papers([p["body"] for p in store.artifacts("paper")], getattr(args, "since", DEMO_MINING_SINCE))
        # Fail before reserving a run: nothing to mine is an input problem, not a model failure.
        require(bool(papers) or args.command == "demo", "no dated math/physics Valency records on or after --since; import a recent connector export first")
    backend = ScriptedAgents() if args.command == "demo" else LiveAgents(config)
    engine = Engine(store, backend, config, args.retry_errors)
    audit = read_json(args.file) if args.command == "audit" else None
    if audit is not None and audit.get("split") != "solver-audit":
        require(args.samples == 1, "--samples applies to solver audits; verifier audit cases are fixed candidates")
    payload = {"suite": digest(suite), "policy": policy, "limit": getattr(args, "limit", None),
               "cycles": getattr(args, "cycles", None), "objective": getattr(args, "objective", None),
               "domain": getattr(args, "domain", None), "candidate": getattr(args, "candidate", None),
               "arm": getattr(args, "arm", None), "since": getattr(args, "since", None), "samples": getattr(args, "samples", None),
               "mining": [p["source"] + ":" + p["id"] for p in papers] if papers is not None else None,
               "audit": digest(audit) if audit else None,
               "literature": [p["id"] for p in store.artifacts("paper")]}
    run_id = engine.start(args.command, payload, args.resume)
    try:
        if args.command in ("demo", "run"):
            objective = getattr(args, "objective", "Inspect hypotheses in EFT power counting and mathematical proof verification")
            domain = getattr(args, "domain", "theoretical-physics")
            # Facts the Danus native verifier accepted are the only trusted prior results.
            rounds, current, memory = [], policy, bridge.verified_memory(store)
            for n in range(args.cycles):
                research = engine.research(objective, domain, current, f"round/{n}/research", memory)
                arm = args.arm if args.arm != "alternate" else ("verifier", "solver")[n % 2]
                if arm == "solver":
                    improvement = engine.improve_solver(suite, current, 1, args.limit, f"round/{n}/solver-rsi", getattr(args, "samples", 1))
                else:
                    improvement = engine.improve(suite, current, 1, args.limit, f"round/{n}/rsi")
                current = improvement["selected_development_policy"]
                # Preserve provenance and unresolved status; never convert a model
                # review into a trusted fact in subsequent planning.
                memory = bridge.verified_memory(store) + [{"claim": f["solution"]["claim"], "status": f["status"], "evidence_id": f["evidence_id"]}
                                                          for f in research["findings"]]
                rounds.append({"research": research, "improvement": improvement})
            result = {"kind": "campaign", "rounds": rounds, "development_policy": current, "active_policy": store.active()}
            if args.command == "demo" and papers:
                result["mining"] = engine.mine(papers, 1, 2, "demo/mine", engine.exposures(suite))
        elif args.command == "benchmark":
            result = engine.benchmark(suite, policy, args.limit)
        elif args.command == "improve" and args.arm == "solver":
            result = engine.improve_solver(suite, policy, args.cycles, args.limit, samples=args.samples)
        elif args.command == "improve":
            result = engine.improve(suite, policy, args.cycles, args.limit)
        elif args.command == "mine":
            result = engine.mine(papers, args.batches, args.batch_size, exposed=engine.exposures(suite))
        elif audit.get("split") == "solver-audit":
            result = engine.audit_solver(audit, suite, args.candidate, args.promote, args.samples)
        else:
            result = engine.audit(audit, suite, args.candidate, args.promote)
        store.finish_run(run_id, "complete")
        return {"run_id": run_id, "mode": backend.mode, "calls": store.run(run_id)["calls"],
                "active_policy": store.active(), **write_report(store, run_id, result)}
    except BaseException as exc:
        store.finish_run(run_id, "budget-exhausted" if isinstance(exc, BudgetExceeded) else "error")
        raise


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, StopIteration) as exc:
        print(f"danus-rsi: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("danus-rsi: interrupted; reserved calls remain charged", file=sys.stderr)
        return 130
