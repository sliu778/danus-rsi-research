"""SQLite experiments plus content-addressed evidence and a chained event log."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .protocol import canonical, digest, require


class Busy(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "research.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    kind TEXT NOT NULL, body TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, manifest TEXT NOT NULL,
                    status TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, budget INTEGER NOT NULL,
                    deadline REAL NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(run_id TEXT NOT NULL, key TEXT NOT NULL,
                    request_hash TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
                    token TEXT, lease_until REAL, result TEXT, PRIMARY KEY(run_id,key));
                CREATE TABLE IF NOT EXISTS lineage(child TEXT PRIMARY KEY, parent TEXT NOT NULL, run_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit_batches(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                    run_id TEXT UNIQUE NOT NULL, reserved_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS audit_cases(fingerprint TEXT PRIMARY KEY, batch_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, body TEXT NOT NULL);
            """)
            version = db.execute("SELECT body FROM meta WHERE key='schema_version'").fetchone()
            require(version is None or json.loads(version[0]) == 1, "unsupported database schema")
            db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def _event(self, db, kind, body):
        last = db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last[0] if last else "0" * 64
        at = time.time()
        hashed = digest({"at": at, "kind": kind, "body": body, "previous": previous})
        db.execute("INSERT INTO events(at,kind,body,previous,hash) VALUES(?,?,?,?,?)",
                   (at, kind, canonical(body), previous, hashed))

    def event(self, kind, body):
        with self.transaction() as db:
            self._event(db, kind, body)

    def put(self, kind, value):
        key = digest({"kind": kind, "body": value})
        with self.transaction() as db:
            result = db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (key, kind, canonical(value)))
            if result.rowcount:
                self._event(db, "artifact", {"id": key, "kind": kind})
        return key

    def get(self, key, kind=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (key,)).fetchone()
        require(row is not None, "unknown artifact: " + key)
        require(kind is None or row["kind"] == kind, "artifact has wrong kind")
        value = json.loads(row["body"])
        require(digest({"kind": row["kind"], "body": value}) == key, "artifact integrity failure")
        return value

    def artifacts(self, kind):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM artifacts WHERE kind=? ORDER BY rowid", (kind,))]
        return [{"id": key, "body": self.get(key, kind)} for key in ids]

    def active(self):
        with self.connect() as db:
            row = db.execute("SELECT body FROM meta WHERE key='active_policy'").fetchone()
        return json.loads(row[0]) if row else None

    def initialize_policy(self, policy_id):
        self.get(policy_id, "policy")
        with self.transaction() as db:
            result = db.execute("INSERT OR IGNORE INTO meta VALUES('active_policy',?)", (canonical(policy_id),))
            if result.rowcount:
                self._event(db, "policy_initialized", {"policy": policy_id})

    def add_lineage(self, child, parent, run_id):
        require(child != parent, "candidate policy is unchanged")
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO lineage VALUES(?,?,?)", (child, parent, run_id))

    def new_run(self, manifest, budget, seconds, run_id=None):
        require(type(budget) is int and 1 <= budget <= 10000, "budget must be 1..10000 calls")
        require(type(seconds) is int and 1 <= seconds <= 86400, "deadline must be 1..86400 seconds")
        run_id = run_id or uuid.uuid4().hex
        require(run_id.isalnum() and len(run_id) <= 64, "invalid run id")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if old:
                require(old["manifest"] == canonical(manifest) and old["budget"] == budget,
                        "resume requires the original manifest and budget")
                return run_id
            db.execute("INSERT INTO runs VALUES(?,?,?,0,?,?,?)",
                       (run_id, canonical(manifest), "running", budget, time.time() + seconds, time.time()))
            self._event(db, "run_started", {"run": run_id, "manifest": manifest, "budget": budget})
        return run_id

    def claim(self, run_id, key, request, lease_seconds, retry_errors=False):
        """Reserve a call atomically. Expired workers cannot overwrite new results."""
        fingerprint = digest(request)
        with self.transaction() as db:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            require(run is not None, "unknown run")
            old = db.execute("SELECT * FROM jobs WHERE run_id=? AND key=?", (run_id, key)).fetchone()
            if old:
                require(old["request_hash"] == fingerprint, "job key reused for changed input")
                if old["status"] == "done" or (old["status"] == "error" and not retry_errors):
                    return None, json.loads(old["result"])
                if old["status"] == "running" and old["lease_until"] > time.time():
                    raise Busy("job already leased: " + key)
                require(old["attempts"] < 2, "job retry limit reached")
            if run["calls"] >= run["budget"] or time.time() >= run["deadline"]:
                raise BudgetExceeded("persistent call budget or run deadline exhausted")
            token = uuid.uuid4().hex
            attempts = old["attempts"] + 1 if old else 1
            db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                       (run_id, key, fingerprint, "running", attempts, token, time.time() + lease_seconds, None))
            db.execute("UPDATE runs SET calls=calls+1 WHERE id=?", (run_id,))
            self._event(db, "call_started", {"run": run_id, "key": key, "request": fingerprint, "attempt": attempts})
            return token, None

    def finish(self, run_id, key, token, result):
        state = "done" if result["status"] == "ok" else "error"
        with self.transaction() as db:
            updated = db.execute("UPDATE jobs SET status=?,result=?,token=NULL,lease_until=NULL WHERE run_id=? AND key=? AND token=?",
                                 (state, canonical(result), run_id, key, token))
            require(updated.rowcount == 1, "stale worker result rejected")
            self._event(db, "call_finished", {"run": run_id, "key": key, "status": state, "result": digest(result)})

    def finish_run(self, run_id, status):
        require(status in ("complete", "error", "budget-exhausted"), "invalid run status")
        with self.transaction() as db:
            db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
            self._event(db, "run_finished", {"run": run_id, "status": status})

    def runs(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY created DESC").fetchall()
        return [dict(r) | {"manifest": json.loads(r["manifest"])} for r in rows]

    def run(self, run_id):
        return next(r for r in self.runs() if r["id"] == run_id)

    def reserve_audit(self, audit, run_id):
        """One use even after interruption. Re-labeling/re-naming cannot reuse cases."""
        from .protocol import statement_key
        fingerprint = digest(audit)
        keys = {"statement:" + statement_key(c["task"]["prompt"]) for c in audit["cases"]}
        keys |= {"family:" + digest(c["task"]["family_id"]) for c in audit["cases"]}
        with self.transaction() as db:
            require(db.execute("SELECT 1 FROM audit_batches WHERE id=? OR fingerprint=?", (audit["id"], fingerprint)).fetchone() is None,
                    "audit batch already consumed; use a fresh batch")
            for key in keys:
                require(db.execute("SELECT 1 FROM audit_cases WHERE fingerprint=?", (key,)).fetchone() is None,
                        "audit contains previously consumed problems")
            db.execute("INSERT INTO audit_batches VALUES(?,?,?,?)", (audit["id"], fingerprint, run_id, time.time()))
            db.executemany("INSERT INTO audit_cases VALUES(?,?)", [(k, audit["id"]) for k in keys])
            self._event(db, "audit_reserved", {"run": run_id, "batch": audit["id"], "fingerprint": fingerprint})

    def record_evaluation(self, run_id, value):
        key = digest(value)
        with self.transaction() as db:
            db.execute("INSERT INTO evaluations VALUES(?,?,?)", (key, run_id, canonical(value)))
            self._event(db, "audit_evaluated", {"id": key, "run": run_id})
        return key

    def promote(self, evaluation_id, code_hash, suite_hash=None):
        """Compare-and-swap prevents an old evaluation replacing a newer baseline."""
        with self.transaction() as db:
            row = db.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
            require(row is not None, "unknown evaluation")
            value = json.loads(row["body"])
            require(digest(value) == evaluation_id, "evaluation integrity failure")
            require(value["mode"] == "live" and value["gate"]["eligible"], "evaluation is not promotion eligible")
            require(value["code_hash"] == code_hash, "evaluator code changed; obtain a fresh audit")
            require(suite_hash is not None and value["regression_suite"] == suite_hash, "regression suite changed; obtain a fresh audit")
            active = json.loads(db.execute("SELECT body FROM meta WHERE key='active_policy'").fetchone()[0])
            require(active == value["baseline"], "active policy changed since the audit")
            require(db.execute("SELECT 1 FROM audit_batches WHERE run_id=?", (row["run_id"],)).fetchone() is not None,
                    "missing audit reservation")
            db.execute("UPDATE meta SET body=? WHERE key='active_policy'", (canonical(value["candidate"]),))
            self._event(db, "policy_promoted", {"previous": active, "policy": value["candidate"], "evaluation": evaluation_id})

    def rollback(self, target):
        self.get(target, "policy")
        with self.transaction() as db:
            history = [json.loads(r[0]) for r in db.execute("SELECT body FROM events WHERE kind IN ('policy_initialized','policy_promoted')")]
            require(any(r["policy"] == target for r in history), "rollback target was never an active policy")
            db.execute("UPDATE meta SET body=? WHERE key='active_policy'", (canonical(target),))
            self._event(db, "policy_rollback", {"policy": target})

    def check_integrity(self):
        previous = "0" * 64
        with self.connect() as db:
            for row in db.execute("SELECT * FROM events ORDER BY seq"):
                require(row["previous"] == previous, "broken event chain")
                expected = digest({"at": row["at"], "kind": row["kind"], "body": json.loads(row["body"]), "previous": previous})
                require(expected == row["hash"], "event integrity failure")
                previous = expected
        return previous
