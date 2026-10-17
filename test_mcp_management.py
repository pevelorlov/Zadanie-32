"""Постоянные запреты MCP и жизненный цикл без сети и реальных данных."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent import Agent
from app import create_app
from mcp_control import MCPServerControl
from test_app import FakeMCPManager, FakeProvider, FakeRagIndexService, FakeVoiceService


class MCPManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fs = FakeMCPManager()
        self.scheduler = FakeMCPManager()
        self.app = create_app(Path(self.temp.name), Agent(FakeProvider()), FakeVoiceService(), self.fs,
                              scheduler_mcp_manager=self.scheduler, rag_index_service=FakeRagIndexService())
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions['workspace_service'].stop()
        self.temp.cleanup()

    def action(self, name, action):
        return self.client.post(f'/api/mcp/servers/{name}/{action}', json={})

    def test_status_does_not_start_servers_and_includes_scopes(self):
        result = self.client.get('/api/mcp/servers').get_json()
        self.assertEqual({s['id'] for s in result['servers']}, {'project', 'filesystem', 'scheduler'})
        self.assertTrue(all(s['enabled'] and not s['status']['connected'] and s['scope'] for s in result['servers']))
        self.assertEqual(self.fs.start_calls + self.scheduler.start_calls, 0)

    def test_disable_stops_and_blocks_legacy_routes_and_persists(self):
        self.assertEqual(self.action('filesystem', 'start').status_code, 200)
        self.assertEqual(self.action('filesystem', 'tools').status_code, 200)
        self.assertEqual(self.action('filesystem', 'disable').status_code, 200)
        self.assertFalse(self.fs.running)
        self.assertEqual(self.action('filesystem', 'start').status_code, 403)
        self.assertEqual(self.action('filesystem', 'tools').status_code, 403)
        self.assertEqual(self.client.post('/api/mcp/start').status_code, 409)
        self.assertEqual(self.client.get('/api/mcp/tools').status_code, 409)
        persisted = MCPServerControl(Path(self.temp.name) / 'mcp_server_control.json')
        self.assertFalse(persisted.is_enabled('filesystem'))
        self.assertTrue(persisted.is_enabled('project'))
        self.action('filesystem', 'enable')
        self.assertFalse(self.fs.running, 'Разрешение не запускает сервер')
        self.assertTrue(persisted.is_enabled('filesystem'))

    def test_global_toggle_preserves_individual_permissions(self):
        self.action('scheduler', 'disable')
        self.client.post('/api/mcp-control/disable')
        self.assertEqual(self.action('filesystem', 'start').status_code, 403)
        self.client.post('/api/mcp-control/enable')
        states = {s['id']: s for s in self.client.get('/api/mcp/servers').get_json()['servers']}
        self.assertFalse(states['scheduler']['allowed'])
        self.assertTrue(states['filesystem']['allowed'])
        self.assertEqual(self.client.get('/api/scheduler/tools').status_code, 409)

    def test_disable_stops_all_cached_project_instances(self):
        service = self.app.extensions['workspace_service']
        a, b = FakeMCPManager(), FakeMCPManager()
        a.start(); b.start()
        service.cache['test-a'] = SimpleNamespace(project_mcp=a, filesystem=FakeMCPManager())
        service.cache['test-b'] = SimpleNamespace(project_mcp=b, filesystem=FakeMCPManager())
        self.action('project', 'disable')
        self.assertFalse(a.running or b.running)

    def test_scheduler_mcp_disable_does_not_stop_executor(self):
        executor = self.app.extensions['scheduler_service']
        with mock.patch.object(executor, 'stop') as stop:
            self.action('scheduler', 'start')
            self.action('scheduler', 'disable')
            stop.assert_not_called()
        self.assertFalse(self.scheduler.running)

    def test_invalid_server_or_action_rejected(self):
        self.assertEqual(self.action('unknown', 'start').status_code, 404)
        self.assertEqual(self.action('project', 'unknown').status_code, 404)

    def test_disabled_project_is_not_started_for_help(self):
        self.action('project', 'disable')
        conversation = self.client.post('/api/conversations', json={}).get_json()['conversation']
        manager = self.app.extensions['project_mcp_manager']
        with mock.patch.object(manager, 'start') as start, mock.patch.object(manager, 'call_tool') as call:
            result = self.client.post(f"/api/conversations/{conversation['id']}/messages", json={
                'content': '/help Какая текущая git-ветка?', 'settings': {}} )
            self.assertEqual(result.status_code, 200, result.get_json())
            start.assert_not_called(); call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
