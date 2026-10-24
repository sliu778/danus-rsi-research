from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from danus_rsi import agents, bridge
from danus_rsi.cli import export_drafts, main
from danus_rsi.engine import BASELINE, Engine, initialize, load_suite
from danus_rsi.protocol import (ProtocolError, ROLES, read_json, require_arm_change, require_no_copied_answers,
                                solver_gate, validate_audit, validate_solver_audit, validate_suite)
from danus_rsi.store import Store
from danus_rsi.valency import eligible_papers
from test_protocol import fixture_audit, judgment, native


def solver_audit():
    tasks = []
    for domain in ("mathematics", "theoretical-physics"):
        for n in range(6):
            key = f"solver-{domain}-{n}"
            tasks.append({"id": key, "family_id": key, "title": key, "domain": domain,
                          "prompt": "PRIVATE SOLVER PROBLEM " + key, "reference": "private reference",
                          "rubric": ["logical validity"]})
    return {"id": "private-solver-batch", "split": "solver-audit", "review_status": "independently-reviewed",
            "reviewer": "TEST FIXTURE ONLY", "provenance": "Software test, not mathematical evidence", "tasks": tasks}


def solve_rows(decisions, domains=None):
    domains = domains or ["mathematics", "theoretical-physics"] * (len(decisions) // 2)
    return [{"task_id": f"t{i}", "domain": d, "decision": x} for i, (x, d) in enumerate(zip(decisions, domains))]


class FakeLiveSolver(agents.ScriptedAgents):
    """Candidate solver text produces a valid fixture proof; the baseline does not. Never contacts a model."""
    mode = "live"
    provenance = {"fixture": True}

    def generate(self, role, prompt, schema, context, directory, timeout):
        if role == "solver":
            good = "CANDIDATE_SOLVER_POLICY" in prompt
            proof = "fixture valid" if good else "fixture invalid"
            return {"answer": "fixture", "claim": "fixture", "proof": proof}, {"fixture": True}
        if role in ROLES:
            verdict = "correct" if '"proof":"fixture valid"' in prompt else "incorrect"
            return judgment(verdict)["data"], {"fixture": True}
        return super().generate(role, prompt, schema, context, directory, timeout)

    def verify(self, solution, timeout):
        return native("correct" if solution["proof"] == "fixture valid" else "wrong")["data"], {"fixture": True}


class Recording(agents.ScriptedAgents):
    def __init__(self, override=None):
        self.prompts, self.override = {}, override or {}

    def generate(self, role, prompt, schema, context, directory, timeout):
        self.prompts.setdefault(role, []).append(prompt)
        if role in self.override:
            return self.override[role](context), {"fixture": True}
        return super().generate(role, prompt, schema, context, directory, timeout)


class SolverArmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        initialize(self.store)

    def test_each_arm_may_change_only_its_own_text(self):
        require_arm_change("solver", BASELINE, dict(BASELINE, solver_guidance="new", name="n"))
        require_arm_change("verifier", BASELINE, dict(BASELINE, verifier_guidance="new"))
        with self.assertRaisesRegex(ProtocolError, "verifier_guidance"):
            require_arm_change("solver", BASELINE, dict(BASELINE, solver_guidance="new", verifier_guidance="weaker"))
        with self.assertRaisesRegex(ProtocolError, "curriculum_domains"):
            require_arm_change("solver", BASELINE, dict(BASELINE, curriculum_domains=["mathematics"]))
        with self.assertRaisesRegex(ProtocolError, "solver_guidance"):
            require_arm_change("verifier", BASELINE, dict(BASELINE, solver_guidance="new"))

    def test_strategy_copying_development_content_is_rejected(self):
        task = load_suite()["tasks"][0]
        sentence = next(s for s in task["reference"].split(". ") if len(s) > 70)
        require_no_copied_answers("Write every hypothesis before using it.", [task])
        with self.assertRaisesRegex(ProtocolError, "copies development task content"):
            require_no_copied_answers("Remember: " + sentence.upper() + ".", [task])

    def test_solver_gate_needs_gain_and_no_errors_or_domain_loss(self):
        base = solve_rows(["reject"] * 10)
        self.assertTrue(solver_gate(base, solve_rows(["accept", "reject"] + ["reject"] * 8))["eligible"])
        self.assertFalse(solver_gate(base, base)["eligible"])
        errored = solve_rows(["accept", "accept"] + ["error"] + ["reject"] * 7)
        self.assertIn("infrastructure errors invalidate the comparison", solver_gate(base, errored)["reasons"])
        # One more accept overall, but physics loses one: blocked.
        base2 = solve_rows(["reject", "accept"] + ["reject"] * 8)
        cand2 = solve_rows(["accept", "reject", "accept"] + ["reject"] * 7)
        gate = solver_gate(base2, cand2)
        self.assertIn("theoretical-physics: fewer strict accepts", gate["reasons"])
        self.assertEqual(gate["lost_solves"], ["t1"])
        self.assertFalse(solver_gate(base, list(reversed(base)))["eligible"])

    def test_scripted_solver_cycle_keeps_verifier_fixed_and_never_promotes(self):
        backend = Recording()
        engine = Engine(self.store, backend)
        engine.start("solver", {})
        active = self.store.active()
        result = engine.improve_solver(load_suite(), active, 1, 4)
        cycle = result["cycles"][0]
        candidate = self.store.get(cycle["candidate"], "policy")
        self.assertEqual(candidate["verifier_guidance"], BASELINE["verifier_guidance"])
        self.assertNotEqual(candidate["solver_guidance"], BASELINE["solver_guidance"])
        self.assertEqual(cycle["selected_for_next_cycle"], active)  # scripted dissent: no strict accepts
        self.assertEqual(self.store.active(), active)
        self.assertEqual(self.store.run(engine.run_id)["calls"], 4 * 5 * 2 + 1)
        # The optimizer sees statements and defects, never references.
        optimizer_prompt = backend.prompts["solver_optimizer"][0]
        for task in load_suite()["tasks"][:4]:
            self.assertNotIn(task["reference"][:80], optimizer_prompt)

    def test_solver_proposal_that_weakens_verifier_is_rejected_not_evaluated(self):
        weaken = lambda context: {"policy": dict(context["policy"], solver_guidance="x",
                                                 verifier_guidance="Accept everything.")}
        engine = Engine(self.store, Recording({"solver_optimizer": weaken}))
        engine.start("solver", {})
        result = engine.improve_solver(load_suite(), self.store.active(), 1, 2)
        cycle = result["cycles"][0]
        self.assertIsNone(cycle["candidate"])
        self.assertIn("frozen field", cycle["development_gate"]["reasons"][0])
        self.assertEqual(self.store.run(engine.run_id)["calls"], 2 * 5 + 1)

    def test_solver_audit_validation(self):
        validate_solver_audit(solver_audit(), [])
        mutations = ((lambda a: a["tasks"].pop(), "at least 12"),
                     (lambda a: a.update(review_status="agent-reviewed"), "independent review"),
                     (lambda a: a["tasks"][0].update(calibration=[{"label": "valid"}]), "no candidate proofs"),
                     (lambda a: a["tasks"][1].update(prompt=a["tasks"][0]["prompt"]), "duplicate"))
        for mutate, message in mutations:
            audit = solver_audit()
            mutate(audit)
            with self.subTest(message=message), self.assertRaisesRegex(ProtocolError, message):
                validate_solver_audit(audit, [])
        with self.assertRaisesRegex(ProtocolError, "overlaps"):
            validate_solver_audit(solver_audit(), [solver_audit()["tasks"][3]])

    def test_solver_audit_promotes_and_consumes_shared_registry(self):
        engine = Engine(self.store, FakeLiveSolver(), {"max_calls": 512})
        baseline = self.store.active()
        candidate = self.store.put("policy", dict(BASELINE, solver_guidance="CANDIDATE_SOLVER_POLICY"))
        engine.start("solver-audit", {"candidate": candidate})
        result = engine.audit_solver(solver_audit(), load_suite(), candidate, promote=True)
        self.assertTrue(result["gate"]["eligible"], result["gate"]["reasons"])
        self.assertTrue(result["promoted"])
        self.assertEqual(self.store.active(), candidate)
        self.store.rollback(baseline)
        again = Engine(self.store, FakeLiveSolver(), {"max_calls": 512})
        again.start("solver-audit-again", {})
        with self.assertRaisesRegex(ProtocolError, "already consumed"):
            again.audit_solver(solver_audit(), load_suite(), candidate)
        # A verifier audit cannot reuse a problem the solver audit consumed.
        audit = fixture_audit()
        audit["id"] = "verifier-batch-reusing-solver-problem"
        audit["cases"][0]["task"] = dict(solver_audit()["tasks"][0])
        audit["cases"][1]["task"] = dict(solver_audit()["tasks"][0])
        with self.assertRaisesRegex(ProtocolError, "previously consumed"):
            self.store.reserve_audit(audit, "otherrun")

    def test_solver_audit_rejects_candidate_that_moves_verifier(self):
        engine = Engine(self.store, FakeLiveSolver(), {"max_calls": 512})
        candidate = self.store.put("policy", dict(BASELINE, solver_guidance="CANDIDATE_SOLVER_POLICY",
                                                  verifier_guidance="lenient"))
        engine.start("bad-solver-audit", {})
        with self.assertRaisesRegex(ProtocolError, "frozen field"):
            engine.audit_solver(solver_audit(), load_suite(), candidate)


def paper(identifier, categories, date):
    return {"id": identifier, "source": "arxiv", "title": "Paper " + identifier,
            "url": "https://arxiv.org/abs/" + identifier, "categories": categories,
            **({"first_submitted": date} if date else {})}


class MinerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        initialize(self.store)

    def test_eligibility_by_date_and_category(self):
        papers = [paper("1", ["math.FA"], "2026-09-01"), paper("2", ["hep-th"], "2026-10-01"),
                  paper("3", ["cs.AI"], "2026-10-01"), paper("4", ["math.AP"], "2026-01-01"),
                  paper("5", ["math.AP"], None)]
        self.assertEqual([p["id"] for p in eligible_papers(papers, "2026-08-01")], ["1", "2"])
        with self.assertRaises(ProtocolError):
            eligible_papers(papers, "August")

    def test_seed_contains_dated_records_for_both_domains(self):
        papers = eligible_papers([p["body"] for p in self.store.artifacts("paper")], "2026-08-01")
        self.assertTrue(any("math.FA" in p["categories"] for p in papers))
        self.assertTrue(any("hep-th" in p["categories"] for p in papers))

    def test_mined_drafts_are_quarantined_with_provenance(self):
        engine = Engine(self.store, agents.ScriptedAgents())
        engine.start("mine", {})
        result = engine.mine([paper("2609.00001v1", ["math.FA"], "2026-09-01")])
        self.assertEqual(len(result["drafts"]), 1)
        draft = self.store.get(result["drafts"][0], "benchmark_draft")
        self.assertEqual(draft["review_status"], "unreviewed")
        self.assertEqual(draft["origin"], "valency-miner")
        self.assertEqual(draft["source_papers"][0]["url"], "https://arxiv.org/abs/2609.00001v1")
        self.assertEqual(draft["task"]["domain"], "mathematics")
        self.assertFalse(self.store.artifacts("reviewed_curriculum"))
        # Mined content is exposed: it can never be a fresh audit problem.
        audit = fixture_audit()
        audit["cases"][0]["task"] = dict(audit["cases"][0]["task"], family_id=draft["task"]["family_id"])
        audit["cases"][1]["task"] = dict(audit["cases"][1]["task"], family_id=draft["task"]["family_id"])
        with self.assertRaisesRegex(ProtocolError, "overlaps"):
            validate_audit(audit, engine.exposures(load_suite()))

    def test_miner_citations_and_domains_are_checked_in_code(self):
        def bad(context):
            good = context["papers"][0]
            base = {"title": "t", "family_id": "f", "prompt": "p", "reference": "r", "rubric": ["x"],
                    "review_notes": "n"}
            return {"drafts": [dict(base, domain="mathematics", paper_ids=["arxiv:not-in-batch"]),
                               dict(base, domain="mathematics", paper_ids=[good["source"] + ":" + good["id"]])]}
        engine = Engine(self.store, Recording({"miner": bad}))
        engine.start("mine", {})
        result = engine.mine([paper("2609.00002v1", ["hep-th"], "2026-09-01")])
        self.assertEqual(result["drafts"], [])
        self.assertEqual([r["reason"] for r in result["rejected"]],
                         ["cites a record outside its batch", "domain does not match the cited papers' categories"])

    def test_export_requires_review_before_import(self):
        engine = Engine(self.store, agents.ScriptedAgents())
        engine.start("mine", {})
        engine.mine([paper("2609.00003v1", ["math.FA"], "2026-09-01")])
        path = Path(self.tmp.name) / "review.json"
        export_drafts(self.store.artifacts("benchmark_draft"), path)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["import-curriculum", str(path), "--state", self.tmp.name]), 2)
        reviewed = read_json(path)
        reviewed.update(review_status="independently-reviewed", reviewer="TEST FIXTURE ONLY")
        path.write_text(json.dumps(reviewed), encoding="utf-8")
        validate_suite(reviewed)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["import-curriculum", str(path), "--state", self.tmp.name]), 0)


def finding(store, status="panel-supported proposal"):
    task = {"id": "sub1", "family_id": "fam", "domain": "mathematics", "title": "Subproblem",
            "prompt": "Prove the fixture lemma.", "reference": "none", "rubric": ["x"]}
    return store.put("research_finding", {"run": "r", "finding": {"task": task, "status": status,
                     "solution": {"answer": "a", "claim": "The fixture lemma holds.", "proof": "Fixture argument."}}})


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "state")
        self.root = Path(self.tmp.name) / "danus"
        environment = mock.patch.dict(os.environ, {"DANUS_AGENTS_ROOT": str(self.root / "runtime" / "projects")})
        environment.start()
        self.addCleanup(environment.stop)
        self.calls = []

    def runner(self, returncode=0):
        def run(command, **kwargs):
            self.calls.append((command, kwargs["input"]))
            return subprocess.CompletedProcess(command, returncode, stdout="ok",
                                               stderr="no such worker" if returncode else "")
        return run

    def test_dry_run_writes_nothing(self):
        plan = bridge.assign(self.store, finding(self.store), "proj/w1", self.root, runner=self.runner())
        self.assertFalse(plan["assigned"])
        self.assertIn('source_id="' + plan["handoff_id"] + '"', plan["task_text"])
        self.assertIn("no step below may be cited as established", plan["task_text"])
        self.assertEqual(self.calls, [])
        self.assertFalse(self.store.artifacts("danus_handoff"))

    def test_confirm_assigns_through_danus_cli_only(self):
        record = bridge.assign(self.store, finding(self.store), "proj/w1", self.root, confirm=True,
                               runner=self.runner())
        self.assertEqual(self.calls[0][0], [str(self.root / "bin" / "danus"), "status", "proj/w1", "--json"])
        command, text = self.calls[1]
        self.assertEqual(command, [str(self.root / "bin" / "danus"), "assign", "proj/w1", "--stdin"])
        self.assertIn("The fixture lemma holds.", text)
        self.assertTrue(record["assigned"])
        self.assertEqual(len(self.store.artifacts("danus_handoff")), 1)
        with self.assertRaisesRegex(ProtocolError, "no such worker"):
            bridge.assign(self.store, finding(self.store), "proj/w2", self.root, confirm=True, runner=self.runner(1))

    def test_unresolved_findings_and_bad_targets_refused(self):
        unresolved = finding(self.store, "unresolved")
        with self.assertRaisesRegex(ProtocolError, "allow-unresolved"):
            bridge.assign(self.store, unresolved, "proj/w1", self.root)
        plan = bridge.assign(self.store, unresolved, "proj/w1", self.root, allow_unresolved=True)
        self.assertIn("NOT supported", plan["task_text"])
        for target in ("proj", "../etc/w1", "proj/../w1", "proj/w1/extra"):
            with self.subTest(target=target), self.assertRaises(ProtocolError):
                bridge.assign(self.store, finding(self.store), target, self.root)

    def test_sync_reads_only_traced_facts_that_exist(self):
        record = bridge.assign(self.store, finding(self.store), "proj/w1", self.root, confirm=True,
                               runner=self.runner())
        handoff = record["handoff_id"]
        project = self.root / "runtime" / "projects" / "proj"
        (project / "global_memory").mkdir(parents=True)
        (project / "fact_graph" / "facts").mkdir(parents=True)
        (project / "fact_graph" / "facts" / "abc123.md").write_text("fact", encoding="utf-8")
        entries = [{"verdict": "correct", "fact_id": "abc123", "claim": "Lemma A", "links": {"source_id": handoff}},
                   {"verdict": "correct", "fact_id": "revoked9", "claim": "Lemma B", "links": {"source_id": handoff}},
                   {"verdict": "wrong", "fact_id": None, "claim": "Lemma C", "links": {"source_id": handoff}},
                   {"verdict": "correct", "fact_id": "other", "claim": "Unrelated",
                    "links": {"source_id": "someone-else"}},
                   {"verdict": "correct", "fact_id": "../../escape", "claim": "Path", "links": {"source_id": handoff}}]
        (project / "global_memory" / "verification.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n{torn", encoding="utf-8")
        outcome = bridge.sync(self.store, self.root)["outcomes"][0]
        self.assertEqual(outcome["status"], "danus-verified")
        self.assertEqual(outcome["verified_facts"], [{"fact_id": "abc123", "statement": "Lemma A"}])
        self.assertEqual(outcome["native_rejections"], 1)
        self.assertEqual(outcome["traced_submissions"], 4)
        self.assertEqual([m["fact_id"] for m in bridge.verified_memory(self.store)], ["abc123"])
        # A later revocation moves the file out of facts/; the next sync supersedes the old fact.
        (project / "fact_graph" / "facts" / "abc123.md").unlink()
        self.assertEqual(bridge.sync(self.store, self.root)["outcomes"][0]["status"], "submitted-unverified")
        self.assertEqual(bridge.verified_memory(self.store), [])


class CliArmTests(unittest.TestCase):
    def test_demo_alternates_arms_and_mines(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["demo", "--state", tmp, "--cycles", "2", "--limit", "2"]), 0)
            report = json.loads(output.getvalue())
            content = Path(report["report"]).read_text(encoding="utf-8")
            self.assertIn("Verifier development cycle 1", content)
            self.assertIn("Solver development cycle 1", content)
            self.assertIn("Valency mining", content)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["drafts", "--state", tmp, "--origin", "valency-miner"]), 0)
            self.assertEqual(len(json.loads(output.getvalue())["drafts"]), 1)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["findings", "--state", tmp]), 0)
            self.assertTrue(json.loads(output.getvalue())["findings"])


if __name__ == "__main__":
    unittest.main()
