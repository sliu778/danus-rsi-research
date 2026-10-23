#!/usr/bin/env python3
"""Offline CLI fixture; never contacts a model."""
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
sys.stdin.read()
mode = os.environ.get("DANUS_TEST_MODE", "ok")
if mode == "sleep":
    time.sleep(30)
if mode == "exit":
    raise SystemExit(7)
target = Path(args[args.index("--output-last-message") + 1])
target.write_text("{broken" if mode == "malformed" else json.dumps({"answer": "fixture", "claim": "fixture", "proof": "fixture"}))
print(json.dumps({"type": "item.completed", "item": {"type": "command_execution" if mode == "tool" else "agent_message", "text": "fixture"}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 10}}))
