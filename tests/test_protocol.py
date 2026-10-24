import copy
import unittest

from danus_rsi import agents, transport
from danus_rsi.engine import BASELINE, balanced_selection, decision_from, load_suite
from danus_rsi.protocol import (ProtocolError, calibration_cases, metrics, promotion_gate,
                                validate_audit, validate_policy, validate_suite)


def fixture_audit():
    cases = []
    for domain in ("mathematics", "theoretical-physics"):
        for n in range(5):
            for label in ("valid", "invalid"):
                key = f"{domain}-{n}"
                task = {"id": key, "family_id": key, "title": key, "domain": domain,
                        "prompt": "PRIVATE PROBLEM " + key, "reference": "private reference",
                        "rubric": ["logical validity"]}
                cases.append({"id": key + "-" + label, "task": task, "label": label,
                              "solution": {"answer": "fixture", "claim": "fixture", "proof": "fixture " + label}})
    return {"id": "private-test-batch", "split": "audit", "review_status": "independently-reviewed",
            "reviewer": "TEST FIXTURE ONLY", "provenance": "Software test, not mathematical evidence", "cases": cases}


def rows(decisions):
    return [{"case_id": c["id"], "domain": c["task"]["domain"], "label": c["label"], "decision": decision}
            for c, decision in zip(fixture_audit()["cases"], decisions)]


def judgment(verdict="correct"):
    return {"status": "ok", "data": {
        "verdict": verdict, "scores": {k: 4 if verdict == "correct" else 1 for k in transport.DIMENSIONS},
        "critical_errors": [] if verdict == "correct" else ["explicit invalid inference"], "gaps": [],
        "rationale": "fixture", "reference_concern": ""}}


def native(verdict="correct"):
    return {"status": "ok", "data": {"verdict": verdict, "verification_report": {
        "summary": "fixture", "gaps": [],
        "critical_errors": [] if verdict == "correct" else [{"location": "step", "issue": "invalid"}]},
        "repair_hints": ""}}


class ProtocolTests(unittest.TestCase):
    def test_development_suite_coverage(self):
        suite = validate_suite(load_suite())
        self.assertEqual(len(suite["tasks"]), 18)
        cases = calibration_cases(suite)
        self.assertEqual(len(cases), 18)
        self.assertEqual({c["task"]["domain"] for c in balanced_selection(cases, 4)},
                         {"mathematics", "theoretical-physics"})
        self.assertEqual({(c["task"]["domain"], c["label"]) for c in balanced_selection(cases, 4)},
                         {(d, y) for d in ("mathematics", "theoretical-physics") for y in ("valid", "invalid")})

    def test_solver_cannot_see_references_or_labels(self):
        task = copy.deepcopy(load_suite()["tasks"][0])
        task.update(reference="SECRET_REFERENCE", calibration=[{"label": "SECRET_LABEL"}])
        text = transport.solver_prompt(task)
        self.assertNotIn("SECRET_REFERENCE", text)
        self.assertNotIn("SECRET_LABEL", text)

    def test_judge_receives_no_policy_name_or_labels(self):
        task = copy.deepcopy(load_suite()["tasks"][0])
        task["calibration"] = [{"label": "HIDDEN_LABEL"}]
        text = agents.verification_prompt(task, {"claim": "x", "proof": "y", "answer": "z"},
                                          dict(BASELINE, name="HIDDEN_NAME"), "adversarial")
        self.assertNotIn("HIDDEN_LABEL", text)
        self.assertNotIn("HIDDEN_NAME", text)

    def test_policy_cannot_change_gate_or_model(self):
        for forbidden in ("model", "gate", "labels", "max_calls"):
            with self.subTest(forbidden=forbidden), self.assertRaises(ProtocolError):
                validate_policy(dict(BASELINE, **{forbidden: "anything"}))

    def test_audit_rejects_family_and_text_overlap(self):
        audit = fixture_audit()
        validate_audit(audit, [])
        with self.assertRaisesRegex(ProtocolError, "overlaps"):
            validate_audit(audit, [audit["cases"][0]["task"]])
        exposed = dict(audit["cases"][0]["task"], family_id="renamed",
                       prompt="  " + audit["cases"][0]["task"]["prompt"].lower() + "\n")
        with self.assertRaisesRegex(ProtocolError, "overlaps"):
            validate_audit(audit, [exposed])

    def test_audit_requires_independent_review_and_balance(self):
        for mutate in (lambda a: a.update(review_status="agent-reviewed"),
                       lambda a: a["cases"].pop(), lambda a: a.update(reviewer="")):
            audit = fixture_audit()
            mutate(audit)
            with self.assertRaises(ProtocolError):
                validate_audit(audit, [])

    def test_duplicate_candidates_and_disguised_families_rejected(self):
        audit = fixture_audit()
        audit["cases"][1]["solution"] = copy.deepcopy(audit["cases"][0]["solution"])
        with self.assertRaisesRegex(ProtocolError, "duplicate audit candidate"):
            validate_audit(audit, [])
        audit = fixture_audit()
        audit["cases"][1]["task"]["family_id"] = "disguised-family"
        with self.assertRaisesRegex(ProtocolError, "inconsistent family"):
            validate_audit(audit, [])

    def test_abstentions_and_errors_do_not_score_as_correct_rejections(self):
        score = metrics(rows(["abstain"] * 20))
        self.assertEqual(score["balanced_accuracy"], 0)
        self.assertEqual(score["coverage"], 0)
        self.assertFalse(promotion_gate(rows(["reject"] * 20), rows(["error"] * 20))["eligible"])

    def test_strictly_better_balanced_candidate_can_pass_gate(self):
        base = rows(["reject"] * 20)
        candidate = rows(["accept", "reject"] * 10)
        gate = promotion_gate(base, candidate)
        self.assertTrue(gate["eligible"])
        self.assertEqual(gate["baseline"]["balanced_accuracy"], 0.5)
        self.assertEqual(gate["candidate"]["balanced_accuracy"], 1)

    def test_more_false_accepts_blocks_even_with_accuracy_gain(self):
        candidate = rows(["accept", "reject"] * 10)
        candidate[1]["decision"] = "accept"
        gate = promotion_gate(rows(["reject"] * 20), candidate)
        self.assertFalse(gate["eligible"])
        self.assertIn("false acceptances increased", gate["reasons"])

    def test_domain_regression_and_mismatched_pairs_block(self):
        base = rows(["accept", "reject"] * 10)
        candidate = copy.deepcopy(base)
        candidate[-2]["decision"] = "reject"
        self.assertFalse(promotion_gate(base, candidate)["eligible"])
        self.assertFalse(promotion_gate(base, list(reversed(candidate)))["eligible"])

    def test_dissent_native_failure_and_reference_concerns_abstain(self):
        self.assertEqual(decision_from([judgment()] * 3, native()), "accept")
        self.assertEqual(decision_from([judgment("incorrect")] * 3, native("wrong")), "reject")
        self.assertEqual(decision_from([judgment(), judgment(), judgment("incorrect")], native()), "abstain")
        self.assertEqual(decision_from([judgment()] * 3, native("wrong")), "abstain")
        self.assertEqual(decision_from([judgment()] * 3, {"status": "error"}), "error")
        value = judgment()
        value["data"]["reference_concern"] = "reference hypothesis missing"
        self.assertEqual(decision_from([value] * 3, native()), "abstain")

    def test_inconsistent_native_response_rejected(self):
        value = native()["data"]
        value["verification_report"]["gaps"] = [{"location": "step", "issue": "unsupported"}]
        with self.assertRaises(transport.BenchError):
            transport.validate_native(value)

    def test_tool_events_are_rejected(self):
        with self.assertRaises(transport.BenchError):
            transport.inspect_events('{"type":"item.completed","item":{"type":"command_execution"}}\n'
                                     '{"type":"turn.completed"}')


if __name__ == "__main__":
    unittest.main()
