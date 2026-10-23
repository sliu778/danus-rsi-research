"""Bounded research DAG and recursive development of verifier and solver strategies."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
from pathlib import Path
import time

from . import agents, transport as t
from .protocol import (DATA, DOMAINS, FROZEN_PROTOCOL, ROLES, SOLVER_PROTOCOL, ProtocolError, calibration_cases, digest, metrics,
                       promotion_gate, read_json, require, require_arm_change, require_no_copied_answers, save_json,
                       solve_metrics, solver_gate, validate_audit, validate_policy, validate_solver_audit, validate_suite, validate_task)
from .store import BudgetExceeded
from .valency import import_snapshot, paper_domains

DEFAULT_CONFIG = {"model": "gpt-6-astra", "effort": "xhigh", "workers": 3,
                  "max_calls": 160, "deadline_seconds": 14400,
                  "call_timeout_seconds": 600, "verify_timeout_seconds": 960,
                  "verify_url": "http://127.0.0.1:8091/verify"}
BASELINE = {"name": "Danus panel baseline v1", "solver_guidance": "Give explicit hypotheses, a checkable argument, and limitations.",
            "verifier_guidance": "Check each inference, theorem hypothesis, boundary case and the response to the original question.",
            "curriculum_domains": ["mathematics", "theoretical-physics"],
            "rationale": "Initial authored strategy; no measured research or verifier improvement is claimed."}


def code_hash():
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))})


def validate_config(config):
    require(set(config) == set(DEFAULT_CONFIG), "unknown engine configuration")
    for key in ("workers", "max_calls", "deadline_seconds", "call_timeout_seconds", "verify_timeout_seconds"):
        require(type(config[key]) is int and config[key] > 0, "invalid " + key)
    require(config["workers"] <= 3, "at most three concurrent panel sessions")
    require(config["max_calls"] <= 10000 and config["deadline_seconds"] <= 86400, "run budget exceeds configured hard bounds")
    require(isinstance(config["model"], str) and config["model"].strip(), "model must be a nonempty identifier")
    require(config["effort"] in ("low", "medium", "high", "xhigh", "max", "ultra"), "invalid reasoning effort")
    from urllib.parse import urlparse
    endpoint = urlparse(config["verify_url"])
    require(endpoint.scheme == "http" and endpoint.hostname in ("localhost", "127.0.0.1", "::1") and endpoint.path == "/verify"
            and not endpoint.username and not endpoint.query and not endpoint.fragment, "native verifier must use a loopback /verify endpoint")
    return config


def load_suite():
    suite = read_json(DATA / "development.json")
    suite["tasks"] += read_json(DATA / "physics.json")["tasks"]
    return validate_suite(suite)


def initialize(store):
    policy_id = store.put("policy", BASELINE)
    store.initialize_policy(policy_id)
    suite = load_suite()
    store.put("development_suite", suite)
    for snapshot in read_json(DATA / "valency-seed.json")["snapshots"]:
        import_snapshot(store, snapshot)
    return {"active_policy": store.active(), "tasks": len(suite["tasks"]), "calibration_cases": len(calibration_cases(suite)),
            "valency_papers": len(store.artifacts("paper"))}


def balanced_selection(items, limit):
    require(type(limit) is int and limit > 0, "limit must be positive")
    buckets = {d: [i for i in items if i.get("domain", i.get("task", {}).get("domain")) == d] for d in sorted(DOMAINS)}
    selected = []
    while len(selected) < limit and any(buckets.values()):
        for bucket in buckets.values():
            if bucket and len(selected) < limit:
                selected.append(bucket.pop(0))
    return selected


def decision_from(judgments, native):
    if native["status"] != "ok" or any(j["status"] != "ok" for j in judgments):
        return "error"
    data = [j["data"] for j in judgments]
    if any(j["reference_concern"].strip() or j["verdict"] == "uncertain" for j in data):
        return "abstain"
    if len({j["verdict"] for j in data}) != 1:
        return "abstain"
    if t.aggregate(judgments, native)["strict_pass"]:
        return "accept"
    # A rejection requires a concrete defect and a unanimous negative panel.
    # A merely low completeness score or a conflicting native result is uncertainty.
    if all(j["verdict"] == "incorrect" and (j["critical_errors"] or j["gaps"]) for j in data):
        return "reject"
    return "abstain"


def solver_feedback(task, row):
    """What the solver optimizer may see: statement, decision and stated defects, never the reference."""
    defects = []
    panel = row.get("panel", {})
    for judgment in panel.get("judgments", {}).values():
        if judgment["status"] == "ok":
            defects += judgment["data"]["critical_errors"] + judgment["data"]["gaps"]
    native = panel.get("native", {})
    if native.get("status") == "ok":
        report = native["data"]["verification_report"]
        defects += [item["issue"] for item in report["critical_errors"] + report["gaps"]]
    solution = row["solution"]
    return {"task_id": task["id"], "domain": task["domain"], "prompt": task["prompt"], "decision": row["decision"],
            "claim": solution["data"]["claim"] if solution["status"] == "ok" else None, "defects": defects}


class Engine:
    def __init__(self, store, backend, config=None, retry_errors=False):
        self.store, self.backend = store, backend
        self.retry_errors = retry_errors
        self.config = validate_config(dict(DEFAULT_CONFIG, **(config or {})))
        self.run_id = None

    def start(self, kind, payload, run_id=None):
        manifest = {"kind": kind, "payload": payload, "config": self.config, "mode": self.backend.mode,
                    "backend": self.backend.provenance, "protocol": FROZEN_PROTOCOL, "code_hash": code_hash()}
        self.run_id = self.store.new_run(manifest, self.config["max_calls"], self.config["deadline_seconds"], run_id)
        return self.run_id

    def call(self, key, role, prompt=None, schema=None, context=None, solution=None):
        require(self.run_id is not None, "start a run before scheduling calls")
        configured_timeout = self.config["verify_timeout_seconds"] if role == "native" else self.config["call_timeout_seconds"]
        timeout = max(0.01, min(configured_timeout, self.store.run(self.run_id)["deadline"] - time.time()))
        request = {"role": role, "prompt": prompt, "schema": schema, "solution": solution,
                   "model": self.config["model"], "effort": self.config["effort"], "mode": self.backend.mode}
        token, cached = self.store.claim(self.run_id, key, request, timeout + 30, self.retry_errors)
        if token is None:
            return cached
        directory = self.store.directory / "calls" / self.run_id / digest(key) / token
        directory.mkdir(parents=True, exist_ok=True)
        save_json(directory / "request.json", request)
        started = time.monotonic()
        try:
            if role == "native":
                value, usage = self.backend.verify(solution, timeout)
                t.validate_native(value)
            else:
                value, usage = self.backend.generate(role, prompt, schema, context or {}, directory, timeout)
                t.validate_schema(value, schema)
                agents.validate_role(role, value)
            result = {"status": "ok", "data": value, "usage": usage}
        except Exception as exc:
            result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)[:2000]}
        result.update(elapsed_seconds=time.monotonic() - started, evidence=str(directory.relative_to(self.store.directory)))
        save_json(directory / "result.json", result)
        self.store.finish(self.run_id, key, token, result)
        return result

    @staticmethod
    def data(result):
        require(result["status"] == "ok", "agent failed: " + result.get("error", "unknown failure"))
        return result["data"]

    def panel(self, key, task, solution, policy):
        native = self.call(key + "/native", "native", solution=solution)
        def judge(role):
            return self.call(key + "/" + role, role, agents.verification_prompt(task, solution, policy, role), t.JUDGE_SCHEMA)
        with ThreadPoolExecutor(max_workers=self.config["workers"]) as pool:
            judgments = list(pool.map(judge, ROLES))
        return {"decision": decision_from(judgments, native), "native": native,
                "judgments": dict(zip(ROLES, judgments)), "aggregate": t.aggregate(judgments, native)}

    def evaluate(self, key, cases, policy_id):
        policy = self.store.get(policy_id, "policy")
        rows = []
        for index, case in enumerate(cases):
            # The numeric schedule key does not disclose the calibration label.
            panel = self.panel(f"{key}/{index}", case["task"], case["solution"], policy)
            rows.append({"case_id": case["id"], "domain": case["task"]["domain"], "label": case["label"],
                         "decision": panel["decision"], "panel": panel})
        return rows

    def solve(self, key, task, policy):
        """One generated attempt judged by the strict panel under the same policy's verifier guidance."""
        prompt = t.solver_prompt(task) + "\n" + agents.PHYSICS + "\nSolver strategy:\n" + policy["solver_guidance"]
        generated = self.call(key + "/solve", "solver", prompt, t.SOLUTION_SCHEMA)
        row = {"task_id": task["id"], "domain": task["domain"], "solution": generated}
        if generated["status"] == "ok":
            row["panel"] = self.panel(key + "/panel", task, generated["data"], policy)
            row["decision"] = row["panel"]["decision"]
        else:
            row["decision"] = "error"
        return row

    def benchmark(self, suite, policy_id, limit):
        policy = self.store.get(policy_id, "policy")
        rows = [self.solve(f"benchmark/{index}", task, policy) for index, task in enumerate(balanced_selection(suite["tasks"], limit))]
        return {"kind": "benchmark", "policy": policy_id, "rows": rows}

    def exposures(self, suite):
        """Every problem statement a model or optimizer has already seen."""
        exposed = suite["tasks"] + [x["body"] for x in self.store.artifacts("exposed_task")]
        exposed += [t for s in self.store.artifacts("development_suite") for t in s["body"]["tasks"]]
        exposed += [x["body"]["task"] for x in self.store.artifacts("benchmark_draft")]
        return exposed

    def research(self, objective, domain, policy_id, prefix="research", memory=None):
        require(domain in DOMAINS, "unsupported research domain")
        policy = self.store.get(policy_id, "policy")
        papers = [p["body"] for p in self.store.artifacts("paper")][-30:]
        curator = self.data(self.call(prefix + "/curator", "curator", agents.prompt_for("curator", {"objective": objective, "papers": papers}),
                                      agents.CURATOR_SCHEMA, {"papers": papers}))
        require(set(curator["paper_ids"]) <= {p["source"] + ":" + p["id"] for p in papers}, "curator cited an unavailable Valency record")
        plan = self.data(self.call(prefix + "/planner", "planner", agents.prompt_for("planner", {
            "objective": objective, "literature": curator, "prior_findings": memory or [], "strategy": policy["solver_guidance"],
            "curriculum_focus": policy["curriculum_domains"]}), agents.PLAN_SCHEMA))
        findings = []
        for index, problem in enumerate(plan["subproblems"]):
            payload = {"objective": objective, "subproblem": problem, "assumptions": plan["assumptions"],
                       "literature": [p for p in papers if p["source"] + ":" + p["id"] in curator["paper_ids"]], "strategy": policy["solver_guidance"]}
            key = f"{prefix}/{index}"
            solution = self.data(self.call(key + "/researcher", "researcher", agents.prompt_for("researcher", payload), t.SOLUTION_SCHEMA))
            critique = self.data(self.call(key + "/critic", "critic", agents.prompt_for("critic", {"problem": problem, "candidate": solution}), agents.CRITIC_SCHEMA))
            # Repair is a bounded second attempt. Judges do not see the critic's vote.
            if critique["objections"]:
                solution = self.data(self.call(key + "/repair", "researcher", agents.prompt_for("researcher", payload | {"candidate": solution, "critique": critique}), t.SOLUTION_SCHEMA))
            task = {"id": digest(problem)[:16], "family_id": digest({"objective": objective, "problem": problem}),
                    "domain": domain, "title": problem[:120], "prompt": problem + "\nResearch objective: " + objective + "\nAssumptions: " + "; ".join(plan["assumptions"]),
                    "reference": "Open research proposal: no trusted reference is available. Require a self-contained argument and flag unresolved dependencies.",
                    "rubric": ["Answer the stated subproblem", "State assumptions and dependencies", "Distinguish proved conclusions from conjectures", agents.PHYSICS]}
            self.store.put("exposed_task", task)
            panel = self.panel(key + "/panel", task, solution, policy)
            finding = {"task": task, "solution": solution, "critique": critique, "panel": panel,
                       "status": "panel-supported proposal" if panel["decision"] == "accept" else "unresolved",
                       "validation": "Informal model reviews; requires independent expert assessment; no novelty claim."}
            evidence_id = self.store.put("research_finding", {"run": self.run_id, "finding": finding})
            findings.append(finding | {"evidence_id": evidence_id})
        return {"kind": "research", "objective": objective, "policy": policy_id, "literature": curator, "plan": plan, "findings": findings}

    def improve(self, suite, policy_id, cycles, limit, prefix="rsi"):
        require(1 <= cycles <= 5, "RSI cycles must be 1..5")
        cases = balanced_selection(calibration_cases(suite), limit)
        results, current = [], policy_id
        for cycle in range(cycles):
            key = f"{prefix}/{cycle}"
            policy = self.store.get(current, "policy")
            baseline = self.evaluate(key + "/baseline", cases, current)
            # Only development feedback enters optimizer context, even if state
            # also contains audits. No global history/DB is exposed to an agent.
            proposal = self.data(self.call(key + "/optimizer", "optimizer", agents.prompt_for("optimizer", {
                "policy": policy, "development_cases": cases, "development_results": baseline,
                "development_metrics": metrics(baseline)}), agents.PROPOSAL_SCHEMA, {"policy": policy}))
            require(all(proposal["policy"][field] == policy[field] for field in ("solver_guidance", "curriculum_domains")),
                    "verifier optimizer changed an unevaluated solver/curriculum field")
            candidate = self.store.put("policy", validate_policy(proposal["policy"]))
            self.store.add_lineage(candidate, current, self.run_id)
            drafts = []
            for draft in proposal["drafts"]:
                draft = validate_task(dict(draft, id=digest(draft)[:20]))
                drafts.append(self.store.put("benchmark_draft", {"run": self.run_id, "parent_policy": candidate,
                                                                 "review_status": "unreviewed", "task": draft}))
            proposed = self.evaluate(key + "/candidate", cases, candidate)
            gate = promotion_gate(baseline, proposed)
            # Development selection changes this experimental branch only.
            selected = candidate if gate["eligible"] else current
            result = {"cycle": cycle + 1, "baseline": current, "candidate": candidate, "selected_for_next_cycle": selected,
                      "development_gate": gate, "baseline_rows": baseline, "candidate_rows": proposed,
                      "drafts": drafts, "production_promoted": False}
            self.store.put("improvement_cycle", {"run": self.run_id, **result})
            results.append(result)
            current = selected
        return {"kind": "rsi", "cycles": results, "selected_development_policy": current, "active_policy": self.store.active()}

    def audit(self, audit, suite, candidate_id, promote=False):
        require(self.backend.mode == "live", "scripted evaluations cannot consume audit sets or promote policies")
        candidate_policy = self.store.get(candidate_id, "policy")
        baseline_id = self.store.active()
        require(candidate_id != baseline_id, "audit candidate equals active baseline")
        baseline_policy = self.store.get(baseline_id, "policy")
        require(candidate_policy["solver_guidance"] == baseline_policy["solver_guidance"] and
                candidate_policy["curriculum_domains"] == baseline_policy["curriculum_domains"],
                "verifier audit cannot promote changes to solver strategy or curriculum; keep these fixed")
        validate_audit(audit, self.exposures(suite))
        regression = calibration_cases(suite)
        require(self.config["max_calls"] >= 8 * (len(audit["cases"]) + len(regression)), "audit call budget is too small; budget eight calls per paired case including regression")
        # Reserve before any evaluation. A failed/interrupted audit burns this batch.
        self.store.reserve_audit(audit, self.run_id)
        baseline, candidate = [], []
        for index, case in enumerate(audit["cases"]):
            # Alternate order to reduce simple ordering effects.
            order = [(baseline_id, baseline, "baseline"), (candidate_id, candidate, "candidate")]
            if index % 2:
                order.reverse()
            for policy, target, label in order:
                target.extend(self.evaluate(f"audit/{index}/{label}", [case], policy))
        b_reg = self.evaluate("regression/baseline", regression, baseline_id)
        c_reg = self.evaluate("regression/candidate", regression, candidate_id)
        gate = promotion_gate(baseline, candidate)
        for b, c in zip(b_reg, c_reg):
            correct = lambda r: r["decision"] == ("accept" if r["label"] == "valid" else "reject")
            if c["decision"] in ("error", "abstain") or b["decision"] in ("error", "abstain") or (correct(b) and not correct(c)):
                gate["reasons"].append("frozen regression failure: " + b["case_id"])
        gate["eligible"] = not gate["reasons"]
        value = {"mode": "live", "protocol": FROZEN_PROTOCOL, "code_hash": code_hash(), "baseline": baseline_id,
                 "candidate": candidate_id, "audit_digest": digest(audit), "regression_suite": digest(suite), "baseline_rows": baseline, "candidate_rows": candidate,
                 "regression_baseline": b_reg, "regression_candidate": c_reg, "gate": gate}
        evaluation = self.store.record_evaluation(self.run_id, value)
        if promote and gate["eligible"]:
            self.store.promote(evaluation, code_hash(), digest(suite))
        return {"kind": "audit", "evaluation_id": evaluation, "promoted": promote and gate["eligible"], **value}

    def improve_solver(self, suite, policy_id, cycles, limit, prefix="solver-rsi"):
        """Revise solver strategy against a verifier policy held fixed for the whole comparison."""
        require(1 <= cycles <= 5, "RSI cycles must be 1..5")
        tasks = balanced_selection(suite["tasks"], limit)
        results, current = [], policy_id
        for cycle in range(cycles):
            key = f"{prefix}/{cycle}"
            policy = self.store.get(current, "policy")
            baseline = [self.solve(f"{key}/baseline/{i}", task, policy) for i, task in enumerate(tasks)]
            proposal = self.data(self.call(key + "/optimizer", "solver_optimizer", agents.prompt_for("solver_optimizer", {
                "policy": policy, "development_results": [solver_feedback(task, row) for task, row in zip(tasks, baseline)],
                "development_metrics": solve_metrics(baseline)}), agents.SOLVER_PROPOSAL_SCHEMA, {"policy": policy}))
            revised = validate_policy(proposal["policy"])
            result = {"cycle": cycle + 1, "baseline": current, "candidate": None, "selected_for_next_cycle": current,
                      "baseline_rows": baseline, "candidate_rows": [], "production_promoted": False}
            try:
                require_arm_change("solver", policy, revised)
                require(revised["solver_guidance"] != policy["solver_guidance"], "no solver strategy change proposed")
                require_no_copied_answers(revised["solver_guidance"], suite["tasks"])
            except ProtocolError as exc:
                # A rejected proposal is evidence, not a crash: the branch stays unchanged.
                result["development_gate"] = {"eligible": False, "reasons": ["proposal rejected: " + str(exc)]}
            else:
                candidate = self.store.put("policy", revised)
                self.store.add_lineage(candidate, current, self.run_id)
                proposed = [self.solve(f"{key}/candidate/{i}", task, revised) for i, task in enumerate(tasks)]
                gate = solver_gate(baseline, proposed)
                result.update(candidate=candidate, candidate_rows=proposed, development_gate=gate,
                              selected_for_next_cycle=candidate if gate["eligible"] else current)
            self.store.put("solver_improvement_cycle", {"run": self.run_id, **result})
            results.append(result)
            current = result["selected_for_next_cycle"]
        return {"kind": "solver-rsi", "cycles": results, "selected_development_policy": current, "active_policy": self.store.active()}

    def audit_solver(self, audit, suite, candidate_id, promote=False):
        require(self.backend.mode == "live", "scripted evaluations cannot consume audit sets or promote policies")
        candidate_policy = self.store.get(candidate_id, "policy")
        baseline_id = self.store.active()
        require(candidate_id != baseline_id, "audit candidate equals active baseline")
        baseline_policy = self.store.get(baseline_id, "policy")
        # The candidate must be the active policy with only solver text changed:
        # a solver audit cannot also move the verifier it is judged by.
        require_arm_change("solver", baseline_policy, candidate_policy)
        validate_solver_audit(audit, self.exposures(suite))
        require(self.config["max_calls"] >= 10 * len(audit["tasks"]), "solver audit call budget is too small; budget ten calls per paired problem")
        self.store.reserve_audit(audit, self.run_id)
        baseline, candidate = [], []
        for index, task in enumerate(audit["tasks"]):
            order = [(baseline_policy, baseline, "baseline"), (candidate_policy, candidate, "candidate")]
            if index % 2:
                order.reverse()
            for policy, target, label in order:
                target.append(self.solve(f"solver-audit/{index}/{label}", task, policy))
        gate = solver_gate(baseline, candidate)
        value = {"arm": "solver", "mode": "live", "protocol": SOLVER_PROTOCOL, "code_hash": code_hash(),
                 "baseline": baseline_id, "candidate": candidate_id, "audit_digest": digest(audit), "regression_suite": digest(suite),
                 "baseline_rows": baseline, "candidate_rows": candidate, "gate": gate}
        evaluation = self.store.record_evaluation(self.run_id, value)
        if promote and gate["eligible"]:
            self.store.promote(evaluation, code_hash(), digest(suite))
        return {"kind": "audit", "evaluation_id": evaluation, "promoted": promote and gate["eligible"], **value}

    def mine(self, papers, batches=1, batch_size=6, prefix="mine"):
        """Turn recent Valency records into quarantined benchmark drafts with paper provenance."""
        require(bool(papers), "no eligible Valency records; import recent math/physics records or use an earlier --since")
        require(1 <= batches <= 20 and 1 <= batch_size <= 8, "mining needs 1..20 batches of 1..8 papers")
        drafts, rejected = [], []
        for index in range(min(batches, math.ceil(len(papers) / batch_size))):
            batch = papers[index * batch_size:(index + 1) * batch_size]
            domains = {p["source"] + ":" + p["id"]: sorted(paper_domains(p)) for p in batch}
            result = self.data(self.call(f"{prefix}/{index}", "miner", agents.prompt_for("miner", {"papers": batch}),
                                         agents.MINER_SCHEMA, {"papers": batch, "domains": domains}))
            for draft in result["drafts"]:
                if not set(draft["paper_ids"]) <= set(domains):
                    rejected.append({"title": draft["title"], "reason": "cites a record outside its batch"})
                elif not all(draft["domain"] in domains[c] for c in draft["paper_ids"]):
                    rejected.append({"title": draft["title"], "reason": "domain does not match the cited papers' categories"})
                else:
                    fields = {k: draft[k] for k in ("title", "domain", "family_id", "prompt", "reference", "rubric")}
                    task = validate_task(dict(fields, id=digest(fields)[:20]))
                    sources = [{k: p[k] for k in ("id", "source", "title", "url", "first_submitted") if k in p}
                               for p in batch if p["source"] + ":" + p["id"] in draft["paper_ids"]]
                    drafts.append(self.store.put("benchmark_draft", {"run": self.run_id, "origin": "valency-miner", "review_status": "unreviewed",
                                                                     "task": task, "source_papers": sources, "review_notes": draft["review_notes"]}))
        return {"kind": "mining", "papers": len(papers), "drafts": drafts, "rejected": rejected}
