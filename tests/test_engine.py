from contextlib import redirect_stdout
import copy
import io
from pathlib import Path
import tempfile
import unittest

from danus_rsi import agents
from danus_rsi.cli import main
from danus_rsi.engine import BASELINE, Engine, code_hash, initialize, load_suite
from danus_rsi.protocol import ProtocolError, digest
from danus_rsi.store import BudgetExceeded, Store
from test_protocol import fixture_audit, judgment, native


class FakeLiveAgents(agents.ScriptedAgents):
    """Mock the live interface to test promotion; never contact a model."""
    mode = "live"
    provenance = {"fixture": True}

    def generate(self, role, prompt, schema, context, directory, timeout):
        if role in ("correctness", "adversarial", "completeness"):
            correct = '"verifier_guidance":"CANDIDATE_TEST_POLICY"' in prompt and '"proof":"fixture valid"' in prompt
            return judgment("correct" if correct else "incorrect")["data"], {"fixture": True}
        return super().generate(role, prompt, schema, context, directory, timeout)

    def verify(self, solution, timeout):
        return native("correct" if solution["proof"] == "fixture valid" else "wrong")["data"], {"fixture": True}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        initialize(self.store)
        self.engine = Engine(self.store, agents.ScriptedAgents())

    def test_demo_dag_records_real_dependencies_and_dissent(self):
        run = self.engine.start("test", {"objective": "fixture"})
        result = self.engine.research("fixture objective", "theoretical-physics", self.store.active())
        self.assertEqual(len(result["findings"]), 2)
        self.assertTrue(all(f["status"] == "unresolved" for f in result["findings"]))
        self.assertEqual(self.store.run(run)["calls"], 16)
        calls = self.store.run(run)["calls"]
        self.engine.research("fixture objective", "theoretical-physics", self.store.active())
        self.assertEqual(self.store.run(run)["calls"], calls)

    def test_recursive_proposals_never_promote_or_self_certify_drafts(self):
        active = self.store.active()
        self.engine.start("improve", {})
        result = self.engine.improve(load_suite(), active, 2, 4)
        self.assertEqual(len(result["cycles"]), 2)
        self.assertEqual(self.store.active(), active)
        self.assertTrue(self.store.artifacts("benchmark_draft"))
        self.assertFalse(self.store.artifacts("reviewed_curriculum"))
        self.assertTrue(all(not c["production_promoted"] for c in result["cycles"]))

    def test_budget_exhaustion_stops_campaign(self):
        engine = Engine(self.store, agents.ScriptedAgents(), {"max_calls": 1})
        run = engine.start("bounded", {})
        with self.assertRaises(BudgetExceeded):
            engine.research("fixture", "mathematics", self.store.active())
        self.assertEqual(self.store.run(run)["calls"], 1)

    def test_scripted_audit_is_blocked_before_reservation(self):
        self.engine.start("audit", {})
        with self.assertRaisesRegex(ProtocolError, "scripted"):
            self.engine.audit(fixture_audit(), load_suite(), self.store.active())

    def test_audit_pairing_regression_promotion_and_rollback(self):
        engine = Engine(self.store, FakeLiveAgents(), {"max_calls": 512})
        baseline = self.store.active()
        candidate = self.store.put("policy", dict(BASELINE, verifier_guidance="CANDIDATE_TEST_POLICY"))
        suite = copy.deepcopy(load_suite())
        suite["tasks"] = [t for t in suite["tasks"] if t["calibration"]][:2]
        for task in suite["tasks"]:
            for c in task["calibration"]:
                c["solution"] = {"answer": "fixture", "claim": "fixture", "proof": "fixture " + c["label"]}
        engine.start("audit-test", {"candidate": candidate})
        result = engine.audit(fixture_audit(), suite, candidate, promote=True)
        self.assertTrue(result["gate"]["eligible"])
        self.assertTrue(result["promoted"])
        self.assertEqual(self.store.active(), candidate)
        # The same evaluation cannot overwrite a subsequent active policy.
        with self.assertRaisesRegex(ProtocolError, "active policy changed"):
            self.store.promote(result["evaluation_id"], code_hash(), digest(suite))
        self.store.rollback(baseline)
        self.assertEqual(self.store.active(), baseline)
        with self.assertRaisesRegex(ProtocolError, "code changed"):
            self.store.promote(result["evaluation_id"], "different-code")

    def test_malformed_judge_is_error_not_math_failure(self):
        class Broken(agents.ScriptedAgents):
            def generate(self, *args):
                return {"verdict": "correct"}, {}
        engine = Engine(self.store, Broken())
        engine.start("broken", {})
        result = engine.panel("panel", load_suite()["tasks"][0], {"claim": "x", "proof": "y", "answer": "z"}, BASELINE)
        self.assertEqual(result["decision"], "error")
        self.assertFalse(result["aggregate"]["strict_pass"])

    def test_cli_demo_and_html_escape(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["demo", "--state", self.tmp.name, "--cycles", "1", "--limit", "2"]), 0)
        import json
        report = json.loads(output.getvalue())
        content = Path(report["report"]).read_text(encoding="utf-8")
        self.assertIn("SCRIPTED DEMONSTRATION", content)
        from danus_rsi.report import write_report
        rows = [{"task_id": "<script>alert(1)</script>", "domain": "math", "decision": "error"}]
        files = write_report(self.store, report["run_id"], {"kind": "benchmark", "rows": rows})
        self.assertNotIn("<script>", Path(files["report"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
