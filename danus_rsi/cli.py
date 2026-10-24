"""Command line entry point; all live runs require an explicit command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import bridge, doctor
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
            q.add_argument("--retry-errors", action="store_true",
                           help="retry cached transport errors once within the original budget")
            q.add_argument("--policy", help="policy artifact ID; defaults to the active version")
            q.add_argument("--estimate", action="store_true",
                           help="print the upper bound of calls this command reserves; start nothing")
        return q
    command("init", "initialize state, development data and Valency seed records")
    command("status", "show runs, policies, drafts and event integrity")
    lit = command("literature", "query Valency or import a connector result/export")
    action = lit.add_mutually_exclusive_group()
    action.add_argument("--query")
    action.add_argument("--import-file", type=Path)
    lit.add_argument("--limit", type=int, default=10)
    arms = ["verifier", "solver", "alternate"]
    samples_help = "solver arm: independent attempts per problem (1..5)"
    demo = command("demo", "run deterministic fixtures without credentials", True)
    demo.add_argument("--cycles", type=int, default=2)
    demo.add_argument("--limit", type=int, default=4)
    demo.add_argument("--arm", choices=arms, default="alternate", help="improvement arm after each research round")
    bench = command("benchmark", "solve and judge public development problems", True)
    bench.add_argument("--limit", type=int, default=4)
    rsi = command("improve", "recursively propose/evaluate development strategies", True)
    rsi.add_argument("--cycles", type=int, default=2)
    rsi.add_argument("--limit", type=int, default=8)
    rsi.add_argument("--arm", choices=arms[:2], default="verifier",
                     help="verifier: labeled calibration; solver: verifier-gated solve rate")
    rsi.add_argument("--samples", type=int, default=1, help=samples_help)
    run = command("run", "run a research campaign with development RSI after each round", True)
    run.add_argument("--objective", required=True)
    run.add_argument("--domain", choices=["mathematics", "theoretical-physics"], default="theoretical-physics")
    run.add_argument("--cycles", type=int, default=1)
    run.add_argument("--limit", type=int, default=8)
    run.add_argument("--arm", choices=arms, default="verifier", help="improvement arm after each research round")
    run.add_argument("--samples", type=int, default=1, help=samples_help)
    run.add_argument("--refresh-literature", action="store_true",
                     help="query Valency before the campaign (requires standalone token)")
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
    handoff.add_argument("--allow-unresolved", action="store_true",
                         help="hand off an unsupported finding as an open subproblem")
    handoff.add_argument("--confirm", action="store_true",
                         help="actually replace the worker's TASK.md; otherwise dry run")
    sync = command("handoff-sync", "read Danus verifier outcomes for handed-off findings (read-only)")
    sync.add_argument("--danus-root", help="Danus installation; defaults to DANUS_ROOT or /opt/danus")
    audit = command("audit", "evaluate on a fresh independently reviewed private batch "
                             "(verifier or solver, by file split)", True)
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
    readiness = command("doctor", "check live-run readiness: Linux, Danus, login, verifier (read-only)")
    readiness.add_argument("--config", type=Path)
    template = command("audit-template", "write a private audit worksheet for a reviewer to fill in")
    template.add_argument("--arm", choices=["verifier", "solver"], required=True)
    template.add_argument("--out", type=Path, required=True, help="a path outside this repository")
    check = command("audit-check", "validate a private audit file and check freshness without consuming it")
    check.add_argument("file", type=Path)
    return p


RESEARCH_ROUND_MAX = 2 + 3 * 7  # curator, planner, then <= 3 x (researcher, critic, repair, native, 3 judges)


def estimate(args, suite, papers, audit, config):
    """Upper bound on reserved calls, computed from the same selections the engine uses."""
    from .engine import balanced_selection
    from .protocol import calibration_cases
    limit, samples = getattr(args, "limit", None), getattr(args, "samples", 1)
    verifier_cycle = lambda: 8 * len(balanced_selection(calibration_cases(suite), limit)) + 1
    solver_cycle = lambda: 10 * samples * len(balanced_selection(suite["tasks"], limit)) + 1
    parts = []
    if args.command in ("demo", "run"):
        for n in range(args.cycles):
            arm = args.arm if args.arm != "alternate" else ("verifier", "solver")[n % 2]
            parts.append((f"round {n + 1} research, at most", RESEARCH_ROUND_MAX))
            parts.append((f"round {n + 1} {arm} cycle", solver_cycle() if arm == "solver" else verifier_cycle()))
        if args.command == "demo" and papers:
            parts.append(("mining batch", 1))
    elif args.command == "benchmark":
        parts.append(("benchmark problems x 5 calls", 5 * len(balanced_selection(suite["tasks"], limit))))
    elif args.command == "improve":
        cycle = solver_cycle if args.arm == "solver" else verifier_cycle
        parts += [(f"{args.arm} cycle {c + 1}", cycle()) for c in range(args.cycles)]
    elif args.command == "mine":
        # Before a --query search the paper count is unknown, so every batch may run.
        batches = min(args.batches, -(-len(papers) // args.batch_size)) if papers else args.batches
        parts.append(("mining batches", batches))
    elif audit.get("split") == "solver-audit":
        parts.append((f"solver audit: problems x {samples} sample(s) x 10", 10 * samples * len(audit.get("tasks", []))))
    else:
        parts.append(("verifier audit: (cases + regression) x 8",
                      8 * (len(audit.get("cases", [])) + len(calibration_cases(suite)))))
    total = sum(calls for _, calls in parts)
    return {"estimate": True, "command": args.command, "upper_bound_calls": total, "max_calls": config["max_calls"],
            "fits": total <= config["max_calls"], "breakdown": [{"step": s, "calls": c} for s, c in parts],
            "note": "Upper bound on reserved interface calls, not tokens or money. No run was started."}


def audit_template(arm, out):
    """A worksheet that cannot pass validation until a reviewer completes and signs it."""
    root = Path(__file__).resolve().parents[1]
    target = Path(out).resolve()
    require(not target.is_relative_to(root) or target.is_relative_to(root / ".state"),
            "keep private audit files outside this repository (or under its git-ignored .state/)")
    require(not target.exists(), "refusing to overwrite an existing file")
    def task(domain, n):
        return {"id": f"REPLACE-{domain}-{n}", "family_id": "REPLACE-stable-family-of-the-underlying-result",
                "title": "REPLACE", "domain": domain,
                "prompt": "REPLACE: precisely stated question with every hypothesis and convention",
                "reference": "REPLACE: independently checked argument", "rubric": ["REPLACE: checkable condition"]}
    common = {"id": "REPLACE-unique-batch-id", "review_status": "template-unreviewed", "reviewer": "",
              "provenance": "", "instructions": "Fill every REPLACE field, delete this key if you like, then set "
              "review_status to independently-reviewed and name the reviewer. Problems must never have been shown to "
              "this system: run audit-check before using the file. A batch is consumed on first use, even if "
              "interrupted."}
    if arm == "solver":
        body = dict(common, split="solver-audit",
                    requirements="at least 12 problems, 8 families, 5 per domain; no candidate proofs",
                    tasks=[task("mathematics", 1), task("theoretical-physics", 1)])
    else:
        solution = {"answer": "REPLACE", "claim": "REPLACE: exact claim",
                    "proof": "REPLACE: candidate proof, valid or deliberately flawed"}
        body = dict(common, split="audit",
                    requirements="at least 20 cases, 10 families, 5 valid and 5 invalid per domain",
                    cases=[{"id": f"REPLACE-case-{d}", "label": "valid or invalid", "task": task(d, 1),
                            "solution": solution} for d in ("mathematics", "theoretical-physics")])
    save_json(target, body)
    return {"template": str(target), "arm": arm, "requirements": body["requirements"]}


def audit_check(store, suite, path):
    """Validation, exposure and freshness only. Reserves nothing and prints no case content."""
    from .engine import exposed_tasks
    from .protocol import ProtocolError, calibration_cases, validate_audit, validate_solver_audit
    audit = read_json(path)
    split = audit.get("split")
    require(split in ("audit", "solver-audit"), "expected split audit or solver-audit")
    solver = split == "solver-audit"
    result = {"file": str(path), "arm": "solver" if solver else "verifier"}
    try:
        (validate_solver_audit if solver else validate_audit)(audit, exposed_tasks(store, suite))
        result.update(valid=True, problem=None)
    except (ProtocolError, KeyError, TypeError, AttributeError) as exc:
        result.update(valid=False, problem=f"{type(exc).__name__}: {exc}")
    entries = audit.get("tasks", []) if solver else audit.get("cases", [])
    counts = {}
    for entry in entries:
        task = entry if solver else entry.get("task", {})
        key = task.get("domain", "?") if solver else f"{task.get('domain', '?')}/{entry.get('label', '?')}"
        counts[key] = counts.get(key, 0) + 1
    result.update(entries=len(entries), counts=counts,
                  families=len({(e if solver else e.get("task", {})).get("family_id") for e in entries}))
    try:
        result.update(store.audit_status(audit))
    except (KeyError, TypeError, AttributeError):
        result.update(batch_consumed=None, consumed_problem_keys=None)
    result["fresh"] = bool(result["valid"] and result["batch_consumed"] is False
                           and result["consumed_problem_keys"] == 0)
    if solver:
        result["calls_per_sample"] = 10 * len(entries)
    else:
        result["calls"] = 8 * (len(entries) + len(calibration_cases(suite)))
    result["note"] = "Read-only: nothing was reserved or exposed, and no case content is printed."
    return result


def effective_suite(store):
    suite = load_suite()
    known = {t["id"]: t for t in suite["tasks"]}
    for entry in store.artifacts("reviewed_curriculum"):
        for task in entry["body"]["tasks"]:
            require(task["id"] not in known or known[task["id"]] == task,
                    "imported curriculum collides with an existing task")
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
                                   "hypothesis and reference against the cited full papers; edit or delete tasks, "
                                   "then set review_status=independently-reviewed and reviewer before "
                                   "import-curriculum.",
                     "tasks": tasks})
    return str(path)


def load_config(path):
    """Defaults overridden by an optional JSON file; unknown fields are refused."""
    config = dict(DEFAULT_CONFIG)
    if path:
        override = read_json(path)
        require(set(override) <= set(config), "unknown configuration field")
        config.update(override)
    return config


def execute(args):
    store = Store(args.state)
    initial = initialize(store)
    if args.command == "init":
        return initial | {"state": str(store.directory)}
    if args.command == "status":
        return initial | {"runs": store.runs(), "policies": [p["id"] for p in store.artifacts("policy")],
                          "unreviewed_drafts": len(store.artifacts("benchmark_draft")),
                          "event_chain_head": store.check_integrity()}
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
        require(value.get("review_status") == "independently-reviewed" and bool(value.get("reviewer")),
                "curriculum needs independent review and a reviewer identity")
        existing = {t["id"]: t for t in effective_suite(store)["tasks"]}
        require(all(t["id"] not in existing or existing[t["id"]] == t for t in value["tasks"]),
                "curriculum changes an existing immutable task ID")
        key = store.put("reviewed_curriculum", value)
        store.put("development_suite", value)
        return {"curriculum": key, "tasks": len(value["tasks"])}
    if args.command == "report":
        saved = next((r["body"] for r in store.artifacts("run_result") if r["body"]["run_id"] == args.run_id), None)
        require(saved is not None, "no saved result for this run")
        return write_report(store, args.run_id, saved["result"])
    if args.command == "drafts":
        selected = [d for d in store.artifacts("benchmark_draft")
                    if args.origin is None or d["body"].get("origin") == args.origin]
        if args.export:
            return {"export": export_drafts(selected, args.export), "tasks": len(selected)}
        return {"drafts": [{"id": d["id"], "origin": d["body"].get("origin", "verifier-optimizer"),
                            "title": d["body"]["task"]["title"], "domain": d["body"]["task"]["domain"],
                            "review_status": d["body"]["review_status"]} for d in selected]}
    if args.command == "findings":
        return {"findings": [{"id": f["id"], "run": f["body"]["run"], "status": f["body"]["finding"]["status"],
                              "domain": f["body"]["finding"]["task"]["domain"],
                              "title": f["body"]["finding"]["task"]["title"]}
                             for f in store.artifacts("research_finding")]}
    if args.command == "handoff":
        return bridge.assign(store, args.finding, args.target, args.danus_root, args.confirm, args.allow_unresolved)
    if args.command == "handoff-sync":
        return bridge.sync(store, args.danus_root)
    if args.command == "audit-template":
        return audit_template(args.arm, args.out)
    if args.command == "audit-check":
        return audit_check(store, effective_suite(store), args.file)
    if args.command == "doctor":
        return doctor.diagnose(validate_config(load_config(args.config)), store.directory)
    config = load_config(args.config)
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
    # An estimate touches nothing external: no literature search, no backend, no run.
    if args.command == "run" and args.refresh_literature and not args.estimate:
        import_snapshot(store, search(args.objective, 10))
    if args.command == "mine" and args.query and not args.estimate:
        import_snapshot(store, search(args.query, 20))
    papers = None
    if args.command in ("mine", "demo"):
        papers = eligible_papers([p["body"] for p in store.artifacts("paper")],
                                 getattr(args, "since", DEMO_MINING_SINCE))
        # Fail before reserving a run: nothing to mine is an input problem, not a model failure.
        require(bool(papers) or args.command == "demo" or (args.estimate and args.query),
                "no dated math/physics Valency records on or after --since; import a recent connector export first")
    audit = read_json(args.file) if args.command == "audit" else None
    if audit is not None and audit.get("split") != "solver-audit":
        require(args.samples == 1, "--samples applies to solver audits; verifier audit cases are fixed candidates")
    if args.estimate:
        return estimate(args, suite, papers, audit, config)
    backend = ScriptedAgents() if args.command == "demo" else LiveAgents(config)
    engine = Engine(store, backend, config, args.retry_errors)
    payload = {"suite": digest(suite), "policy": policy, "limit": getattr(args, "limit", None),
               "cycles": getattr(args, "cycles", None), "objective": getattr(args, "objective", None),
               "domain": getattr(args, "domain", None), "candidate": getattr(args, "candidate", None),
               "arm": getattr(args, "arm", None), "since": getattr(args, "since", None),
               "samples": getattr(args, "samples", None),
               "mining": [p["source"] + ":" + p["id"] for p in papers] if papers is not None else None,
               "audit": digest(audit) if audit else None,
               "literature": [p["id"] for p in store.artifacts("paper")]}
    run_id = engine.start(args.command, payload, args.resume)
    try:
        if args.command in ("demo", "run"):
            objective = getattr(args, "objective",
                                "Inspect hypotheses in EFT power counting and mathematical proof verification")
            domain = getattr(args, "domain", "theoretical-physics")
            # Facts the Danus native verifier accepted are the only trusted prior results.
            rounds, current, memory = [], policy, bridge.verified_memory(store)
            for n in range(args.cycles):
                research = engine.research(objective, domain, current, f"round/{n}/research", memory)
                arm = args.arm if args.arm != "alternate" else ("verifier", "solver")[n % 2]
                if arm == "solver":
                    improvement = engine.improve_solver(suite, current, 1, args.limit, f"round/{n}/solver-rsi",
                                                        getattr(args, "samples", 1))
                else:
                    improvement = engine.improve(suite, current, 1, args.limit, f"round/{n}/rsi")
                current = improvement["selected_development_policy"]
                # Preserve provenance and unresolved status; never convert a model
                # review into a trusted fact in subsequent planning.
                memory = bridge.verified_memory(store) + [
                    {"claim": f["solution"]["claim"], "status": f["status"], "evidence_id": f["evidence_id"]}
                    for f in research["findings"]]
                rounds.append({"research": research, "improvement": improvement})
            result = {"kind": "campaign", "rounds": rounds, "development_policy": current,
                      "active_policy": store.active()}
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
