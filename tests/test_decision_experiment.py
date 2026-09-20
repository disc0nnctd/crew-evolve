"""Validate evaluation math and leakage boundaries without ML dependencies."""
import math
import unittest

from experiments.decision_cases import CRITERIA, HEADERS, ROUTES, build_cases, fingerprint, model_text
from experiments.decision_metrics import choose_threshold, normalize, score


def result(label, probabilities):
    return {"label": label, "probabilities": probabilities, "predicted": max(probabilities, key=probabilities.get),
            "family": label, "latency_ms": 1.0}


class DecisionExperimentTests(unittest.TestCase):
    def test_no_split_overlap_or_label_metadata_in_model_state(self):
        cases = build_cases()
        self.assertEqual(len(cases), 297)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual(fingerprint(cases), fingerprint(build_cases()))
        for task in CRITERIA:
            sets = [{case["family"] for case in cases if case["task"] == task and case["split"] == split}
                    for split in ("train", "development", "test")]
            self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        for case in cases:
            changed = dict(case, label="SECRET_LABEL", family="SECRET_FAMILY", id="SECRET_ID")
            self.assertEqual(model_text(case), model_text(changed))
            self.assertIn(case["label"], CRITERIA[case["task"]])
        for templates in (ROUTES,):
            texts = [{text for values in templates[split].values() for text in values} for split in templates]
            self.assertFalse(texts[0] & texts[1] or texts[0] & texts[2] or texts[1] & texts[2])
        aliases = [{header for splits in HEADERS.values() for header in splits[index]} for index in range(3)]
        self.assertFalse(aliases[0] & aliases[1] or aliases[0] & aliases[2] or aliases[1] & aliases[2])

    def test_probability_validation_rejects_invalid_distribution(self):
        for probs in ({"a": 0.3}, {"a": -0.1, "b": 1.1}, {"a": math.nan, "b": 1},
                      {"a": math.inf, "b": 0}, {"a": 0.1, "b": 0.1}):
            with self.assertRaises(ValueError):
                normalize(probs, ["a", "b"])
        normalized = normalize({"a": 0.3333, "b": 0.6666}, ["a", "b"])
        self.assertAlmostEqual(sum(normalized.values()), 1)

    def test_known_accuracy_brier_calibration_and_abstention(self):
        rows = [result("a", {"a": 0.8, "clarify": 0.2}), result("clarify", {"a": 0.6, "clarify": 0.4})]
        scores = score(rows, ["a", "clarify"], threshold=0.75)
        self.assertEqual(scores["accuracy"], 0.5)
        self.assertAlmostEqual(scores["brier_sum_per_case"], 0.4)
        self.assertAlmostEqual(scores["expected_calibration_error_10_bins"], 0.4)
        self.assertEqual(scores["accepted"], 1)
        self.assertEqual(scores["accepted_errors"], 0)
        self.assertEqual(scores["clarify_recall"], 0)
        self.assertIsNone(score(rows, ["a", "clarify"])["accepted_error_rate"])

    def test_threshold_needs_evidence_and_does_not_certify_test(self):
        correct = result("a", {"a": 0.8, "clarify": 0.2})
        wrong = result("clarify", {"a": 0.9, "clarify": 0.1})
        self.assertIsNone(choose_threshold([correct] * 9))
        self.assertEqual(choose_threshold([correct] * 10), 0.8)
        self.assertIsNone(choose_threshold([correct] * 10 + [wrong]))
        evaluated = score([wrong], ["a", "clarify"], threshold=0.8)
        self.assertEqual(evaluated["accepted_error_rate"], 1)
        self.assertEqual(evaluated["expected_calibration_error_10_bins"], 0.9)


if __name__ == "__main__":
    unittest.main()
