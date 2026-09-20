import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from crew_evolve.app import App
from crew_evolve.model import ModelError
from crew_evolve.store import Store


class FakeModel:
    configured = True
    name = 'test-model'

    def route(self, question, context):
        return {'action': 'coverage', 'duty_id': 'D-100', 'role': 'captain', 'reply': '999 pilots are eligible'}

    def mapping(self, pending, fields):
        return {'mapping': {'made_up_column': 'crew_id'}}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'workspace.sqlite'
        self.app = App(Store(self.path))
        self.app.demo()

    def tearDown(self):
        self.temp.cleanup()

    def coverage(self):
        return self.app.execute({'action': 'coverage', 'duty_id': 'D-100', 'role': 'captain'})

    def test_known_answer_and_evidence(self):
        result = self.coverage()['result']
        self.assertEqual([c['crew_id'] for c in result['candidates'] if c['passes']], ['C-01'])
        noor = next(c for c in result['candidates'] if c['crew_id'] == 'C-02')
        self.assertTrue(any('Rest after D-099 is 3 hours' in r for r in noor['reasons']))
        self.assertTrue(all(c['sources'] for c in result['candidates']))

    def test_assignment_rechecks_and_invalidates_cache(self):
        first = self.coverage()
        self.assertFalse(first['metrics']['cache_hit'])
        self.assertTrue(self.coverage()['metrics']['cache_hit'])
        self.app.assign('C-01', 'D-100', 'captain', first['revision'])
        after = self.coverage()
        self.assertFalse(after['metrics']['cache_hit'])
        self.assertEqual(after['result']['passing'], 0)
        with self.assertRaisesRegex(ValueError, 'workspace changed'):
            self.app.assign('C-02', 'D-100', 'captain', first['revision'])

    def test_bad_assignment_cannot_be_forced(self):
        with self.assertRaisesRegex(ValueError, 'Cannot assign'):
            self.app.assign('C-02', 'D-100', 'captain', self.app.state()['revision'])
        self.assertEqual(self.app.state()['tables']['assignments']['count'], 1)

    def test_concurrent_assignment_requests_cannot_overbook(self):
        revision = self.app.state()['revision']
        def assign():
            try:
                self.app.assign('C-01', 'D-100', 'captain', revision)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: assign(), range(2)))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.app.state()['tables']['assignments']['count'], 2)

    def test_cache_does_not_share_mutable_answers(self):
        first = self.coverage()
        first['result']['candidates'][0]['name'] = 'tampered'
        self.assertNotEqual(self.coverage()['result']['candidates'][0]['name'], 'tampered')

    def test_workflow_learns_persists_generalizes_and_rolls_back(self):
        change = self.app.teach('Find someone for D-100 as captain', 'coverage')
        self.assertEqual(change['status'], 'active')
        app = App(Store(self.path))
        answer = app.ask('Find someone for D-101 as captain')
        self.assertEqual(answer['plan']['duty_id'], 'D-101')
        self.assertEqual(answer['route_source'], 'learned workflow')
        app.rollback(change['id'])
        self.assertEqual(app.state()['learned'], {})

    def test_conflicting_learning_is_rejected(self):
        self.app.teach('Show my workspace', 'summary')
        change = self.app.teach('Show my workspace', 'roster')
        self.assertEqual(change['status'], 'rejected')
        self.assertEqual(self.app.ask('Show my workspace')['action'], 'summary')

    def test_reviewed_mapping_is_learned_for_next_file(self):
        content = (Path(__file__).resolve().parent.parent / 'examples/unfamiliar-crew.csv').read_text()
        pending = self.app.preview('crew', 'new.csv', content)
        self.assertNotIn('Badge', pending['mapping'])
        mapping = {'Badge': 'crew_id', 'Person': 'name', 'Home station': 'base', 'Position': 'role', 'Fleet types': 'aircraft', 'On call': 'available'}
        self.app.accept_import(pending['id'], mapping, self.app.state()['revision'])
        next_file = self.app.preview('crew', 'next.csv', content)
        self.assertEqual(next_file['mapping'], mapping)
        # Replacing crew does not silently discard old assignments.
        self.assertTrue(self.app.state()['roster']['issues'])
        with self.assertRaisesRegex(ValueError, 'Resolve roster data issues'):
            self.coverage()

    def test_failed_import_is_atomic(self):
        p = self.app.preview('crew', 'x.csv', 'x\nhello')
        before = self.app.state()['revision']
        with self.assertRaises(ValueError):
            self.app.accept_import(p['id'], {'x':'name'}, before)
        self.assertEqual(self.app.state()['revision'], before)
        self.assertEqual(self.app.state()['tables']['crew']['count'], 6)

    def test_policy_requires_review_and_stale_proposals_fail(self):
        policy = copy.deepcopy(self.app.state()['policy'])
        policy['min_rest_hours'] = 2
        proposal = self.app.propose_policy(policy, 'Test shorter rest for a synthetic scenario')
        self.assertEqual(self.app.state()['policy']['min_rest_hours'], 10)
        self.assertTrue(proposal['report']['changes'])
        self.app.activate_policy(proposal['id'])
        self.assertEqual(self.app.state()['policy']['min_rest_hours'], 2)
        stale = self.app.propose_policy(policy | {'min_rest_hours': 12}, 'Stricter rest')
        self.app.assign('C-01', 'D-100', 'captain', self.app.state()['revision'])
        with self.assertRaisesRegex(ValueError, 'workspace changed'):
            self.app.activate_policy(stale['id'])

    def test_model_cannot_supply_answer_numbers_or_unknown_operations(self):
        self.app.model = FakeModel()
        result = self.app.ask('Who can cover D-100 as captain?')
        self.assertNotIn('999', result['reply'])
        self.assertEqual(result['result']['passing'], 1)
        self.app.model.route = lambda *args: {'action': 'assign', 'crew_id': 'C-02'}
        with self.assertRaises(ValueError):
            self.app.ask('Who can cover D-100 as captain?')

    def test_missing_targets_and_write_requests_do_not_reach_model(self):
        from unittest.mock import Mock
        self.app.model = FakeModel()
        self.app.model.route = Mock(side_effect=AssertionError('Provider must not guess missing targets or interpret writes'))
        before = self.app.state()['revision']
        for question in ('Who can cover?', 'Assign someone', 'Who can cover D-100 and D-101 as captain?',
                         "Don't show candidates; assign Asha to D-100 as captain"):
            self.assertEqual(self.app.ask(question)['action'], 'clarify', question)
        self.app.model.route.assert_not_called()
        self.assertEqual(before, self.app.state()['revision'])

    def test_model_cannot_substitute_request_target(self):
        self.app.model = FakeModel()
        self.app.model.route = lambda *args: {'action': 'coverage', 'duty_id': 'D-101', 'role': 'captain'}
        self.assertEqual(self.app.ask('Who can cover D-100 as captain?')['action'], 'clarify')

    def test_model_context_contains_only_requested_targets(self):
        from unittest.mock import Mock
        with self.app.store.connect() as db:
            data = self.app.store.datasets(db)['duties']
            data['records'][0]['required_roles'] = ['captain'] + [f'role_{i}' for i in range(5000)]
            db.execute('UPDATE datasets SET payload=? WHERE kind=?', (json.dumps(data), 'duties'))
            self.app.store.bump(db)
        self.app.model = FakeModel()
        self.app.model.route = Mock(return_value={'action': 'coverage', 'duty_id': 'D-100', 'role': 'captain'})
        self.assertEqual(self.app.ask('Who can cover D-100 as captain?')['action'], 'coverage')
        context = self.app.model.route.call_args.args[1]
        self.assertEqual(context['duties'], [{'duty_id': 'D-100'}])
        self.assertEqual(context['roles'], ['captain'])
        self.assertLess(len(json.dumps(context)), 1000)

    def test_local_model_evidence_survives_application_route(self):
        from unittest.mock import patch
        from crew_evolve.local_model import LocalModel
        from tests.test_local_model import KeywordEncoder
        self.app.teach('Find eligible crew for D-100 as captain', 'coverage')
        self.app.model = LocalModel(encoder=KeywordEncoder())
        # Exercise the provider branch separately from the reviewed phrase matcher.
        with patch('crew_evolve.app.workflows.route', return_value=None):
            answer = self.app.ask('Who could cover D-100 as captain?')
        self.assertEqual(answer['action'], 'coverage')
        self.assertTrue(answer['route_evidence']['inference'])
        self.assertTrue(answer['route_evidence']['revision'])
        self.assertEqual(answer['workflow_evidence']['source'], 'approved workflow example')
        self.assertIn('model proposal', answer['route_source'])

    def test_provider_evidence_is_bounded_and_detached(self):
        trace = {'large': ['x' * 10000] * 1000, 'nan': float('nan'), 'infinity': float('inf')}
        self.app.model = FakeModel()
        self.app.model.route = lambda *args: {'action': 'coverage', 'duty_id': 'D-100', 'role': 'captain', 'evidence': trace}
        answer = self.app.ask('Who can cover D-100 as captain?')
        self.assertLess(len(json.dumps(answer['route_evidence'])), 6000)
        self.assertIsNone(answer['route_evidence']['nan'])
        self.assertIsNone(answer['route_evidence']['infinity'])
        json.dumps(answer, allow_nan=False)
        answer['route_evidence']['large'].clear()
        self.assertEqual(len(trace['large']), 1000)

    def test_wide_provider_evidence_has_a_total_byte_limit(self):
        from crew_evolve.app import route_evidence
        trace = {str(i): [{str(j): '\\' * 10000 for j in range(24)} for _ in range(10)] for i in range(24)}
        bounded = route_evidence(trace)
        self.assertLessEqual(len(json.dumps(bounded).encode('utf-8')), 8192)
        self.assertTrue(bounded['truncated'])

    def test_reused_engine_cannot_be_mutated_through_responses(self):
        result = self.coverage()
        result['result']['duty']['aircraft'][0] = 'TAMPERED'
        state = self.app.state()
        state['duties'][0]['aircraft'][0] = 'TAMPERED'
        # A different query bypasses the prior result cache and uses the engine.
        actual = self.app.execute({'action': 'coverage', 'duty_id': 'D-101', 'role': 'captain'})
        self.assertEqual(actual['result']['duty']['aircraft'], ['A320'])

    def test_model_mapping_must_reference_real_columns(self):
        self.app.model = FakeModel()
        p = self.app.preview('crew', 'x.csv', 'Badge\n001')
        with self.assertRaisesRegex(ValueError, 'unknown columns'):
            self.app.analyze(p['id'])

    def test_model_cannot_smuggle_assertions_through_clarification(self):
        self.app.model = FakeModel()
        self.app.model.route = lambda *args: {'action': 'clarify', 'question': 'All 999 pilots are qualified.'}
        self.assertNotIn('999', self.app.ask('Help')['reply'])

    def test_demo_cannot_overwrite_data(self):
        with self.assertRaisesRegex(ValueError, 'empty workspace'):
            self.app.demo()

    def test_release_and_reassignment(self):
        rev = self.app.state()['revision']
        self.app.assign('C-01', 'D-100', 'captain', rev)
        self.app.unassign('D-100', 'captain', self.app.state()['revision'])
        self.assertEqual(self.coverage()['result']['passing'], 1)
