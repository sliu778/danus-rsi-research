"""Data contracts. Decisions are computed by code, never accepted from an agent."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"
DOMAINS = {"mathematics", "theoretical-physics"}
ROLES = ("correctness", "adversarial", "completeness")
FROZEN_PROTOCOL = "danus-rsi-panel-v1"


class ProtocolError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise ProtocolError(message)


def text(value, name, maximum=50000):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum, f"invalid {name}")
    return value


def statement_key(prompt):
    return digest(re.sub(r"\s+", " ", prompt).strip().casefold())


def validate_policy(value):
    require(set(value) == {"name", "solver_guidance", "verifier_guidance", "curriculum_domains", "rationale"}, "policy fields differ from allowed strategy fields")
    for key in ("name", "solver_guidance", "verifier_guidance", "rationale"):
        text(value[key], key, 12000)
    require(isinstance(value["curriculum_domains"], list) and 0 < len(value["curriculum_domains"]) <= 2, "invalid curriculum")
    require(set(value["curriculum_domains"]) <= DOMAINS and len(set(value["curriculum_domains"])) == len(value["curriculum_domains"]), "invalid curriculum domains")
    return value


def validate_task(task):
    for key in ("id", "family_id", "title", "prompt", "reference"):
        text(task.get(key), key)
    require(task.get("domain") in DOMAINS, "task domain must be mathematics or theoretical-physics")
    require(isinstance(task.get("rubric"), list) and task["rubric"], "task needs a rubric")
    for item in task["rubric"]:
        text(item, "rubric item")
    return task


def validate_suite(suite):
    require(suite.get("split") == "development", "built-in/imported curriculum must be development data")
    require(suite.get("tasks"), "empty development suite")
    ids = set()
    for task in suite["tasks"]:
        validate_task(task)
        require(task["id"] not in ids, "duplicate task id")
        ids.add(task["id"])
    return suite


def calibration_cases(suite):
    cases = []
    for task in suite["tasks"]:
        for fixture in task.get("calibration", []):
            require(fixture["label"] in ("valid", "invalid"), "invalid calibration label")
            cases.append({"id": task["id"] + ":" + fixture["label"], "task": task,
                          "solution": fixture["solution"], "label": fixture["label"]})
    require(bool(cases), "suite contains no calibration candidates")
    return cases


def validate_audit(audit, exposed_tasks):
    """Attestation is a human trust boundary, not automatic expert certification."""
    require(audit.get("split") == "audit", "expected audit split")
    require(audit.get("review_status") == "independently-reviewed", "audit requires independent review")
    text(audit.get("reviewer"), "reviewer")
    text(audit.get("provenance"), "audit provenance")
    text(audit.get("id"), "audit id")
    cases = audit.get("cases", [])
    require(len(cases) >= 20, "audit requires at least 20 labeled candidates")
    exposed_families = {t["family_id"] for t in exposed_tasks}
    exposed_prompts = {statement_key(t["prompt"]) for t in exposed_tasks}
    seen, counts, families, candidates, statement_families = set(), {}, set(), set(), {}
    for case in cases:
        text(case.get("id"), "audit case id")
        require(case["id"] not in seen, "duplicate audit case")
        seen.add(case["id"])
        task = validate_task(case["task"])
        require(task["family_id"] not in exposed_families and statement_key(task["prompt"]) not in exposed_prompts,
                "audit overlaps development/research exposure")
        require(case.get("label") in ("valid", "invalid"), "invalid audit label")
        families.add(task["family_id"])
        key = (task["domain"], case["label"])
        counts[key] = counts.get(key, 0) + 1
        for field in ("answer", "claim", "proof"):
            text(case.get("solution", {}).get(field), "audit solution " + field)
        statement = statement_key(task["prompt"])
        require(statement not in statement_families or statement_families[statement] == task["family_id"],
                "identical audit problems have inconsistent family IDs")
        statement_families[statement] = task["family_id"]
        candidate = digest({"statement": statement, "solution": case["solution"]})
        require(candidate not in candidates, "duplicate audit candidate, possibly with contradictory labels")
        candidates.add(candidate)
    require(len(families) >= 10, "audit requires at least 10 distinct families")
    require(all(counts.get((d, y), 0) >= 5 for d in DOMAINS for y in ("valid", "invalid")),
            "audit requires at least five valid and five invalid candidates in each domain")
    return audit


def metrics(rows):
    """Abstention/error is never a correct rejection; full coverage is required."""
    valid = [r for r in rows if r["label"] == "valid"]
    invalid = [r for r in rows if r["label"] == "invalid"]
    accepted = sum(r["decision"] == "accept" for r in valid)
    rejected = sum(r["decision"] == "reject" for r in invalid)
    fa = sum(r["decision"] == "accept" for r in invalid)
    coverage = sum(r["decision"] in ("accept", "reject") for r in rows) / len(rows) if rows else 0
    balanced = (accepted / len(valid) + rejected / len(invalid)) / 2 if valid and invalid else None
    return {"n": len(rows), "valid": len(valid), "invalid": len(invalid), "coverage": coverage,
            "false_accepts": fa, "false_accept_rate": fa / len(invalid) if invalid else None,
            "balanced_accuracy": balanced}


def promotion_gate(baseline, candidate):
    """Frozen, descriptive finite-sample gate; not a statistical guarantee."""
    reasons = []
    if [r["case_id"] for r in baseline] != [r["case_id"] for r in candidate]:
        return {"eligible": False, "reasons": ["unpaired audit cases"]}
    if [(r["label"], r["domain"]) for r in baseline] != [(r["label"], r["domain"]) for r in candidate]:
        return {"eligible": False, "reasons": ["audit labels/domains changed"]}
    b, c = metrics(baseline), metrics(candidate)
    if b["coverage"] != 1 or c["coverage"] != 1:
        reasons.append("incomplete coverage or abstention")
    if b["balanced_accuracy"] is None or c["balanced_accuracy"] is None:
        reasons.append("both labels are required")
    elif c["balanced_accuracy"] - b["balanced_accuracy"] < 0.05 - 1e-12:
        reasons.append("balanced accuracy gain is below 0.05")
    if c["false_accepts"] > b["false_accepts"]:
        reasons.append("false acceptances increased")
    for domain in DOMAINS:
        bm = metrics([r for r in baseline if r["domain"] == domain])
        cm = metrics([r for r in candidate if r["domain"] == domain])
        if cm["balanced_accuracy"] is None or bm["balanced_accuracy"] is None:
            reasons.append(domain + ": missing label coverage")
        elif cm["balanced_accuracy"] < bm["balanced_accuracy"] or cm["false_accepts"] > bm["false_accepts"]:
            reasons.append(domain + ": regression")
    return {"eligible": not reasons, "reasons": reasons, "baseline": b, "candidate": c}
