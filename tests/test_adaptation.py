import unittest
from contextlib import redirect_stderr
from io import StringIO

from crew_evolve.contracts import apply_contract, validate_contract
from benchmarks.adaptation.generate import (_canonical, _canonical_expected,
                                             _source_tables)
from benchmarks.adaptation.protocol import (BUDGETS, SEEDS, evaluate_family,
                                             iter_families, load_family,
                                             load_manifest, run_protocol)


class AdaptationFixtureTests(unittest.TestCase):
    def test_frozen_manifest_has_declared_splits_budgets_and_fingerprints(self):
        manifest = load_manifest()
        self.assertEqual(manifest["splits"], {"train": 6, "development": 3, "final": 3})
        self.assertEqual(tuple(manifest["budgets"]), BUDGETS)
        self.assertEqual(tuple(manifest["seeds"]), SEEDS)
        self.assertTrue(all(f["files"] and f["labels_sha256"] for f in manifest["families"]))
        self.assertFalse(manifest["labels_are_model_input"])

    def test_model_input_does_not_include_known_answers(self):
        family = load_family("train_03_cannot_work")
        self.assertNotIn("labels", family)
        labelled = load_family("train_03_cannot_work", include_labels=True)
        self.assertIn("labels", labelled)
        self.assertNotEqual(set(family), set(labelled))

    def test_cannot_work_contract_inverts_boolean_and_aliases_do_not(self):
        family = load_family("train_03_cannot_work", include_labels=True)
        alias = evaluate_family(family, "aliases", 0, 11)
        adapted = evaluate_family(family, "contracts", 20, 11)
        self.assertEqual(alias["coverage"], 0.0)
        self.assertGreater(adapted["coverage"], 0.5)
        self.assertEqual(adapted["corrections"], 9)
        self.assertTrue(adapted["trace"][0]["scored_before_feedback"])
        self.assertEqual(adapted["trace"][0]["feedback_after_score"], "crew:Badge")
        self.assertFalse(adapted["trace"][0]["actual_accept"])
        self.assertEqual(adapted["trace"][0]["outcome"], "abstain")

    def test_development_report_is_grouped_by_source_family(self):
        aliases = run_protocol(method="aliases")
        contracts = run_protocol(method="contracts", budgets=(0, 1, 5, 10, 20), seeds=SEEDS)
        manifest = load_manifest()
        self.assertEqual(contracts["protocol_version"], manifest["protocol_version"])
        self.assertEqual(contracts["fixture_schema_version"], manifest["schema_version"])
        self.assertEqual(len(contracts["manifest_sha256"]), 64)
        self.assertEqual(contracts["manifest_fingerprint"], contracts["manifest_sha256"])
        self.assertEqual(len(aliases["results"]), 3 * len(BUDGETS) * len(SEEDS))
        summary = contracts["summary"]
        self.assertEqual(len(summary["by_source_family"]), 3)
        self.assertIn("no row-level significance", summary["uncertainty_note"])
        self.assertEqual(len(summary["by_budget"]), len(BUDGETS))
        self.assertTrue(all(group["macro_by_source_family"]["scenario_count"] == len(SEEDS) * 3
                            for group in summary["by_budget"]))
        self.assertEqual(contracts["baselines"]["fixed_model"], "not-run")
        self.assertGreater(
            contracts["summary"]["macro_by_source_family"]["coverage"],
            aliases["summary"]["macro_by_source_family"]["coverage"],
        )

    def test_final_family_count_and_default_guard(self):
        self.assertEqual(sum(1 for _ in iter_families("final")), 3)

    def test_train_and_development_contracts_match_known_records(self):
        for split in ("train", "development"):
            for family in iter_families(split, include_labels=True):
                labels = family["labels"]
                for kind, table in family["tables"].items():
                    contract = validate_contract(kind, table["headers"], labels["mapping"][kind],
                                                 labels["transforms"].get(kind, {}), labels["source_contract"])
                    records = apply_contract(kind, table["headers"], table["rows"], contract)
                    clean = [{key: value for key, value in row.items() if not key.startswith("_")}
                             for row in records]
                    self.assertEqual(clean, labels["expected"]["valid"]["records"][kind])

    def test_v2_transform_styles_have_train_scoped_analogues(self):
        for index, style in enumerate(("v2_neg_enum", "v2_local_dates", "v2_mixed"), 1):
            canonical = _canonical(1700 + index)
            tables, mapping, transforms = _source_tables(canonical, style)
            expected = _canonical_expected(canonical)
            for kind in ("crew", "duties", "assignments"):
                table = {"headers": list(mapping[kind]), "rows": tables[kind]}
                contract = validate_contract(kind, table["headers"], mapping[kind],
                                             transforms[kind], f"train-analogue-{style}")
                records = apply_contract(kind, table["headers"], table["rows"], contract)
                clean = [{key: value for key, value in row.items() if not key.startswith("_")}
                         for row in records]
                self.assertEqual(clean, expected[kind])

    def test_nonthrowing_malformed_case_is_not_scored_as_correct(self):
        from benchmarks.adaptation.protocol import _score_case
        family = load_family("train_01_canonical", include_labels=True)
        case = {"id": "malformed_nonthrowing", "kind": "crew",
                "mutation": {"row": 0, "field": "role", "value": "UNKNOWN_ROLE"},
                "expected": {"accepted": False, "reason": "unknown_enum"}}
        result = _score_case(family, family["labels"], case, "aliases",
                             {"contracts": {}, "aliases": {}})
        self.assertTrue(result[3])
        self.assertFalse(result[0])
        self.assertEqual(result[4], "accepted")

    def test_feedback_is_per_field_and_future_seed_values_are_distinct(self):
        family = load_family("development_01_polarity", include_labels=True)
        aliases = evaluate_family(family, "aliases", 1, 11)
        contracts = evaluate_family(family, "contracts", 1, 11)
        self.assertEqual(aliases["trace"][0]["feedback_after_score"], contracts["trace"][0]["feedback_after_score"])
        self.assertGreaterEqual(sum(1 for row in contracts["trace"] if row["case"].startswith("future_values_")), 20)
        self.assertNotEqual(evaluate_family(family, "contracts", 20, 11)["scenario_seed"],
                            evaluate_family(family, "contracts", 20, 23)["scenario_seed"])

    def test_expected_and_observed_fault_reasons_stay_separate(self):
        family = load_family("development_01_polarity", include_labels=True)
        result = evaluate_family(family, "contracts", 20, 11)
        missing = next(row for row in result["trace"] if row["case"] == "missing_value")
        self.assertEqual(missing["expected_reason"], "missing")
        self.assertEqual(missing["observed_reason"], "invalid_boolean")
        self.assertTrue(missing["correct"])

    def test_unsupported_control_is_unassessable_and_not_credited(self):
        from benchmarks.adaptation.protocol import _score_case
        family = load_family("development_01_polarity", include_labels=True)
        case = {"id": "bad_control", "kind": "crew",
                "mutation": {"row": 0, "field": "Badge", "value": ""},
                "expected": {"accepted": False, "reason": "missing"}}
        result = _score_case(family, family["labels"], case, "aliases",
                             {"contracts": {}, "aliases": {}})
        self.assertFalse(result[0])
        self.assertEqual(result[5], "unassessable_control")

    def test_final_cli_requires_unlock_and_remains_disabled(self):
        import hashlib
        from benchmarks.adaptation.protocol import FINAL_UNLOCK_CONFIRM, MANIFEST, main
        with self.assertRaises(SystemExit) as error:
            with redirect_stderr(StringIO()):
                main(["--split", "final"])
        self.assertEqual(error.exception.code, 2)
        with self.assertRaises(SystemExit) as error:
            with redirect_stderr(StringIO()):
                main(["--split", "final", "--unlock-final", "--confirm-final", FINAL_UNLOCK_CONFIRM,
                      "--final-version", "2.0",
                      "--manifest-sha256", "0" * 64])
        self.assertEqual(error.exception.code, 2)
        with self.assertRaises(ValueError):
            run_protocol("final")


if __name__ == "__main__":
    unittest.main()
