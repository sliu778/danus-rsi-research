from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from danus_rsi import transport
from test_protocol import native


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.backend = transport.LiveBackend()
        self.backend.binary = str(Path(__file__).parent / "fake_codex.py")
        self.backend.env = os.environ.copy()
        stub = types.ModuleType("danus")
        stub.codex = types.SimpleNamespace(
            exec_cmd=lambda binary, model, effort, *tail: [sys.executable, binary, "exec", "--model", model, *tail],
            resolve_bin=lambda: self.backend.binary,
            subprocess_env=lambda _: os.environ.copy())
        self.patch = patch.dict(sys.modules, {"danus": stub})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_command_restricts_tools_and_preserves_schema(self):
        args = transport.codex_command(self.backend.binary, "gpt-6-astra", "xhigh", Path("/tmp"), Path("/tmp/schema"),
                                       Path("/tmp/output"))
        for expected in ("read-only", "--ignore-user-config", "features.shell_tool=false", "features.apps=false",
                         "features.plugins=false", "--output-schema"):
            self.assertIn(expected, args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)

    def test_subscription_preflight_rejects_api_login_and_removes_keys(self):
        result = subprocess.CompletedProcess([], 0, "Logged in using an API key", "")
        with (patch.dict(os.environ, {"CODEX_BACKEND": "chatgpt", "OPENAI_API_KEY": "fixture-secret"}),
              patch("danus_rsi.transport.subprocess.run", return_value=result) as run):
            with self.assertRaises(transport.BenchError):
                self.backend.preflight({})
            self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "live subprocess transport is Linux/WSL only")
    def test_cli_success_and_invalid_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, usage = self.backend.generate("fixture", transport.SOLUTION_SCHEMA, "gpt-6-astra", "xhigh",
                                                Path(tmp), 5)
            self.assertEqual(data["answer"], "fixture")
            self.assertEqual(usage["input_tokens"], 10)
        for mode in ("malformed", "tool", "exit"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                self.backend.env["DANUS_TEST_MODE"] = mode
                with self.assertRaises((transport.BenchError, ValueError)):
                    self.backend.generate("fixture", transport.SOLUTION_SCHEMA, "gpt-6-astra", "xhigh", Path(tmp), 5)

    @unittest.skipUnless(sys.platform.startswith("linux"), "process-group timeout is Linux/WSL only")
    def test_cli_timeout_kills_process_group(self):
        self.backend.env["DANUS_TEST_MODE"] = "sleep"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.backend.generate("fixture", transport.SOLUTION_SCHEMA, "gpt-6-astra", "xhigh", Path(tmp), 0.1)

    def test_http_failure_rejection_and_inconsistent_response(self):
        class Handler(BaseHTTPRequestHandler):
            code, body, captured = 200, native()["data"], None
            def log_message(self, *args):
                pass
            def do_POST(self):
                type(self).captured = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(self.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(self.body).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        config = {"verify_url": f"http://127.0.0.1:{server.server_port}/verify", "verify_timeout_seconds": 3}
        solution = {"answer": "summary withheld", "claim": "claim", "proof": "proof"}
        try:
            self.assertEqual(self.backend.verify(solution, config)[0]["verdict"], "correct")
            self.assertEqual(Handler.captured, {"statement": "claim", "proof": "proof"})
            Handler.code, Handler.body = 400, {"detail": "empty proof"}
            self.assertEqual(self.backend.verify(solution, config)[0]["verdict"], "wrong")
            Handler.code = 500
            with self.assertRaises(transport.BenchError):
                self.backend.verify(solution, config)
            Handler.code, Handler.body = 200, native()["data"]
            Handler.body["verification_report"]["gaps"] = [{"location": "step", "issue": "missing"}]
            with self.assertRaises(transport.BenchError):
                self.backend.verify(solution, config)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
