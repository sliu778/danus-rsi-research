import io
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from contextlib import redirect_stdout

from danus_rsi import agents
from danus_rsi.cli import audit_check, main
from danus_rsi.doctor import diagnose
from danus_rsi.engine import DEFAULT_CONFIG, Engine, initialize, load_suite
from danus_rsi.protocol import ProtocolError, validate_solver_audit
from danus_rsi.store import Store
from test_arms import solver_audit
from test_protocol import fixture_audit


def run_cli(*argv):
    output = io.StringIO()
    with redirect_stdout(output):
        code = main(list(argv))
    return code, (json.loads(output.getvalue()) if code == 0 else None)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        (base / "danus" / "scripts").mkdir(parents=True)
        (base / "danus" / "scripts" / "env.sh").write_text("", encoding="utf-8")
        (base / "danus" / "runtime" / "run").mkdir(parents=True)
        (base / "danus" / "runtime" / "run" / "verify.pid").write_text("4242\n", encoding="utf-8")
        self.env = {"DANUS_ROOT": str(base / "danus"), "DANUS_RUNTIME": str(base / "danus" / "runtime"),
                    "CODEX_BACKEND": "chatgpt", "OPENAI_API_KEY": "sk-should-never-reach-codex"}
        self.state = base / "state"
        self.login_envs = []
        codex = types.SimpleNamespace(resolve_bin=lambda: "/fake/codex", subprocess_env=lambda binary: dict(self.env))
        self.kwargs = {"env": self.env, "platform": "linux", "importer": lambda: codex,
                       "runner": self.runner("Logged in using ChatGPT"), "fetch": lambda url: {"status": "ok", "pid": 4242}}

    def runner(self, text):
        def run(command, **kwargs):
            self.login_envs.append(kwargs["env"])
            return subprocess.CompletedProcess(command, 0, stdout=text, stderr="")
        return run

    def result(self, **overrides):
        report = diagnose(DEFAULT_CONFIG, self.state, **(self.kwargs | overrides))
        return report, {c["check"]: c for c in report["checks"]}

    def test_ready_when_every_required_check_passes(self):
        report, checks = self.result()
        self.assertTrue(report["ready"], [c for c in report["checks"] if not c["ok"]])
        self.assertFalse(checks["valency token"]["ok"])  # optional checks never block readiness
        self.assertNotIn("OPENAI_API_KEY", self.login_envs[0])
        self.assertNotIn("sk-should-never-reach-codex", json.dumps(report))

    def test_each_missing_prerequisite_is_reported_with_a_fix(self):
        cases = {
            "verifier": {"fetch": lambda url: {"status": "ok", "pid": 1}},
            "codex login": {"runner": self.runner("Logged in using an API key")},
            "platform": {"platform": "win32"},
            "subscription backend": {"env": dict(self.env, CODEX_BACKEND="api")},
        }
        for check, override in cases.items():
            with self.subTest(check=check):
                report, checks = self.result(**override)
                self.assertFalse(report["ready"])
                self.assertFalse(checks[check]["ok"])
                self.assertTrue(checks[check]["fix"])

    def test_unreachable_verifier_and_missing_package(self):
        def down(url):
            raise OSError("connection refused")
        def missing():
            raise ModuleNotFoundError("No module named 'danus'")
        report, checks = self.result(fetch=down, importer=missing)
        self.assertFalse(checks["verifier"]["ok"])
        self.assertFalse(checks["danus package"]["ok"])
        self.assertFalse(checks["codex login"]["ok"])
        self.assertFalse(report["ready"])


class EstimateTests(unittest.TestCase):
    def test_estimate_matches_engine_and_reserves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, estimate = run_cli("improve", "--state", tmp, "--limit", "4", "--cycles", "1", "--estimate")
            self.assertEqual(code, 0)
            self.assertEqual(Store(tmp).runs(), [])
            store = Store(tmp)
            engine = Engine(store, agents.ScriptedAgents())
            engine.start("compare", {})
            engine.improve(load_suite(), store.active(), 1, 4)
            self.assertEqual(store.run(engine.run_id)["calls"], estimate["upper_bound_calls"])
            code, solver = run_cli("improve", "--state", tmp, "--arm", "solver", "--limit", "6", "--samples", "3",
                                   "--cycles", "2", "--max-calls", "300", "--estimate")
            self.assertEqual((solver["upper_bound_calls"], solver["fits"]), (362, False))

    def test_campaign_and_mining_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, campaign = run_cli("run", "--state", tmp, "--objective", "x", "--cycles", "2", "--arm", "alternate",
                                  "--limit", "6", "--estimate")
            self.assertEqual([b["calls"] for b in campaign["breakdown"]], [23, 49, 23, 61])
            _, mining = run_cli("mine", "--state", tmp, "--since", "2026-08-01", "--batches", "5", "--batch-size", "3", "--estimate")
            self.assertEqual(mining["upper_bound_calls"], 3)  # eight dated seed records in batches of three
            _, query = run_cli("mine", "--state", tmp, "--since", "2099-01-01", "--query", "q", "--batches", "4", "--estimate")
            self.assertEqual(query["upper_bound_calls"], 4)
            self.assertEqual(Store(tmp).runs(), [])


class AuditToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.store = Store(self.base / "state")
        initialize(self.store)

    def test_template_is_unusable_until_reviewed_and_stays_out_of_the_repository(self):
        code, made = run_cli("audit-template", "--state", str(self.base / "state"), "--arm", "solver",
                             "--out", str(self.base / "audit.json"))
        self.assertEqual(code, 0)
        with self.assertRaisesRegex(ProtocolError, "independent review"):
            validate_solver_audit(json.loads(Path(made["template"]).read_text(encoding="utf-8")), [])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["audit-template", "--arm", "solver", "--out", str(self.base / "audit.json"),
                                   "--state", str(self.base / "state")]), 2)  # no overwrite
            inside = Path(__file__).resolve().parents[1] / "docs" / "private-audit.json"
            self.assertEqual(main(["audit-template", "--arm", "verifier", "--out", str(inside),
                                   "--state", str(self.base / "state")]), 2)
            self.assertFalse(inside.exists())

    def test_check_reports_validity_freshness_and_no_content(self):
        path = self.base / "verifier-audit.json"
        path.write_text(json.dumps(fixture_audit()), encoding="utf-8")
        result = audit_check(self.store, load_suite(), path)
        self.assertTrue(result["valid"] and result["fresh"])
        self.assertEqual(result["counts"]["mathematics/valid"], 5)
        self.assertEqual(result["calls"], 8 * (20 + 18))
        self.assertNotIn("PRIVATE PROBLEM", json.dumps(result))
        self.assertFalse(self.store.audit_status(fixture_audit())["batch_consumed"])  # checking consumed nothing
        self.store.reserve_audit(fixture_audit(), "somerun")
        consumed = audit_check(self.store, load_suite(), path)
        self.assertTrue(consumed["batch_consumed"])
        self.assertFalse(consumed["fresh"])

    def test_check_solver_batch_and_malformed_input(self):
        path = self.base / "solver-audit.json"
        path.write_text(json.dumps(solver_audit()), encoding="utf-8")
        result = audit_check(self.store, load_suite(), path)
        self.assertTrue(result["fresh"])
        self.assertEqual((result["entries"], result["calls_per_sample"]), (12, 120))
        broken = solver_audit()
        del broken["tasks"][0]["prompt"]
        path.write_text(json.dumps(broken), encoding="utf-8")
        result = audit_check(self.store, load_suite(), path)
        self.assertFalse(result["valid"])
        self.assertFalse(result["fresh"])


if __name__ == "__main__":
    unittest.main()
