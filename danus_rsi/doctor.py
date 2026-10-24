"""Read-only readiness checks for live runs.

Every check reports instead of raising, so one call shows everything that is
missing. Nothing here makes a model call, starts a service, or writes outside
the state directory's own probe file. Secrets are reported as present or
absent, never printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request


def _fetch_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _import_codex():
    from danus import codex
    return codex


def diagnose(config, state_dir, env=None, platform=None, runner=subprocess.run, fetch=_fetch_json,
             importer=_import_codex):
    env = dict(os.environ if env is None else env)
    platform = platform or sys.platform
    checks = []

    def add(name, ok, detail, fix="", required=True):
        checks.append({"check": name, "ok": bool(ok), "required": required, "detail": detail, "fix": "" if ok else fix})

    add("python", sys.version_info >= (3, 11), sys.version.split()[0], "use Python 3.11 or newer")
    linux = platform.startswith("linux")
    add("platform", linux, platform, "run live commands inside WSL/Linux: bash scripts/run.sh ...")

    root = Path(env.get("DANUS_ROOT", "/opt/danus"))
    has_root = (root / "scripts" / "env.sh").is_file()
    add("danus root", has_root, str(root), "set DANUS_ROOT to the Danus checkout that contains scripts/env.sh")
    add("danus environment", bool(env.get("DANUS_RUNTIME")), env.get("DANUS_RUNTIME", "DANUS_RUNTIME unset"),
        "start through scripts/run.sh, which sources the Danus scripts/env.sh")
    add("subscription backend", env.get("CODEX_BACKEND") == "chatgpt",
        "CODEX_BACKEND=" + env.get("CODEX_BACKEND", "unset"),
        "set CODEX_BACKEND=chatgpt in the Danus config/danus.env; this project never uses an API key")

    binary, run_env = None, env
    try:
        codex = importer()
        binary = codex.resolve_bin()
        # The same launcher environment the live transport uses (CODEX_HOME and friends).
        run_env = dict(codex.subprocess_env(binary))
        add("danus package", True, "codex binary " + str(binary))
    except Exception as exc:
        add("danus package", False, type(exc).__name__ + ": " + str(exc)[:200],
            "run with the Danus Python (scripts/run.sh) so `danus` is importable")
    if binary and linux:
        try:
            login = runner([str(binary), "login", "status"], capture_output=True, text=True, timeout=30,
                           env={k: v for k, v in run_env.items()
                                if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN")})
            text = (login.stdout + login.stderr).strip()
            add("codex login", login.returncode == 0 and "chatgpt" in text.lower(), text[:200] or "no output",
                "sign in once in your own terminal: Danus.ps1 Login (or bin/codex login --device-auth)")
        except Exception as exc:
            add("codex login", False, type(exc).__name__, "check the codex binary under the Danus runtime")
    else:
        add("codex login", False, "not checked without the danus package on Linux", "fix the checks above first")

    health_url = config["verify_url"].rsplit("/", 1)[0] + "/health"
    try:
        health = fetch(health_url)
        pidfile = Path(env.get("DANUS_RUNTIME", str(root / "runtime"))) / "run" / "verify.pid"
        recorded = pidfile.read_text().strip() if pidfile.is_file() else None
        add("verifier", health.get("status") == "ok" and recorded is not None and str(health.get("pid")) == recorded,
            f"health {health.get('status')}, pid {health.get('pid')}, pidfile {recorded}",
            "restart it from the Danus root: bash scripts/services.sh up verify")
    except Exception as exc:
        add("verifier", False, f"{health_url}: {type(exc).__name__}",
            "start it from the Danus root: bash scripts/services.sh up verify (or Danus.ps1 Start)")

    state = Path(state_dir).resolve()
    try:
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("state directory", True, str(state))
    except OSError as exc:
        add("state directory", False, f"{state}: {type(exc).__name__}", "choose a writable --state directory")
    mounted = linux and str(state).startswith("/mnt/")
    add("state filesystem", not mounted, str(state), "use --state on the Linux filesystem, e.g. ~/danus-rsi-state; "
        "SQLite on a Windows mount is slow", required=False)

    add("valency token", bool(env.get("VALENCY_TOKEN", "").strip()),
        "present" if env.get("VALENCY_TOKEN", "").strip() else "absent",
        "only needed for --query/--refresh-literature; connector exports work without it", required=False)
    projects = Path(env.get("DANUS_AGENTS_ROOT") or root / "runtime" / "projects")
    add("danus projects", projects.is_dir(), str(projects),
        "only needed for handoff: create a project with bin/danus new", required=False)

    return {"ready": all(c["ok"] for c in checks if c["required"]), "checks": checks,
            "note": "Read-only: no model calls were made and no service was started."}
