"""End-to-end HTTP contract: validation, persistence, concurrency and downloads."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from workbench.server import Handler

RECORD = {
    'customer_id': 'harbor', 'customer_name': 'Harbor Labs (synthetic)',
    'integration': 'CRM sandbox webhook', 'technical_owner': 'tech@example.test',
    'data_access_owner': 'data@example.test', 'launch_owner': 'launch@example.test',
    'acceptance_criteria': 'Sandbox webhook reconciles 10 synthetic records with zero missing IDs.'
}


class OnboardingAPITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.httpd = HTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.onboarding_db = Path(self.tmp.name) / 'state.sqlite3'
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(2)

    def request(self, path, method='GET', body=None, raw=None, headers=None):
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            content = response.read().decode()
            return response.status, response.headers, json.loads(content) if 'application/json' in response.headers.get('Content-Type', '') else content

    def import_record(self, record=None, revision=0):
        return self.request('/api/onboarding/import', 'POST',
                            {'format': 'json', 'text': json.dumps([record or RECORD]), 'revision': revision})

    def test_browser_surface_and_security_headers(self):
        status, headers, text = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('<title>', text)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.request('/app.js')[0], 200)
        self.assertEqual(self.request('/../server.py')[0], 404)

    def test_preview_correct_import_duplicate_edit_reload_export(self):
        invalid = {**RECORD, 'technical_owner': ''}
        status, _, result = self.request('/api/onboarding/preview', 'POST', {'format': 'json', 'text': json.dumps([invalid])})
        self.assertEqual(status, 200)
        self.assertTrue(any(i['field'] == 'technical_owner' for i in result['issues']))
        self.assertEqual(self.import_record(invalid)[0], 422)
        self.assertEqual(self.request('/api/onboarding')[2]['tasks'], [])
        status, _, state = self.import_record()
        self.assertEqual(status, 201)
        self.assertEqual(len(state['tasks']), 5)
        self.assertTrue(any(t['blocked_reasons'] for t in state['tasks']))
        status, _, duplicate = self.import_record(revision=state['revision'])
        self.assertEqual(status, 200)
        self.assertEqual(duplicate['revision'], state['revision'])
        self.assertEqual(len(duplicate['tasks']), 5)
        task = state['tasks'][0]
        status, _, state = self.request(f"/api/onboarding/tasks/{task['id']}", 'PATCH',
            {'revision': state['revision'], 'changes': {'title': 'Reviewed scope', 'status': 'in_progress'}})
        self.assertEqual(status, 200)
        self.assertEqual(state['tasks'][0]['title'], 'Reviewed scope')
        self.assertEqual(self.request('/api/onboarding')[2], state)
        self.assertTrue(state['activity'])
        status, headers, exported = self.request('/api/onboarding/export?format=json')
        self.assertEqual(status, 200)
        self.assertEqual(len(exported['tasks']), 5)
        self.assertIn('attachment;', headers['Content-Disposition'])
        status, _, csv_text = self.request('/api/onboarding/export?format=csv')
        self.assertEqual(status, 200)
        from workbench.onboarding import parse_plan
        self.assertEqual(parse_plan(csv_text, 'csv'), exported['tasks'])

    def test_conflicts_stale_versions_and_invalid_types(self):
        _, _, state = self.import_record()
        conflict = {**RECORD, 'customer_name': 'Different'}
        self.assertEqual(self.import_record(conflict, state['revision'])[0], 422)
        task = state['tasks'][0]
        self.assertEqual(self.request(f"/api/onboarding/tasks/{task['id']}", 'PATCH',
            {'revision': 0, 'changes': {'status': 'in_progress'}})[0], 409)
        for body in ([], None, {'format': [], 'text': '[]'}, {'format': 'json', 'text': [], 'unknown': 1}):
            self.assertIn(self.request('/api/onboarding/preview', 'POST', raw=json.dumps(body).encode())[0], (400, 422))
        self.assertEqual(self.request('/api/onboarding/import', 'POST',
            {'format': 'json', 'text': json.dumps([RECORD]), 'revision': True})[0], 422)
        self.assertEqual(len(self.request('/api/onboarding')[2]['tasks']), 5)

    def test_malformed_json_does_not_start_default_invoice_run(self):
        self.assertEqual(self.request('/runs', 'POST', raw=b'{bad')[0], 400)
        self.assertEqual(self.request('/runs', 'POST', raw=b'[]')[0], 400)
        self.assertEqual(self.request('/runs', 'POST', raw=b'{"scenario":"a","scenario":"b"}')[0], 400)
        self.assertEqual(self.request('/runs', 'POST', raw=b'[' * 1500 + b']' * 1500)[0], 400)

    def test_oversized_bodies_and_bad_approval_types_are_explicit(self):
        import http.client
        # The server can reject the declared size before accepting the payload.
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=3)
        connection.putrequest('POST', '/api/onboarding/preview')
        connection.putheader('Content-Type', 'application/json')
        connection.putheader('Content-Length', '1048577')
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        connection.close()
        status, _, run = self.request('/runs', 'POST', {'scenario': 'vendor_payments_v1'})
        self.assertEqual(status, 201)
        pending = next(d for d in run['decisions'] if d['decision'] == 'needs_approval')
        path = f"/runs/{run['run_id']}/approve"
        status, _, error = self.request(path, 'POST', {
            'invoice_id': pending['invoice']['invoice_id'], 'approver': 'maria',
            'reason': 'synthetic test', 'approve': 'false'})
        self.assertEqual(status, 422)
        self.assertIn('boolean', error['error'])

    def test_cross_origin_and_host_are_rejected(self):
        self.assertEqual(self.request('/api/onboarding/preview', 'POST',
            {'format': 'json', 'text': '[]'}, headers={'Origin': 'https://untrusted.example'})[0], 403)
        self.assertEqual(self.request('/api/onboarding', headers={'Host': 'untrusted.example'})[0], 403)
        self.assertEqual(self.request('/api/onboarding')[2]['revision'], 0)
