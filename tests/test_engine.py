import copy
import random
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from crew_evolve.engine import Engine, rolling_peak, validate_policy
from crew_evolve.optimize import benchmark, workload
from crew_evolve.store import DEMO_POLICY


class AlgorithmTests(unittest.TestCase):
    def test_full_outputs_match_across_random_workloads(self):
        for seed in range(15):
            datasets = workload(40, seed)
            self.assertEqual(Engine(datasets, DEMO_POLICY, 'reference').coverage('TARGET', 'captain'),
                             Engine(datasets, DEMO_POLICY, 'indexed').coverage('TARGET', 'captain'))

    def test_time_sweep_matches_independent_sum_on_dense_histories(self):
        rng = random.Random(828)
        origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for count in (1, 3, 10, 100, 300):
            intervals = []
            for _ in range(count):
                a = origin + timedelta(seconds=rng.randint(-1000000, 1000000))
                intervals.append((a, a + timedelta(seconds=rng.randint(60, 80000))))
            target = (origin, origin + timedelta(hours=8))
            intervals.append(target)
            self.assertAlmostEqual(rolling_peak(intervals, *target, 'reference'), rolling_peak(intervals, *target, 'indexed'), places=7)

    def test_overlap_and_future_rest_block_both_algorithms(self):
        datasets = workload(1)
        c = datasets['crew']['records'][0]
        c.update(base='DEL',role='captain',aircraft=['A320'],available=True)
        old = datasets['duties']['records'][1]
        datasets['assignments']['records'] = [{'crew_id':c['crew_id'],'duty_id':old['duty_id'],'role':'captain'}]
        old['required_roles'] = ['captain']
        for a, b, expected in [('2026-10-12T12:00:00Z','2026-10-12T18:00:00Z','Overlaps'),
                               ('2026-10-12T20:00:00Z','2026-10-13T02:00:00Z','Rest before')]:
            old.update(report_at=a,release_at=b)
            for strategy in ('reference', 'indexed'):
                result=Engine(datasets,DEMO_POLICY,strategy).check(c['crew_id'],'TARGET','captain')
                self.assertFalse(result['passes'])
                self.assertTrue(any(expected in reason for reason in result['reasons']))

    def test_policy_validates_finite_ranges(self):
        for value in (0, -1, float('nan'), float('inf'), True, '10'):
            with self.assertRaises(ValueError):
                validate_policy(DEMO_POLICY | {'min_rest_hours':value})

    def test_benchmark_gate_and_score_shape(self):
        report=benchmark((5, 15), 3)
        self.assertTrue(report['correctness_gate'])
        self.assertTrue(all(row['correctness_score']==100 for row in report['results']))
        self.assertTrue(all(row['p95_ms']>=row['p50_ms']>0 for row in report['results']))
        self.assertEqual(len(report['holdout']),3)

    def test_corrupt_fast_algorithm_fails_selection_gate(self):
        original = Engine.coverage
        def corrupted(engine, *args):
            result = original(engine, *args)
            if engine.strategy == 'indexed':
                result['passing'] += 1
            return result
        with patch.object(Engine, 'coverage', corrupted):
            report = benchmark((3,), 3)
        self.assertFalse(report['correctness_gate'])
        self.assertEqual(report['selected'], 'reference')

    def test_seven_day_window_clips_partial_history(self):
        origin = datetime(2026, 10, 10, 8, tzinfo=timezone.utc)
        intervals = [(origin-timedelta(days=7, hours=4), origin-timedelta(days=7)+timedelta(hours=4)),
                     (origin, origin+timedelta(hours=8))]
        # The older block leaves the window as the proposed duty enters it.
        for strategy in ('reference', 'indexed'):
            self.assertEqual(rolling_peak(intervals, origin, origin+timedelta(hours=8), strategy), 8)
