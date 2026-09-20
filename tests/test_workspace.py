import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crew_evolve.app import App
from crew_evolve.store import Store
from crew_evolve.workspace import export_workspace, restore_workspace, validate_backup
import crew_evolve.workspace as workspace_module


TABLES = ("state", "imports", "datasets", "learning", "evidence",
          "contract_evidence", "contract_versions", "audit")


class WorkspaceBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source" / "workspace.sqlite"
        self.store = Store(self.source)
        App(self.store).demo()
        with self.store.connect() as db:
            db.execute("INSERT INTO evidence(payload) VALUES (?)", (json.dumps({"kind": "mapping", "ok": True}),))
            db.execute("INSERT INTO contract_evidence(scope_key,digest,payload) VALUES (?,?,?)",
                       ("scope", "digest", json.dumps({"rows": 1})))
            db.execute("INSERT INTO contract_versions(scope_key,version,learning_id,payload) VALUES (?,?,?,?)",
                       ("scope", 1, 0, json.dumps({"version": 1})))
            db.execute("INSERT INTO learning(kind,status,reason,before_state,after_state,report) VALUES (?,?,?,?,?,?)",
                       ("mapping", "active", "test", "{}", "{}", json.dumps({"cases": 1})))
            db.execute("INSERT INTO audit(action,payload) VALUES (?,?)",
                       ("test_event", json.dumps({"retained": True})))

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, path):
        with sqlite3.connect(path) as db:
            return {table: db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                    for table in TABLES}

    def test_round_trip_preserves_learning_evidence_and_audit(self):
        backup = self.root / "backup.sqlite"
        restored_dir = self.root / "restored"
        result = export_workspace(self.source, backup)
        self.assertEqual(result["schema_version"], 2)
        restore_workspace(backup, restored_dir)
        self.assertEqual(self.snapshot(self.source), self.snapshot(restored_dir / "workspace.sqlite"))
        self.assertEqual(validate_backup(backup)["records"], 10)

    def test_export_conflict_leaves_existing_backup_unchanged(self):
        backup = self.root / "backup.sqlite"
        export_workspace(self.source, backup)
        before = hashlib.sha256(backup.read_bytes()).digest()
        with self.assertRaises(ValueError):
            export_workspace(self.source, backup)
        self.assertEqual(before, hashlib.sha256(backup.read_bytes()).digest())

    def test_corrupt_backup_rejected_before_destination_creation(self):
        backup = self.root / "corrupt.sqlite"
        backup.write_bytes(b"not a sqlite database")
        destination = self.root / "restored"
        with self.assertRaises(ValueError):
            restore_workspace(backup, destination)
        self.assertFalse(destination.exists())

    def test_restore_conflict_leaves_existing_workspace_unchanged(self):
        backup = self.root / "backup.sqlite"
        destination = self.root / "restored"
        export_workspace(self.source, backup)
        restore_workspace(backup, destination)
        before = self.snapshot(destination / "workspace.sqlite")
        with self.assertRaises(ValueError):
            restore_workspace(backup, destination)
        self.assertEqual(before, self.snapshot(destination / "workspace.sqlite"))

    def test_invalid_backup_does_not_leave_partial_restore(self):
        backup = self.root / "invalid.sqlite"
        export_workspace(self.source, backup)
        with sqlite3.connect(backup) as db:
            db.execute("UPDATE state SET value=? WHERE key='policy'", (json.dumps({"invalid": True}),))
        destination = self.root / "restored"
        with self.assertRaises(ValueError):
            restore_workspace(backup, destination)
        self.assertFalse(destination.exists())

    def test_too_new_schema_is_rejected_without_touching_destination(self):
        backup = self.root / "future.sqlite"
        export_workspace(self.source, backup)
        with sqlite3.connect(backup) as db:
            db.execute("UPDATE state SET value='999' WHERE key='schema_version'")
        destination = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "newer"):
            restore_workspace(backup, destination)
        self.assertFalse(destination.exists())

    def test_failure_after_directory_creation_removes_only_new_empty_directory(self):
        backup = self.root / "backup.sqlite"
        destination = self.root / "restored"
        export_workspace(self.source, backup)
        real_readonly = workspace_module._readonly
        calls = [0]

        def fail_after_mkdir(path):
            calls[0] += 1
            if calls[0] == 2:
                raise ValueError("injected after mkdir failure")
            return real_readonly(path)

        with patch.object(workspace_module, "_readonly", side_effect=fail_after_mkdir), self.assertRaisesRegex(ValueError, "after mkdir"):
            restore_workspace(backup, destination)
        self.assertFalse(destination.exists())

    def test_copy_failure_removes_new_directory(self):
        backup = self.root / "backup.sqlite"
        destination = self.root / "restored"
        export_workspace(self.source, backup)
        real_readonly = workspace_module._readonly
        calls = [0]

        class FailingBackup:
            def __init__(self, database):
                self.database = database

            def backup(self, target):
                raise sqlite3.OperationalError("injected copy failure")

            def __getattr__(self, name):
                return getattr(self.database, name)

        def fail_copy(path):
            calls[0] += 1
            database = real_readonly(path)
            return FailingBackup(database) if calls[0] == 2 else database

        with patch.object(workspace_module, "_readonly", side_effect=fail_copy), self.assertRaises(sqlite3.OperationalError):
            restore_workspace(backup, destination)
        self.assertFalse(destination.exists())

    def test_final_link_failure_removes_new_directory(self):
        backup = self.root / "backup.sqlite"
        destination = self.root / "restored"
        export_workspace(self.source, backup)
        with patch.object(workspace_module, "_new_link", side_effect=ValueError("injected link failure")), self.assertRaisesRegex(ValueError, "link failure"):
            restore_workspace(backup, destination)
        self.assertFalse(destination.exists())

    def test_round_trip_preserves_operator_assignment_replacement(self):
        app = App(self.store)
        app.unassign("D-099", "captain", app.state()["revision"])
        app.assign("C-01", "D-100", "captain", app.state()["revision"])
        backup = self.root / "backup.sqlite"
        destination = self.root / "restored"
        export_workspace(self.source, backup)
        restore_workspace(backup, destination)
        self.assertEqual(self.snapshot(self.source), self.snapshot(destination / "workspace.sqlite"))

    def test_round_trip_without_assignments_then_assignment(self):
        with self.store.connect() as db:
            db.execute("DELETE FROM datasets WHERE kind='assignments'")
        backup = self.root / "backup.sqlite"
        destination = self.root / "restored"
        export_workspace(self.source, backup)
        restore_workspace(backup, destination)
        restored_app = App(Store(destination / "workspace.sqlite"))
        restored_app.assign("C-01", "D-100", "captain", restored_app.state()["revision"])
        self.assertEqual(restored_app.state()["tables"]["assignments"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
