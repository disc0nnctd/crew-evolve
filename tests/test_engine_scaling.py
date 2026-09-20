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
        self.assertEqual(set(engine._indexed_bounds), crew_keys)

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
        result["candidates"][0]["sources"][0]["file"] = "tampered"
        result["candidates"][0]["reasons"].append("tampered")
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

    def test_exact_time_boundaries_and_assigned_target_match_reference(self):
        # Offsets are hours from target report. Exercise touching duties,
        # exact minimum rest, and history just outside/inside a seven-day window.
        cases = [(-18, -10), (-18, -9.999), (-8, 0), (-8, .001),
                 (8, 16), (7.999, 16), (18, 26), (17.999, 26),
                 (-176, -168), (-176, -167.999), (176, 184),
                 (175.999, 184)]
        for duration in (8, 200):
            for a, b in cases:
                for assigned in (False, True):
                    with self.subTest(duration=duration, history=(a, b), assigned=assigned):
                        datasets = workload(1, seed=113)
                        crew = datasets["crew"]["records"][0]
                        crew.update(role="captain", aircraft=["A320"], available=True, base="DEL")
                        target = datasets["duties"]["records"][0]
                        start = datetime.fromisoformat(target["report_at"])
                        target["release_at"] = (start + timedelta(hours=duration)).isoformat()
                        history = copy.deepcopy(target)
                        history.update(duty_id="HISTORY", _source="history.csv", _record=7,
                                       report_at=(start + timedelta(hours=a)).isoformat(),
                                       release_at=(start + timedelta(hours=b)).isoformat())
                        datasets["duties"]["records"] = [target, history]
                        assignments = [{"crew_id": crew["crew_id"], "duty_id": "HISTORY", "role": "captain"}]
                        if assigned:
                            assignments.append({"crew_id": crew["crew_id"], "duty_id": "TARGET", "role": "captain"})
                        datasets["assignments"]["records"] = assignments
                        reference = Engine(datasets, DEMO_POLICY, "reference")
                        indexed = Engine(datasets, DEMO_POLICY, "indexed")
                        self.assertEqual(indexed.coverage("TARGET", "captain"),
                                         reference.coverage("TARGET", "captain"))
                        actual = indexed.check(crew["crew_id"], "TARGET", "captain", existing=assigned)
                        self.assertEqual(actual, reference.check(crew["crew_id"], "TARGET", "captain", existing=assigned))
                        self.assertEqual(actual["sources"][-1],
                                         {"file": "history.csv", "record": 7, "kind": "duties"})
                        self.assertEqual(len(actual["sources"]), 3)

    def test_tied_ranking_and_history_reason_source_order(self):
        datasets = workload(3, seed=113)
        target = datasets["duties"]["records"][0]
        records, assignments = [target], []
        for crew in reversed(datasets["crew"]["records"]):
            crew.update(name="Same name", role="captain", aircraft=["A320"], available=True, base="DEL")
            # Deliberately reverse ID order; reasons/sources must retain input order.
            for suffix in ("Z", "A"):
                history = copy.deepcopy(target)
                history.update(duty_id=crew["crew_id"] + suffix, _source=suffix + ".csv")
                records.append(history)
                assignments.append({"crew_id": crew["crew_id"], "duty_id": history["duty_id"], "role": "captain"})
        datasets["crew"]["records"].reverse()
        datasets["duties"]["records"] = records
        datasets["assignments"]["records"] = assignments
        reference = Engine(datasets, DEMO_POLICY, "reference")
        indexed = Engine(datasets, DEMO_POLICY, "indexed")
        actual = indexed.coverage("TARGET", "captain")
        self.assertEqual(actual, reference.coverage("TARGET", "captain"))
        self.assertEqual([c["crew_id"] for c in actual["candidates"]],
                         sorted(indexed.crew))
        for candidate in actual["candidates"]:
            self.assertEqual(candidate["reasons"],
                             [f"Overlaps duty {candidate['crew_id']}{suffix}." for suffix in ("Z", "A")])
            self.assertEqual([s["file"] for s in candidate["sources"][2:]], ["Z.csv", "A.csv"])

    def test_integrity_results_cannot_change_later_queries(self):
        datasets = workload(2, seed=113)
        datasets["assignments"]["records"].extend([
            {"crew_id": "missing", "duty_id": "TARGET", "role": "captain"},
            {"crew_id": "C-000001", "duty_id": "TARGET", "role": "wrong"},
        ])
        reference = Engine(datasets, DEMO_POLICY, "reference")
        indexed = Engine(datasets, DEMO_POLICY, "indexed")
        expected = reference.integrity()
        self.assertEqual(len(expected), 2)
        issues = indexed.integrity()
        self.assertEqual(issues, expected)
        issues.clear()
        self.assertEqual(indexed.integrity(), expected)
        with self.assertRaisesRegex(ValueError, "Resolve roster data issues first"):
            indexed.coverage("TARGET", "captain")


if __name__ == "__main__":
    unittest.main()
