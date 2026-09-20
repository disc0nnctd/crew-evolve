import json
import io
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from crew_evolve.app import App
from crew_evolve.server import Server
from crew_evolve.store import Store
from scripts.load_benchmark import (
    benchmark,
    percentile,
    report_failures,
    seed_store,
    synthetic_workload,
)


class LoadBenchmarkTests(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([4, 1, 3, 2], 0.50), 2)
        self.assertEqual(percentile([4, 1, 3, 2], 0.95), 4)
        self.assertEqual(percentile([], 0.95), None)

    def test_synthetic_workload_is_valid_and_has_targets(self):
        datasets = synthetic_workload(8, 3)
        self.assertEqual(len(datasets["crew"]["records"]), 8)
        self.assertEqual(len(datasets["assignments"]["records"]), 24)
        self.assertGreaterEqual(len(datasets["duties"]["records"]), 32 + 24)
        # The engine's integrity check is the same validation used by the app.
        from crew_evolve.engine import Engine
        from crew_evolve.store import DEMO_POLICY

        self.assertEqual(Engine(datasets, DEMO_POLICY, "indexed").integrity(), [])

    def test_real_loopback_http_returns_full_structured_response(self):
        with TemporaryDirectory() as directory:
            datasets = synthetic_workload(4, 2)
            store = Store(Path(directory) / "workspace.sqlite")
            seed_store(store, datasets)
            server = Server(("127.0.0.1", 0), App(store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                plan = {"action": "coverage", "duty_id": "TARGET-0000", "role": "captain"}
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/query",
                    data=json.dumps({"plan": plan}).encode(),
                    headers={"Content-Type": "application/json", "X-Workspace-Token": server.token},
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    body = json.load(response)
                self.assertEqual(body["action"], "coverage")
                self.assertEqual(body["plan"], plan)
                self.assertEqual(body["revision"], 0)
                self.assertIn("candidate_count", body["result"])
                self.assertFalse(body["metrics"]["cache_hit"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_small_benchmark_reports_cache_and_invalidation(self):
        report = benchmark(crew=8, history=2, requests=4, clients=1)
        run = report["runs"][0]
        self.assertEqual(run["rotating"]["requests"], 4)
        self.assertEqual(run["rotating"]["error_count"], 0)
        self.assertEqual(run["repeated"]["cache_hits"], 3)
        self.assertTrue(report["correctness_oracle"]["passed"])
        self.assertTrue(report["http_response_oracle"]["passed"])
        self.assertTrue(report["invalidation"]["passed"])

    def test_failure_injection_is_a_report_gate(self):
        report = benchmark(crew=4, history=1, requests=2, clients=1)
        report["runs"][0]["rotating"]["error_count"] = 1
        report["invalidation"]["passed"] = False
        failures = report_failures(report)
        self.assertTrue(any("rotating errors=1" in failure for failure in failures))
        self.assertIn("revision invalidation check failed", failures)

    def test_cli_returns_failure_for_injected_oracle_error(self):
        report = benchmark(crew=4, history=1, requests=2, clients=1)
        report["http_response_oracle"]["passed"] = False
        with TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch("scripts.load_benchmark.benchmark", return_value=report):
                from scripts.load_benchmark import main
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["--output", str(output)]), 1)
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
