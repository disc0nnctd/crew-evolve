import copy
import random
import unittest
from datetime import datetime, timedelta

from crew_evolve.engine import Engine
from crew_evolve.optimize import workload
from crew_evolve.store import DEMO_POLICY


class ReusableEngineTests(unittest.TestCase):
    def test_indexed_reuses_precomputed_history_without_growing_on_reads(self):
        datasets = workload(24, seed=90210)
        engine = Engine(datasets, DEMO_POLICY, "indexed")
        crew_keys = set(engine.by_crew)
        slot_keys = set(engine.by_slot)

        for crew_id in list(engine.crew) + ["not-assigned"]:
            if crew_id in engine.crew:
                engine.check(crew_id, "TARGET", "captain")
        engine.coverage("TARGET", "captain")

        self.assertEqual(set(engine.by_crew), crew_keys)
        self.assertEqual(set(engine.by_slot), slot_keys)
        self.assertEqual(set(engine._indexed_history), crew_keys)
        self.assertEqual(set(engine._indexed_sweeps), crew_keys)

    def test_indexed_matches_reference_for_full_query_outputs(self):
        for seed in range(10):
            datasets = workload(32, seed=seed)
            reference = Engine(datasets, DEMO_POLICY, "reference")
            indexed = Engine(datasets, DEMO_POLICY, "indexed")
            self.assertEqual(indexed.coverage("TARGET", "captain"),
                             reference.coverage("TARGET", "captain"))
            self.assertEqual(indexed.roster(), reference.roster())

            rng = random.Random(seed)
            duties = list(reference.duties.values())
            for _ in range(12):
                crew_id = rng.choice(list(reference.crew))
                duty = rng.choice(duties)
                role = duty["required_roles"][0]
                existing = any(a["crew_id"] == crew_id and a["duty_id"] == duty["duty_id"]
                               for a in reference.assignments)
                self.assertEqual(indexed.check(crew_id, duty["duty_id"], role, existing),
                                 reference.check(crew_id, duty["duty_id"], role, existing))

    def test_constructor_and_results_are_defensive(self):
        datasets = workload(8, seed=77)
        policy = copy.deepcopy(DEMO_POLICY)
        engine = Engine(datasets, policy, "indexed")
        expected = engine.coverage("TARGET", "captain")

        datasets["duties"]["records"][0]["required_roles"].append("tampered")
        policy["label"] = "tampered"
        self.assertEqual(engine.coverage("TARGET", "captain"), expected)

        result = engine.coverage("TARGET", "captain")
        result["duty"]["required_roles"].append("tampered")
        result["candidates"][0]["sources"].append({"kind": "tampered"})
        result["policy"]["label"] = "tampered"
        self.assertEqual(engine.coverage("TARGET", "captain"), expected)

    def test_dense_overlap_and_future_history_uses_same_sweep_values(self):
        datasets = workload(1, seed=112)
        crew = datasets["crew"]["records"][0]
        crew.update(role="captain", aircraft=["A320"], available=True, base="DEL")
        duties = datasets["duties"]["records"]
        target_start = datetime.fromisoformat(duties[0]["report_at"].replace("Z", "+00:00"))
        history = []
        for index in range(7):
            duty = dict(duties[1 + index % (len(duties) - 1)])
            duty["duty_id"] = f"DENSE-{index}"
            duty["required_roles"] = ["captain"]
            start = target_start + timedelta(hours=-170 + index * 20)
            duty["report_at"] = start.isoformat().replace("+00:00", "Z")
            duty["release_at"] = (start + timedelta(hours=30)).isoformat().replace("+00:00", "Z")
            history.append(duty)
        duties.extend(history)
        datasets["assignments"]["records"] = [
            {"crew_id": crew["crew_id"], "duty_id": duty["duty_id"], "role": "captain"}
            for duty in history
        ]
        reference = Engine(datasets, DEMO_POLICY, "reference")
        indexed = Engine(datasets, DEMO_POLICY, "indexed")
        self.assertEqual(indexed.check(crew["crew_id"], "TARGET", "captain"),
                         reference.check(crew["crew_id"], "TARGET", "captain"))

    def test_long_target_without_history_is_clipped_to_seven_days(self):
        datasets = workload(1, seed=113)
        target = datasets["duties"]["records"][0]
        start = datetime.fromisoformat(target["report_at"].replace("Z", "+00:00"))
        target["release_at"] = (start + timedelta(hours=200)).isoformat().replace("+00:00", "Z")
        reference = Engine(datasets, DEMO_POLICY, "reference")
        indexed = Engine(datasets, DEMO_POLICY, "indexed")
        self.assertEqual(indexed.check("C-000000", "TARGET", "captain"),
                         reference.check("C-000000", "TARGET", "captain"))


if __name__ == "__main__":
    unittest.main()
