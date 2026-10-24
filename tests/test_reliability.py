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
from danus_rsi.cli import main
from danus_rsi.engine import REDACTED, Engine, initialize, load_suite, solver_feedback
from danus_rsi.protocol import ProtocolError, solve_metrics, solver_gate, wilson
from danus_rsi.store import Store
from test_arms import finding, paper


def sampled(decision_lists, domains=None):
    domains = domains or ["mathematics", "theoretical-physics"] * (len(decision_lists) // 2)
    return [{"task_id": f"t{i}", "domain": d, "samples": len(ds), "attempts": [{"decision": x} for x in ds]}
            for i, (ds, d) in enumerate(zip(decision_lists, domains))]


class IntervalTests(unittest.TestCase):
    def test_wilson_interval(self):
        self.assertIsNone(wilson(0, 0))
        low, high = wilson(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)
        self.assertEqual(wilson(10, 10)[1], 1.0)
        self.assertEqual(wilson(0, 10)[0], 0.0)
        # Wider with fewer trials: the reason one sample per problem is weak evidence.
        self.assertGreater(wilson(1, 2)[1] - wilson(1, 2)[0], wilson(10, 20)[1] - wilson(10, 20)[0])


class SamplingGateTests(unittest.TestCase):
    def test_single_attempt_rows_keep_the_v1_rule(self):
        rows = [{"task_id": "a", "domain": "mathematics", "decision": "accept"},
                {"task_id": "b", "domain": "theoretical-physics", "decision": "reject"}]
        metrics = solve_metrics(rows)
        self.assertEqual((metrics["n"], metrics["attempts"], metrics["accepted"]), (2, 2, 1))

    def test_gain_threshold_scales_with_attempts(self):
        base = sampled([["reject"] * 3] * 4)  # 4 problems x 3 attempts = 12 attempts
        one_more = sampled([["accept", "reject", "reject"]] + [["reject"] * 3] * 3)
        two_more = sampled([["accept", "accept", "reject"]] + [["reject"] * 3] * 3)
        gate = solver_gate(base, one_more)
        self.assertIn("strict-accept gain is below 2 attempt(s)", gate["reasons"])
        self.assertTrue(solver_gate(base, two_more)["eligible"])
        self.assertEqual(solver_gate(base, two_more)["candidate"]["attempts"], 12)

    def test_unequal_attempts_and_partial_losses(self):
        base = sampled([["accept", "accept"], ["reject", "reject"]])
        self.assertIn("unequal attempts per problem", solver_gate(base, sampled([["accept"], ["reject"]]))["reasons"])
        candidate = sampled([["accept", "reject"], ["accept", "accept"]])
        gate = solver_gate(base, candidate)
        self.assertEqual(gate["lost_solves"], ["t0"])
        self.assertIn("mathematics: fewer strict accepts", gate["reasons"])


class EngineSamplingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        initialize(self.store)

    def test_samples_multiply_attempts_and_calls(self):
        engine = Engine(self.store, agents.ScriptedAgents())
        engine.start("sampled", {})
        result = engine.improve_solver(load_suite(), self.store.active(), 1, 2, samples=3)
        cycle = result["cycles"][0]
        self.assertEqual([r["samples"] for r in cycle["baseline_rows"]], [3, 3])
        self.assertEqual(cycle["development_gate"]["baseline"]["attempts"], 6)
        self.assertEqual(self.store.run(engine.run_id)["calls"], 2 * 2 * 3 * 5 + 1)
        with self.assertRaisesRegex(ProtocolError, "samples must be 1..5"):
            engine.solve_set("x", load_suite()["tasks"][0], self.store.get(self.store.active()), 6)

    def test_feedback_withholds_defects_quoting_the_reference(self):
        task = load_suite()["tasks"][0]
        quoted = "The panel notes: " + " ".join(task["reference"].split()[:12])
        judgment = {"status": "ok",
                    "data": {"critical_errors": [quoted], "gaps": ["The bound in step 2 is not justified."]}}
        attempt = {"decision": "reject", "solution": {"status": "ok", "data": {"claim": "c"}},
                   "panel": {"judgments": {"correctness": judgment, "adversarial": judgment},
                             "native": {"status": "error"}}}
        feedback = solver_feedback(task, {"task_id": task["id"], "domain": task["domain"],
                                          "attempts": [attempt, attempt]})
        self.assertEqual(feedback["defects"], [REDACTED, "The bound in step 2 is not justified."])
        self.assertEqual(feedback["withheld_defects"], 4)
        self.assertEqual(feedback["decisions"], ["reject", "reject"])
        self.assertNotIn(task["reference"][:60], json.dumps(feedback))

    def test_mining_rejects_known_problems(self):
        engine = Engine(self.store, agents.ScriptedAgents())
        engine.start("mine-twice", {})
        record = paper("2609.00004v1", ["math.FA"], "2026-09-01")
        first = engine.mine([record], exposed=engine.exposures(load_suite()))
        self.assertEqual(len(first["drafts"]), 1)
        second = engine.mine([record], prefix="again", exposed=engine.exposures(load_suite()))
        self.assertEqual(second["drafts"], [])
        self.assertEqual(second["rejected"][0]["reason"], "duplicates a known problem family or statement")


class BridgePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "state")
        self.root = Path(self.tmp.name) / "danus"
        environment = mock.patch.dict(os.environ, {"DANUS_AGENTS_ROOT": str(self.root / "runtime" / "projects")})
        environment.start()
        self.addCleanup(environment.stop)

    def test_failed_status_blocks_assignment(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command[1])
            failed = command[1] == "status"
            return subprocess.CompletedProcess(command, 1 if failed else 0, stdout="",
                                               stderr="no such worker" if failed else "")
        with self.assertRaisesRegex(ProtocolError, "not found or not readable"):
            bridge.assign(self.store, finding(self.store), "proj/ghost", self.root, confirm=True, runner=runner)
        self.assertEqual(calls, ["status"])
        self.assertFalse(self.store.artifacts("danus_handoff"))

    def test_sync_reports_missing_project(self):
        ok = lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")
        bridge.assign(self.store, finding(self.store), "gone/w1", self.root, confirm=True, runner=ok)
        self.assertEqual(bridge.sync(self.store, self.root)["outcomes"][0]["status"], "project-missing")


class CliSamplingTests(unittest.TestCase):
    def test_verifier_samples_rejected_before_any_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["improve", "--state", tmp, "--samples", "2"]), 2)
                self.assertEqual(main(["improve", "--state", tmp, "--arm", "solver", "--samples", "9"]), 2)
            self.assertEqual(Store(tmp).runs(), [])

    def test_report_shows_the_evidence_behind_each_cycle(self):
        for limit, verifier_text in (("4", "balanced accuracy 0.00 → 0.00"), ("2", "balanced accuracy n/a")):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as tmp:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["demo", "--state", tmp, "--cycles", "2", "--limit", limit]), 0)
                content = Path(json.loads(output.getvalue())["report"]).read_text(encoding="utf-8")
                self.assertIn(verifier_text, content)
                self.assertIn("strict accepts 0/" + limit, content)
        # Two attempts of zero successes still leave most of [0, 1] plausible.
        self.assertEqual(wilson(0, 2), [0.0, 0.6576])


if __name__ == "__main__":
    unittest.main()
