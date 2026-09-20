import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from crew_evolve.app import App
from crew_evolve.server import Server
from crew_evolve.store import Store


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=Server(('127.0.0.1',0),App(Store(Path(self.temp.name)/'w.sqlite')))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def get(self,path):
        with urllib.request.urlopen(self.base+path) as response:
            return json.load(response)

    def post(self,path,data,token=True,origin=None):
        headers={'Content-Type':'application/json'}
        if token: headers['X-Workspace-Token']=self.server.token
        if origin: headers['Origin']=origin
        request=urllib.request.Request(self.base+path,json.dumps(data).encode(),headers)
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_real_http_workflow(self):
        self.assertIn('token',self.get('/api/state'))
        self.post('/api/demo',{})
        result=self.post('/api/query',{'plan':{'action':'coverage','duty_id':'D-100','role':'captain'}})
        self.assertEqual(result['result']['passing'],1)
        self.assertIn('server_ms',result)

    def test_cross_origin_and_missing_token_rejected(self):
        for token,origin in [(False,None),(True,'https://untrusted.example')]:
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.post('/api/demo',{},token,origin)
            self.assertEqual(exc.exception.code,403)
            exc.exception.close()

    def test_bad_request_returns_error_without_mutation(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.post('/api/import/preview',{'kind':'crew','filename':'x.csv','content':'a,a\n1,2'})
        self.assertEqual(exc.exception.code,400)
        exc.exception.close()
        self.assertEqual(self.get('/api/state')['tables'],{})

    def test_page_assets_and_csp(self):
        for path in ('/','/app.js','/style.css'):
            with urllib.request.urlopen(self.base+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
