import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from crew_evolve.app import App
from crew_evolve.data import FIELDS
from crew_evolve.store import Store


class ContractAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "workspace.sqlite")
        self.app = App(self.store)
        self.app.demo()
        source = Path(__file__).resolve().parents[1] / "examples/crew.csv"
        rows = list(csv.DictReader(io.StringIO(source.read_text())))
        self.headers = ["cannot_work" if field == "available" else field for field in FIELDS["crew"]]
        for row in rows:
            row["cannot_work"] = "false" if row.pop("available") == "true" else "true"
        self.rows = rows
        self.mapping = {header: "available" if header == "cannot_work" else header for header in self.headers}
        self.transforms = {"cannot_work": {"op": "boolean", "invert": True}}

    def tearDown(self):
        self.temp.cleanup()

    def upload(self, scope="supplier-v1", rows=None, headers=None):
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers or self.headers)
        writer.writeheader()
        writer.writerows(rows or self.rows)
        return self.app.preview("crew", "export.csv", buf.getvalue(), scope)

    def accept(self, pending, transforms=None):
        return self.app.accept_import(pending["id"], self.mapping, self.app.state()["revision"],
                                      self.transforms if transforms is None else transforms)

    def counts(self):
        with self.store.connect() as db:
            return {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    for table in ("datasets", "imports", "learning", "evidence", "contract_evidence", "contract_versions", "audit")}

    def test_review_is_read_only_and_known_answer_survives_reuse(self):
        pending = self.upload()
        before, revision = self.counts(), self.app.state()["revision"]
        tested = self.app.test_import(pending["id"], self.mapping, self.transforms)
        self.assertTrue(tested["valid"], tested)
        self.assertEqual(before, self.counts())
        self.assertEqual(revision, self.app.state()["revision"])
        accepted = self.accept(pending)
        self.assertTrue(accepted["accepted"])
        result = self.app.execute({"action": "coverage", "duty_id": "D-100", "role": "captain"})
        self.assertEqual([c["crew_id"] for c in result["result"]["candidates"] if c["passes"]], ["C-01"])
        self.app = App(Store(self.store.path))
        later = [dict(row, name=row["name"] + " Later") for row in self.rows]
        preview = self.upload(rows=later)
        self.assertTrue(preview["contract_reused"])
        self.assertEqual(preview["transforms"], self.transforms)
        self.assertTrue(self.accept(preview)["accepted"])
        self.assertEqual(self.app.state()["tables"]["crew"]["records"][0]["name"], "Asha Rao Later")

    def test_scope_schema_and_polarity_do_not_leak(self):
        self.accept(self.upload())
        for pending in (self.upload("different-supplier"), self.upload(""), self.upload(headers=list(reversed(self.headers)))):
            self.assertFalse(pending["contract_reused"])
            self.assertEqual(pending["transforms"], {})
            self.assertNotIn("cannot_work", pending["mapping"])
        unknown = self.upload("different-supplier")
        checked = self.app.test_import(unknown["id"], self.mapping, {})
        self.assertFalse(checked["valid"])

    def test_rejected_change_keeps_table_and_pending_and_records_reason(self):
        first = self.upload()
        # Explicit enum is another representation of the same reviewed meaning.
        self.assertTrue(self.accept(first)["accepted"])
        pending = self.upload()
        before = self.app.state()
        changed = {"cannot_work": {"op": "enum", "values": {"true": "true", "false": "false"}}}
        try:
            response = self.accept(pending, changed)
        except ValueError:
            # An explicit polarity guard can reject this before replay. Construct
            # a valid change on another field to test the replay rejection path.
            changed = self.transforms | {"base": {"op": "enum", "values": {"DEL": "BOM", "BOM": "DEL"}}}
            response = self.accept(pending, changed)
        self.assertFalse(response["accepted"])
        self.assertEqual(response["learning"]["status"], "rejected")
        after = self.app.state()
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["tables"], after["tables"])
        self.assertEqual(before["learned"], after["learned"])
        self.assertTrue(response["learning"]["report"]["failures"])
        self.assertTrue(self.app.test_import(pending["id"], self.mapping, self.transforms)["valid"])

    def test_invalid_late_row_is_atomic_and_rollback_invalidates_old_revision(self):
        change = self.accept(self.upload())["learning"]
        bad = [dict(row) for row in self.rows]
        bad[-1]["cannot_work"] = "perhaps"
        pending = self.upload(rows=bad)
        before = self.app.state()
        with self.assertRaises(ValueError):
            self.accept(pending)
        self.assertEqual(before, self.app.state())
        self.app.rollback(change["id"], before["revision"])
        self.assertGreater(self.app.state()["revision"], before["revision"])
        self.assertEqual(before["tables"], self.app.state()["tables"])
        self.assertFalse(self.upload()["contract_reused"])
        with self.assertRaisesRegex(ValueError, "workspace changed"):
            self.app.accept_import(pending["id"], self.mapping, before["revision"], self.transforms)

    def test_new_version_after_rollback_does_not_recycle_number(self):
        first = self.accept(self.upload())["learning"]
        self.app.rollback(first["id"])
        second = self.accept(self.upload())["learning"]
        self.assertGreater(second["report"]["version"], first["report"]["version"])

    def test_canonical_scope_metadata_matches_reused_contract(self):
        pending = self.upload()
        response = self.app.accept_import(pending["id"], self.mapping, self.app.state()["revision"], self.transforms, " supplier-v1 ")
        self.assertTrue(response["accepted"])
        table = self.app.state()["tables"]["crew"]
        self.assertEqual(table["source_contract"], "supplier-v1")
        self.assertEqual(table["records"][0]["_source_contract"], "supplier-v1")
        self.assertTrue(self.upload()["contract_reused"])

    def test_existing_workspace_schema_upgrades_without_replacing_data(self):
        with self.store.connect() as db:
            original = json.dumps(self.store.datasets(db), sort_keys=True)
            db.execute("DROP TABLE contract_evidence")
            db.execute("DROP TABLE contract_versions")
            db.execute("DELETE FROM state WHERE key='schema_version'")
        migrated = Store(self.store.path)
        with migrated.connect() as db:
            self.assertEqual(original, json.dumps(migrated.datasets(db), sort_keys=True))
            self.assertEqual(migrated.get(db, "schema_version"), 2)

    def test_evidence_budget_never_discards_history_or_partially_imports(self):
        from unittest.mock import patch
        self.accept(self.upload())
        later = [dict(row, name=row["name"] + " Different") for row in self.rows]
        pending = self.upload(rows=later)
        before = self.app.state()
        with patch('crew_evolve.contract_learning.MAX_EVIDENCE_CASES', 1):
            with self.assertRaisesRegex(ValueError, "evidence limit"):
                self.accept(pending)
        self.assertEqual(before, self.app.state())
        self.assertEqual(self.counts()['contract_evidence'], 1)


if __name__ == "__main__":
    unittest.main()
