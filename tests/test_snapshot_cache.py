import copy
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from crew_evolve.app import App
from crew_evolve.engine import Engine
from crew_evolve.store import Store


class SnapshotCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "workspace.sqlite")
        self.app = App(self.store)
        self.app.demo()

    def tearDown(self):
        self.temp.cleanup()

    def coverage(self, duty_id="D-100", role="captain"):
        return self.app.execute({"action": "coverage", "duty_id": duty_id, "role": role})

    def assert_matches_reference(self, answer):
        plan = answer["plan"]
        with self.store.connect() as db:
            datasets = self.store.datasets(db)
            policy = self.store.get(db, "policy")
            strategy = self.store.get(db, "strategy")
        expected = Engine(datasets, policy, strategy).coverage(plan["duty_id"], plan["role"])
        for key, value in expected.items():
            self.assertEqual(answer["result"][key], value, key)

    def assert_stale_revision(self, revision):
        with self.assertRaisesRegex(ValueError, "workspace changed"):
            self.app.assign("C-01", "D-101", "captain", revision)

    def test_import_replacement_invalidates_engine_and_rejects_old_revision(self):
        before = self.coverage()
        old_revision = before["revision"]
        content = (Path(__file__).resolve().parents[1] / "examples/crew.csv").read_text()
        content = content.replace("Asha Rao", "Asha Rao Replaced")
        pending = self.app.preview("crew", "replacement.csv", content)

        accepted = self.app.accept_import(pending["id"], pending["mapping"], old_revision)
        self.assertGreater(accepted["revision"], old_revision)
        after = self.coverage()
        self.assertFalse(after["metrics"]["cache_hit"])
        self.assertEqual(after["result"]["candidates"][0]["name"], "Asha Rao Replaced")
        self.assert_matches_reference(after)
        self.assert_stale_revision(old_revision)

    def test_policy_activation_invalidates_engine_and_rejects_old_revision(self):
        before = self.coverage()
        old_revision = before["revision"]
        policy = copy.deepcopy(self.app.state()["policy"])
        policy["min_rest_hours"] = 2
        proposal = self.app.propose_policy(policy, "Review a shorter synthetic rest threshold")
        activated = self.app.activate_policy(proposal["id"])

        self.assertGreater(activated["revision"], old_revision)
        after = self.coverage()
        self.assertFalse(after["metrics"]["cache_hit"])
        self.assert_matches_reference(after)
        self.assert_stale_revision(old_revision)

    def test_workflow_teach_and_rollback_each_create_fresh_revision(self):
        before = self.coverage()
        old_revision = before["revision"]
        change = self.app.teach("Find someone for D-100 as captain", "coverage")
        taught_revision = change["revision"]
        self.assertGreater(taught_revision, old_revision)

        taught = self.coverage()
        self.assertFalse(taught["metrics"]["cache_hit"])
        self.assert_matches_reference(taught)
        self.assert_stale_revision(old_revision)

        rolled_back = self.app.rollback(change["id"], taught_revision)
        self.assertGreater(rolled_back["revision"], taught_revision)
        after = self.coverage()
        self.assertFalse(after["metrics"]["cache_hit"])
        self.assert_matches_reference(after)
        self.assert_stale_revision(taught_revision)

    def test_assignment_and_release_each_replace_cached_snapshot(self):
        before = self.coverage()
        old_revision = before["revision"]
        assigned = self.app.assign("C-01", "D-100", "captain", old_revision)

        after_assignment = self.coverage()
        self.assertEqual(assigned["revision"], after_assignment["revision"])
        self.assertFalse(after_assignment["metrics"]["cache_hit"])
        self.assert_matches_reference(after_assignment)
        self.assert_stale_revision(old_revision)

        released = self.app.unassign("D-100", "captain", assigned["revision"])
        after_release = self.coverage()
        self.assertEqual(released["revision"], after_release["revision"])
        self.assertFalse(after_release["metrics"]["cache_hit"])
        self.assert_matches_reference(after_release)
        self.assert_stale_revision(assigned["revision"])

    def test_successful_strategy_activation_revises_snapshot(self):
        before = self.coverage()
        old_revision = before["revision"]
        report = {"selected": "indexed", "correctness_gate": True,
                  "results": [], "scores": [], "holdout": []}
        with patch("crew_evolve.optimize.benchmark", return_value=report):
            self.app.optimize()
            deadline = time.monotonic() + 2
            while self.app.optimization.get("running") and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertFalse(self.app.optimization["running"])
        state = self.app.state()
        self.assertEqual(state["strategy"], "indexed")
        self.assertGreater(state["revision"], old_revision)

        after = self.coverage()
        self.assertFalse(after["metrics"]["cache_hit"])
        self.assert_matches_reference(after)
        self.assert_stale_revision(old_revision)

    def test_concurrent_targets_share_index_without_mutating_it(self):
        with self.store.connect() as db:
            self.store.put(db, "strategy", "indexed")
            revision = self.store.bump(db)
        self.app.state()
        key = (revision, "indexed")
        engine = self.app.engine_cache[key]
        crew_keys = set(engine.by_crew)
        slot_keys = set(engine.by_slot)
        plans = [
            {"action": "coverage", "duty_id": "D-100", "role": "captain"},
            {"action": "coverage", "duty_id": "D-100", "role": "first_officer"},
            {"action": "coverage", "duty_id": "D-101", "role": "captain"},
            {"action": "coverage", "duty_id": "D-101", "role": "first_officer"},
        ] * 2

        with ThreadPoolExecutor(max_workers=4) as pool:
            answers = list(pool.map(self.app.execute, plans))

        for answer in answers:
            self.assert_matches_reference(answer)
        self.assertEqual(set(engine.by_crew), crew_keys)
        self.assertEqual(set(engine.by_slot), slot_keys)
        self.assertEqual(set(engine._indexed_history), crew_keys)
        self.assertEqual(set(engine._indexed_sweeps), crew_keys)


if __name__ == "__main__":
    unittest.main()
