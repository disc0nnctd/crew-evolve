import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from crew_evolve.model import Model, ModelError


class Endpoint(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.request_body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.authorization = self.headers.get('Authorization')
        wire = json.dumps(self.server.response_body).encode()
        self.send_response(self.server.status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(wire)))
        self.end_headers()
        self.wfile.write(wire)


class ModelTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        self.server.status_code = 200
        self.server.response_body = {'choices': [{'message': {'content': '{"action":"summary"}'}}]}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        with patch.dict('os.environ', {'CREW_MODEL_URL': f'http://127.0.0.1:{self.server.server_address[1]}/v1',
                                      'CREW_MODEL': 'synthetic-test', 'CREW_MODEL_KEY': 'synthetic-test-key'}):
            self.model = Model()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_real_transport_parses_bounded_plan(self):
        result = self.model.route('Show a summary', {'duties': [], 'roles': []})
        self.assertEqual(result, {'action': 'summary'})
        self.assertEqual(self.server.authorization, 'Bearer synthetic-test-key')
        self.assertEqual(self.server.request_body['model'], 'synthetic-test')

    def test_bad_provider_reply_is_rejected(self):
        for body in ({'choices': []}, {'choices': [{'message': {'content': 'not JSON'}}]},
                     {'choices': [{'message': {'content': '[1,2]'}}]}):
            self.server.response_body = body
            with self.assertRaises(ModelError):
                self.model.route('Question', {})

    def test_provider_error_does_not_expose_response_body(self):
        self.server.status_code = 401
        self.server.response_body = {'error': 'a provider could echo sensitive data here'}
        with self.assertRaises(ModelError) as error:
            self.model.route('Question', {})
        self.assertEqual(str(error.exception), 'Model provider returned HTTP 401.')
