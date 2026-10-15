"""Offline smoke tests using temporary databases and mocked controller calls."""
import atexit
import gc
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

TEMP = tempfile.TemporaryDirectory(prefix='mihomo-sla-test-')
def cleanup_temp():
    gc.collect()
    TEMP.cleanup()
atexit.register(cleanup_temp)
LOCAL = Path(TEMP.name)
os.environ.update({
    'SLA_DB': str(LOCAL / 'test.db'),
    'SLA_PROBE_SETTINGS_FILE': str(LOCAL / 'settings.json'),
    'SLA_PROVIDER_FILE': str(LOCAL / 'nodes.yaml'),
    'SLA_TG_STATE_DB': str(LOCAL / 'alerts.db'),
    'SLA_TG_BOT_TOKEN': '', 'SLA_TG_CHAT_ID': '', 'MIHOMO_SECRET': '',
    'SLA_PROBE_URL': 'https://www.gstatic.com/generate_204',
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app
import coverage_engine
import incident_engine
import probe_settings
import telegram_worker
import httpx
from fastapi.testclient import TestClient

class OfflineTests(unittest.TestCase):
    def setUp(self):
        app.init_db()
        incident_engine.init_schema(app.DB)
        with closing(app.connect()) as db, db:
            for table in ('nodes', 'probes', 'incidents', 'incident_states', 'monitoring_rounds'):
                db.execute('DELETE FROM ' + table)
        # No context manager: do not start the collector lifespan/background task.
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)
        self.started = datetime.now(timezone.utc)

    def tearDown(self):
        self.client.close()
        gc.collect()

    def record(self, success, seconds):
        settings = probe_settings.current_settings()
        at = (self.started + timedelta(seconds=seconds)).isoformat()
        result = ('all-nodes', 'fixture-node', 'fixture', at, success,
                  40 if success else None, None, settings['probe_url'])
        with closing(app.connect()) as db, db:
            incident_engine.record_round(db, [result], settings)

    def test_empty_dashboard_routes_are_offline(self):
        with patch.object(app.httpx, 'AsyncClient', side_effect=AssertionError('Outbound network forbidden')):
            for path in ('/api/health', '/api/meta', '/api/nodes', '/api/analytics/summary',
                         '/api/incidents/health', '/api/coverage/summary'):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get('/api/meta').json()['nodes'], 0)

    def test_three_failures_and_two_successes(self):
        self.record(0, 0)
        self.record(0, 60)
        with closing(app.connect()) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0], 0)
        self.record(0, 120)
        self.record(1, 180)
        with closing(app.connect()) as db, db:
            self.assertEqual(db.execute('SELECT status FROM incidents').fetchone()[0], 'open')
        self.record(1, 240)
        with closing(app.connect()) as db, db:
            event = db.execute('SELECT * FROM incidents').fetchone()
            self.assertEqual(event['status'], 'resolved')
            self.assertEqual(event['duration_seconds'], 240)

    def test_monitoring_gap_does_not_claim_recovery(self):
        for seconds in (0, 60, 120):
            self.record(0, seconds)
        self.record(1, 1000)
        with closing(app.connect()) as db, db:
            event = db.execute('SELECT * FROM incidents').fetchone()
            self.assertEqual(event['status'], 'interrupted')
            self.assertIsNone(event['duration_seconds'])

    def test_unobserved_time_stays_unknown(self):
        with closing(app.connect()) as db, db:
            metrics, slots = coverage_engine.node_evidence(
                db, 'all-nodes', 'fixture-node', probe_settings.current_settings()['probe_url'],
                0, 3600, [], [], [])
        self.assertEqual(metrics['unknown_seconds'], 3600)
        self.assertEqual(metrics['sampled_seconds'], 0)
        self.assertEqual(slots, [])
        self.assertEqual(coverage_engine.evidence_status(100, 0, []), 'unknown')

    def test_probe_url_rejects_local_and_nonstandard_urls(self):
        for value in ('http://example.com/', 'https://localhost/',
                      'https://127.0.0.1/', 'https://example.com:8443/'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    probe_settings._validate_url(value)
        self.assertEqual(probe_settings._validate_url('https://example.com/'),
                         'https://example.com/')

    def test_subscription_api_never_returns_node_credentials(self):
        response = httpx.Response(200, json={'providers': {'all-nodes': {
            'proxies': [{'name': 'fixture-node', 'type': 'Shadowsocks',
                         'password': 'REPLACE-ME', 'server': 'proxy.example.invalid'}]}}},
            request=httpx.Request('GET', 'http://127.0.0.1:19091/providers/proxies'))
        with patch.object(app.httpx, 'AsyncClient') as factory:
            factory.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            result = self.client.get('/api/subscription/nodes')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['nodes'], [{'name': 'fixture-node', 'type': 'Shadowsocks'}])

    def test_invalid_subscription_does_not_attempt_download(self):
        with patch.object(app.httpx, 'AsyncClient', side_effect=AssertionError('Outbound network forbidden')):
            response = self.client.post('/api/subscription/import',
                                        json={'url': 'https://127.0.0.1/private'})
        self.assertEqual(response.status_code, 400)

    def test_telegram_resolved_event_keeps_notification_order(self):
        self.assertEqual(telegram_worker.pending_for_event({'status': 'resolved'}),
                         ('down', 'resolved'))

if __name__ == '__main__':
    unittest.main()
