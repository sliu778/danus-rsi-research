import copy
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import unittest

from danus_rsi.engine import BASELINE
from danus_rsi.protocol import ProtocolError, canonical
from danus_rsi.store import BudgetExceeded, Busy, Store
from test_protocol import fixture_audit


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.policy = self.store.put("policy", BASELINE)
        self.store.initialize_policy(self.policy)

    def run_record(self, budget=10, name="run1"):
        return self.store.new_run({"test": True}, budget, 3600, name)

    def test_concurrent_budget_reservation_never_overspends(self):
        run = self.run_record(3)
        def claim(n):
            try:
                self.store.claim(run, str(n), {"n": n}, 10)
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(claim, range(20)))
        self.assertEqual(sum(outcomes), 3)
        self.assertEqual(self.store.run(run)["calls"], 3)

    def test_completed_job_resume_does_not_spend_again(self):
        run = self.run_record(1)
        token, _ = self.store.claim(run, "judge", {"proof": "a"}, 10)
        self.store.finish(run, "judge", token, {"status": "ok", "data": "result"})
        token, result = self.store.claim(run, "judge", {"proof": "a"}, 10)
        self.assertIsNone(token)
        self.assertEqual(result["data"], "result")
        self.assertEqual(self.store.run(run)["calls"], 1)
        with self.assertRaises(ProtocolError):
            self.store.claim(run, "judge", {"proof": "changed"}, 10)

    def test_lease_recovery_rejects_stale_writer(self):
        run = self.run_record()
        token, _ = self.store.claim(run, "job", {}, 10)
        with self.assertRaises(Busy):
            self.store.claim(run, "job", {}, 10)
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET lease_until=0")
        new, _ = self.store.claim(run, "job", {}, 10)
        with self.assertRaisesRegex(ProtocolError, "stale"):
            self.store.finish(run, "job", token, {"status": "ok"})
        self.store.finish(run, "job", new, {"status": "ok"})
        self.assertEqual(self.store.run(run)["calls"], 2)

    def test_errors_are_charged_and_retries_bounded(self):
        run = self.run_record()
        for attempt in range(2):
            token, _ = self.store.claim(run, "job", {}, 10, retry_errors=True)
            self.store.finish(run, "job", token, {"status": "error", "error": "transport failed"})
        with self.assertRaisesRegex(ProtocolError, "retry"):
            self.store.claim(run, "job", {}, 10, retry_errors=True)
        self.assertEqual(self.store.run(run)["calls"], 2)

    def test_resume_requires_same_manifest_and_budget(self):
        self.run_record()
        self.assertEqual(self.run_record(), "run1")
        with self.assertRaises(ProtocolError):
            self.store.new_run({"changed": True}, 10, 3600, "run1")
        with self.assertRaises(ProtocolError):
            self.run_record(11)

    def test_artifact_and_event_mutation_detected(self):
        self.store.check_integrity()
        with self.store.connect() as db:
            db.execute("UPDATE artifacts SET body='{}' WHERE id=?", (self.policy,))
        with self.assertRaisesRegex(ProtocolError, "integrity"):
            self.store.get(self.policy)
        with self.store.connect() as db:
            db.execute("UPDATE events SET body='{}' WHERE seq=1")
        with self.assertRaisesRegex(ProtocolError, "integrity"):
            self.store.check_integrity()

    def test_audit_batch_and_problem_family_are_single_use(self):
        audit = fixture_audit()
        self.store.reserve_audit(audit, "first")
        with self.assertRaises(ProtocolError):
            self.store.reserve_audit(audit, "second")
        changed = copy.deepcopy(audit)
        changed["id"] = "new-batch-name"
        for case in changed["cases"]:
            case["task"]["prompt"] += " paraphrased"
        with self.assertRaisesRegex(ProtocolError, "previously consumed"):
            self.store.reserve_audit(changed, "third")

    def test_scripted_or_ineligible_evaluation_cannot_promote(self):
        for mode, eligible in (("scripted", True), ("live", False)):
            value = {"mode": mode, "gate": {"eligible": eligible}, "baseline": self.policy, "candidate": self.policy, "code_hash": "abc"}
            key = self.store.record_evaluation(mode + str(eligible), value)
            with self.assertRaisesRegex(ProtocolError, "eligible"):
                self.store.promote(key, "abc")

    def test_rollback_rejects_never_active_candidate(self):
        candidate = self.store.put("policy", dict(BASELINE, name="experimental"))
        with self.assertRaises(ProtocolError):
            self.store.rollback(candidate)
        self.store.rollback(self.policy)


if __name__ == "__main__":
    unittest.main()
