"""A local workspace; source data and each learning decision survive restart."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEMO_POLICY = {"min_rest_hours": 10, "max_duty_hours": 12, "max_7day_hours": 60,
               "label": "Example policy — replace with your operational rules"}


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='state'").fetchone():
                version_row = db.execute("SELECT value FROM state WHERE key='schema_version'").fetchone()
                if version_row:
                    version = json.loads(version_row[0])
                    if type(version) is not int or not 1 <= version <= 2:
                        raise ValueError("This workspace schema is unsupported. Open it with the matching application version.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS datasets (kind TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning (
                    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL,
                    before_state TEXT NOT NULL, after_state TEXT NOT NULL, report TEXT NOT NULL,
                    created TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
                CREATE TABLE IF NOT EXISTS evidence (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS contract_evidence (
                    id INTEGER PRIMARY KEY, scope_key TEXT NOT NULL, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, UNIQUE(scope_key, digest));
                CREATE TABLE IF NOT EXISTS contract_versions (
                    scope_key TEXT NOT NULL, version INTEGER NOT NULL, learning_id INTEGER NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(scope_key, version));
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL,
                    created TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
            """)
            for key, value in (("learned", {}), ("revision", 0), ("policy", DEMO_POLICY),
                               ("strategy", "reference"), ("benchmark", None), ("schema_version", 2)):
                db.execute("INSERT OR IGNORE INTO state VALUES (?, ?)", (key, json.dumps(value)))
            self.put(db, "schema_version", 2)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def get(db, key):
        return json.loads(db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()[0])

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    @staticmethod
    def datasets(db):
        return {r["kind"]: json.loads(r["payload"]) for r in db.execute("SELECT * FROM datasets")}

    @staticmethod
    def audit(db, action, payload):
        db.execute("INSERT INTO audit(action,payload) VALUES (?,?)", (action, json.dumps(payload)))

    @staticmethod
    def bump(db):
        revision = Store.get(db, "revision") + 1
        Store.put(db, "revision", revision)
        return revision
