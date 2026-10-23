"""Data contracts. Decisions are computed by code, never accepted from an agent."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"
DOMAINS = {"mathematics", "theoretical-physics"}
ROLES = ("correctness", "adversarial", "completeness")
FROZEN_PROTOCOL = "danus-rsi-panel-v2"  # v2: placeholder reference concerns ("None.") count as no concern
SOLVER_PROTOCOL = "danus-rsi-solver-v2"  # v2: strict accepts counted over k attempts per problem
# Fields each arm's optimizer may change; everything else must be identical to the parent.
ARM_FIELDS = {"verifier": {"name", "verifier_guidance", "rationale"},
              "solver": {"name", "solver_guidance", "rationale"}}


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


def require_arm_change(arm, parent, candidate):
    """An arm may revise only its own strategy text; the other side stays frozen."""
    require(arm in ARM_FIELDS, "unknown improvement arm")
    frozen = set(parent) - ARM_FIELDS[arm]
    require(all(candidate[field] == parent[field] for field in frozen),
            f"{arm} optimizer changed a frozen field: " + ", ".join(sorted(f for f in frozen if candidate[f] != parent[f])))
    return candidate


def shares_window(text_value, source, window=8):
    """True when `text_value` repeats any run of `window` consecutive words from `source`."""
    words = lambda s: re.findall(r"[a-z0-9]+", s.casefold())
    source_words = words(source)
    grams = {tuple(source_words[i:i + window]) for i in range(len(source_words) - window + 1)}
    target = words(text_value)
    return any(tuple(target[i:i + window]) in grams for i in range(len(target) - window + 1))


def require_no_copied_answers(guidance, tasks, minimum=60):
    """Reject strategy text that quotes development prompts or references verbatim.

    A solver strategy that memorizes development answers would raise the
    development solve rate without any transferable skill."""
    folded = re.sub(r"\s+", " ", guidance).casefold()
    for task in tasks:
        for field in ("prompt", "reference"):
            for sentence in re.split(r"(?<=[.;:])\s+", task.get(field, "")):
                chunk = re.sub(r"\s+", " ", sentence).strip().casefold()
                require(len(chunk) < minimum or chunk not in folded,
                        "strategy text copies development task content: " + task["id"])
    return guidance


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


def validate_solver_audit(audit, exposed_tasks):
    """Fresh, independently reviewed problems for the solver arm; no candidate proofs."""
    require(audit.get("split") == "solver-audit", "expected solver-audit split")
    require(audit.get("review_status") == "independently-reviewed", "solver audit requires independent review")
    for key in ("id", "reviewer", "provenance"):
        text(audit.get(key), "solver audit " + key)
    tasks = audit.get("tasks", [])
    require(len(tasks) >= 12, "solver audit requires at least 12 problems")
    exposed_families = {t["family_id"] for t in exposed_tasks}
    exposed_prompts = {statement_key(t["prompt"]) for t in exposed_tasks}
    ids, statements, families, per_domain = set(), set(), set(), {}
    for task in tasks:
        validate_task(task)
        require(task["id"] not in ids, "duplicate solver audit task")
        ids.add(task["id"])
        statement = statement_key(task["prompt"])
        require(statement not in statements, "duplicate solver audit problem statement")
        statements.add(statement)
        require(task["family_id"] not in exposed_families and statement not in exposed_prompts,
                "solver audit overlaps development/research exposure")
        require(not task.get("calibration"), "solver audit tasks carry no candidate proofs or labels")
        families.add(task["family_id"])
        per_domain[task["domain"]] = per_domain.get(task["domain"], 0) + 1
    require(len(families) >= 8, "solver audit requires at least 8 distinct families")
    require(all(per_domain.get(d, 0) >= 5 for d in DOMAINS), "solver audit requires at least five problems in each domain")
    return audit


def wilson(successes, trials, z=1.96):
    """Wilson score interval for a binomial proportion; descriptive, never a gate input."""
    if not trials:
        return None
    p = successes / trials
    centre = (p + z * z / (2 * trials)) / (1 + z * z / trials)
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / (1 + z * z / trials)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def attempt_decisions(row):
    """A problem row holds one attempt (`decision`) or several (`attempts`)."""
    return [a["decision"] for a in row["attempts"]] if "attempts" in row else [row["decision"]]


def solve_metrics(rows):
    """Strict-accept rate over all attempts; abstentions are not solves."""
    decisions = [d for r in rows for d in attempt_decisions(r)]
    attempts = len(decisions)
    count = decisions.count
    return {"n": len(rows), "attempts": attempts, "accepted": count("accept"), "rejected": count("reject"),
            "abstained": count("abstain"), "errors": count("error"),
            "solve_rate": count("accept") / attempts if attempts else None,
            "solve_rate_95ci": wilson(count("accept"), attempts)}


def solver_gate(baseline, candidate, minimum_gain=0.10):
    """Frozen paired rule for solver strategies judged by one fixed verifier policy.

    Counts strict accepts over all attempts, so k samples per problem need a
    gain of max(1, ceil(0.1 n k)). With k = 1 this is the single-sample rule.
    Not a significance test: a shared model family and stochastic decoding
    limit what a pass means; the reported intervals show how wide the noise is."""
    if [r["task_id"] for r in baseline] != [r["task_id"] for r in candidate]:
        return {"eligible": False, "reasons": ["unpaired solver tasks"]}
    if [r["domain"] for r in baseline] != [r["domain"] for r in candidate]:
        return {"eligible": False, "reasons": ["solver task domains changed"]}
    if [len(attempt_decisions(r)) for r in baseline] != [len(attempt_decisions(r)) for r in candidate]:
        return {"eligible": False, "reasons": ["unequal attempts per problem"]}
    b, c = solve_metrics(baseline), solve_metrics(candidate)
    reasons = []
    if not b["n"]:
        reasons.append("no solver tasks")
    if b["errors"] or c["errors"]:
        reasons.append("infrastructure errors invalidate the comparison")
    needed = max(1, math.ceil(minimum_gain * b["attempts"]))
    if c["accepted"] - b["accepted"] < needed:
        reasons.append(f"strict-accept gain is below {needed} attempt(s)")
    for domain in sorted(DOMAINS):
        bd = solve_metrics([r for r in baseline if r["domain"] == domain])
        cd = solve_metrics([r for r in candidate if r["domain"] == domain])
        if cd["accepted"] < bd["accepted"]:
            reasons.append(domain + ": fewer strict accepts")
    lost = [b_row["task_id"] for b_row, c_row in zip(baseline, candidate)
            if attempt_decisions(c_row).count("accept") < attempt_decisions(b_row).count("accept")]
    return {"eligible": not reasons, "reasons": reasons, "baseline": b, "candidate": c, "lost_solves": lost}


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
            "valid_accept_95ci": wilson(accepted, len(valid)), "invalid_reject_95ci": wilson(rejected, len(invalid)),
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
