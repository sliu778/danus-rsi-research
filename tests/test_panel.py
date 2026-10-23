import json
from pathlib import Path
import unittest

from danus_rsi import transport
from danus_rsi.engine import DEFAULT_CONFIG, decision_from, load_suite
from danus_rsi.protocol import FROZEN_PROTOCOL
from test_protocol import judgment, native


class PlaceholderConcernTests(unittest.TestCase):
    def test_placeholders_are_not_concerns(self):
        for text in ("", "   ", "None", "None.", "none", "N/A", "n/a.", "(none)", '"None"', "No concerns.",
                     "Not applicable", "—", "None noted.", "No reference concern."):
            with self.subTest(text=text):
                self.assertFalse(transport.has_reference_concern(text))

    def test_anything_else_is_still_a_concern(self):
        for text in ("The reference omits the finiteness hypothesis.", "None, but step 2 of the reference is wrong.",
                     "None; the reference uses the opposite sign convention.", "No. The reference assumes compactness twice.",
                     "Nonexistent eigenvector in the reference"):
            with self.subTest(text=text):
                self.assertTrue(transport.has_reference_concern(text))

    def test_live_smoke_case_now_accepts(self):
        # Sequential smoke rerun, 2026-10-23: three perfect `correct` votes and a native `correct`,
        # but one judge wrote "None." and the v1 rule abstained.
        votes = [judgment(), judgment(), judgment()]
        votes[0]["data"]["reference_concern"] = "None."
        self.assertEqual(decision_from(votes, native()), "accept")
        aggregate = transport.aggregate(votes, native())
        self.assertTrue(aggregate["strict_pass"])
        self.assertFalse(aggregate["reference_concern"])

    def test_real_concern_still_abstains_and_blocks_the_pass(self):
        votes = [judgment(), judgment(), judgment()]
        votes[2]["data"]["reference_concern"] = "The reference counterexample is not self-adjoint."
        self.assertEqual(decision_from(votes, native()), "abstain")
        self.assertFalse(transport.aggregate(votes, native())["strict_pass"])

    def test_judges_are_asked_for_an_empty_field(self):
        task = load_suite()["tasks"][0]
        prompt = transport.judge_prompt(task, {"answer": "a", "claim": "c", "proof": "p"}, "correctness")
        self.assertIn("Leave reference_concern as an empty string when you have no concern", prompt)


class DefaultsTests(unittest.TestCase):
    def test_protocol_version_and_sequential_panel(self):
        self.assertEqual(FROZEN_PROTOCOL, "danus-rsi-panel-v2")
        self.assertEqual(DEFAULT_CONFIG["workers"], 1)
        example = json.loads((Path(__file__).resolve().parents[1] / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example["workers"], 1)


if __name__ == "__main__":
    unittest.main()
