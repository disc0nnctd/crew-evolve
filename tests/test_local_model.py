import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from crew_evolve.local_model import LocalModel, ModelError


class KeywordEncoder:
    """Tiny deterministic encoder used only to test decision boundaries."""

    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        result = []
        for text in texts:
            value = str(text).casefold()
            if "roster" in value:
                result.append([0.0, 1.0, 0.0, 0.0])
            elif "summary" in value or "aggregate" in value:
                result.append([0.0, 0.0, 1.0, 0.0])
            elif "cover" in value or "eligible" in value or "crew for" in value:
                result.append([1.0, 0.0, 0.0, 0.0])
            elif "badge" in value or "employee number" in value or "crew_id" in value:
                result.append([1.0, 0.0, 0.0, 0.0])
            elif "person" in value or "full name" in value or "name" in value:
                result.append([0.0, 1.0, 0.0, 0.0])
            elif "home station" in value or "base" in value:
                result.append([0.0, 0.0, 1.0, 0.0])
            elif "can work" in value or "available" in value:
                result.append([0.0, 0.0, 0.0, 1.0])
            else:
                result.append([0.0, 0.0, 0.0, 0.0])
        return result


class FlatEncoder:
    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        return [[1.0, 1.0] for _ in texts]


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "duties": ["D-100", "D-101"],
            "roles": ["captain", "first_officer"],
            "approved_examples": [
                {"template": "Find eligible crew for {duty} as {role}", "action": "coverage"},
                {"template": "Show the duty-by-duty roster", "action": "roster"},
                {"template": "Give an aggregate summary", "action": "summary"},
            ],
        }

    def test_model_is_opt_in_and_missing_selection_is_meaningful(self):
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=None)
            self.assertFalse(model.configured)
            with self.assertRaisesRegex(ModelError, "CREW_LOCAL_MODEL=minilm"):
                model.route("Show a summary", self.context)

    def test_route_uses_exact_workspace_targets(self):
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=KeywordEncoder())
        result = model.route("Who could cover D-100 as captain?", self.context)
        self.assertEqual(result["action"], "coverage")
        self.assertEqual(result["duty_id"], "D-100")
        self.assertEqual(result["role"], "captain")
        self.assertTrue(result["evidence"]["inference"])
        self.assertIn("calibration", result["evidence"])

    def test_evidence_reports_custom_model_configuration(self):
        with patch.dict(os.environ, {"CREW_LOCAL_MODEL": "minilm"}, clear=False):
            model = LocalModel(encoder=KeywordEncoder(), model_name="crew-local-test", revision="test-revision")
        result = model.route("Who could cover D-100 as captain?", self.context)
        evidence = result["evidence"]
        self.assertEqual(evidence["model"], "crew-local-test")
        self.assertEqual(evidence["model_id"], "crew-local-test")
        self.assertEqual(evidence["revision"], "test-revision")
        self.assertIn("crew-local-test", evidence["source"])

    def test_concurrent_first_load_constructs_one_encoder(self):
        calls = []
        calls_lock = threading.Lock()

        class ConstructedEncoder:
            def __init__(self, *args, **kwargs):
                with calls_lock:
                    calls.append((args, kwargs))
                time.sleep(0.03)

        fake_sentence_transformers = SimpleNamespace(SentenceTransformer=ConstructedEncoder)
        with patch.dict(os.environ, {"CREW_LOCAL_MODEL": "minilm"}, clear=False), \
             patch.dict(sys.modules, {"sentence_transformers": fake_sentence_transformers}):
            model = LocalModel()
            with ThreadPoolExecutor(max_workers=8) as pool:
                loaded = list(pool.map(lambda _: model._load_encoder(), range(8)))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(item is loaded[0] for item in loaded))
        self.assertTrue(calls[0][1]["local_files_only"])

    def test_route_accepts_application_context_shape(self):
        context = {
            "duties": [{"duty_id": "D-100"}],
            "roles": ["captain"],
            "approved_workflows": [["Find eligible crew for {duty} as {role}", "coverage"]],
        }
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=KeywordEncoder())
        result = model.route("Who could cover D-100 as captain?", context)
        self.assertEqual((result["action"], result["duty_id"], result["role"]),
                         ("coverage", "D-100", "captain"))

    def test_route_abstains_on_unknown_target_before_model_inference(self):
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=KeywordEncoder())
        result = model.route("Who could cover D-999 as captain?", self.context)
        self.assertEqual(result["action"], "clarify")
        self.assertEqual(result["reason"], "unknown duty ID")
        self.assertFalse(result["evidence"]["inference"])

    def test_route_abstains_when_same_action_examples_are_tied(self):
        context = {
            "duties": ["D-100"], "roles": [],
            "approved_examples": [
                {"template": "Show the roster", "action": "roster"},
                {"template": "List the roster", "action": "roster"},
            ],
        }
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=FlatEncoder())
        result = model.route("Show the roster", context)
        self.assertEqual(result["action"], "clarify")
        self.assertEqual(result["reason"], "ambiguous nearest examples")
        self.assertTrue(result["evidence"]["inference"])

    def test_mapping_returns_ranked_candidates_and_never_inverts_availability(self):
        pending = {
            "headers": ["Badge", "Person", "Home station", "Unavailable"],
            "rows": [{"Badge": "C-01", "Person": "Asha", "Home station": "BOM", "Unavailable": "yes"}],
        }
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=KeywordEncoder())
        result = model.mapping(pending, ["crew_id", "name", "base", "available"])
        self.assertEqual(result["mapping"].get("Badge"), "crew_id")
        self.assertEqual(result["mapping"].get("Person"), "name")
        self.assertEqual(result["mapping"].get("Home station"), "base")
        self.assertNotIn("Unavailable", result["mapping"])
        self.assertTrue(any("inversion" in item for item in result["uncertainties"]))
        self.assertTrue(result["evidence"]["inference"])

    def test_policy_requests_manual_rule(self):
        with patch.dict(os.environ, {}, clear=True):
            model = LocalModel(encoder=KeywordEncoder())
        result = model.policy("Make rest safer", {"min_rest_hours": 10})
        self.assertIn("manual", result["question"].casefold())
        self.assertNotIn("policy", result)
        self.assertTrue(result["evidence"]["abstained"])

    @unittest.skipUnless(os.environ.get("CREW_LOCAL_MODEL_REAL_TEST") == "1",
                         "set CREW_LOCAL_MODEL_REAL_TEST=1 for the cached-model check")
    def test_cached_model_real_check(self):
        with patch.dict(os.environ, {"CREW_LOCAL_MODEL": "minilm"}, clear=False):
            model = LocalModel()
        result = model.route("How many crew and duties are in the workspace?", self.context)
        self.assertIn(result["action"], {"summary", "clarify"})
        self.assertTrue(result["evidence"]["local_files_only"])


if __name__ == "__main__":
    unittest.main()
