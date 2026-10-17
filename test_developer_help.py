"""Проверки дня 31: явная маршрутизация, актуальность MCP и границы доступа."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import Agent
from app import create_app, strip_rag_evidence_appendix
from developer_help import ProjectDocumentation, parse_help
from mcp_servers.project import server as project_server
from test_app import FakeProvider, FakeRagIndexService, FakeVoiceService, FakeMCPManager


class ProjectToolsTests(unittest.TestCase):
    def test_archived_guide_is_preserved_but_removed_from_rag_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "README.md").write_text("Current project", encoding="utf-8")
            (root / "docs" / "archive").mkdir(parents=True)
            source = root / "docs" / "GUIDE.md"
            source.write_text("Old guide", encoding="utf-8")
            docs = ProjectDocumentation(root, root / "rag_documents")
            docs.sync()
            self.assertTrue((docs.destination / "docs/GUIDE.md").exists())
            archived = root / "docs" / "archive" / source.name
            source.rename(archived)
            docs.sync()
            self.assertEqual(archived.read_text(encoding="utf-8"), "Old guide")
            self.assertEqual(docs.sources(), [root / "README.md"])
            self.assertFalse((docs.destination / "docs/GUIDE.md").exists())
            self.assertFalse((docs.destination / "docs/archive/GUIDE.md").exists())

    def test_previous_help_source_appendix_is_not_reused_as_evidence(self):
        text = "Ответ по проекту.\n\n---\n**Источники контекста:**\n- RAG: `old.md`"
        self.assertEqual(strip_rag_evidence_appendix(text), "Ответ по проекту.")

    def test_branch_is_fresh_and_files_exclude_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-b", "day31", str(root)], check=True, capture_output=True)
            (root / "README.md").write_text("project", encoding="utf-8")
            (root / ".env").write_text("private", encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "private.json").write_text("{}")
            with mock.patch.object(project_server, "ROOT", root):
                self.assertEqual(project_server.get_git_branch()["branch"], "day31")
                subprocess.run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/next"], check=True)
                self.assertEqual(project_server.get_git_branch()["branch"], "next")
                self.assertEqual(project_server.list_project_files()["files"], ["README.md"])

    def test_detached_and_non_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(project_server, "ROOT", root):
                self.assertFalse(project_server.get_git_branch()["available"])
                subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
                subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                                "commit", "--allow-empty", "-m", "test"], capture_output=True, check=True)
                subprocess.run(["git", "-C", str(root), "checkout", "--detach"], capture_output=True, check=True)
                branch = project_server.get_git_branch()
                self.assertTrue(branch["detached"])
                self.assertIsNone(branch["branch"])
                self.assertEqual(len(branch["commit"]), 40)

    def test_docs_snapshot_preserves_paths_and_detects_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "README.md").write_text("readme")
            (root / "docs" / "nested").mkdir(parents=True)
            source = root / "docs" / "nested" / "API.md"
            source.write_text("API v1")
            (root / "docs" / "DAY25_RESULTS.md").write_text("Старый пример диалога")
            (root / ".env").write_text("secret")
            docs = ProjectDocumentation(root, root / "rag_documents")
            docs.sync()
            self.assertFalse(docs.state()["stale"])
            self.assertEqual((docs.destination / "docs/nested/API.md").read_text(), "API v1")
            self.assertFalse((docs.destination / ".env").exists())
            self.assertFalse((docs.destination / "docs/DAY25_RESULTS.md").exists())
            source.unlink()
            self.assertTrue(docs.state()["stale"])
            docs.sync()
            self.assertFalse((docs.destination / "docs/nested/API.md").exists())


class DeveloperHelpApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = FakeProvider()
        self.project = mock.Mock()
        self.project.stop.return_value = {"phase": "stopped", "connected": False}
        self.project.call_tool.side_effect = lambda name, args: {
            "tool": name, "arguments": args, "is_error": False,
            "result": {"branch": "day31"} if name == "get_git_branch" else {"files": ["app.py", "README.md"]},
        }
        self.rag = FakeRagIndexService()
        with mock.patch("app.ProjectMCPManager", return_value=self.project):
            self.app = create_app(Path(self.temp.name), Agent(self.provider), FakeVoiceService(),
                                  FakeMCPManager(), rag_index_service=self.rag)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.conversation = self.client.post("/api/conversations", json={}).get_json()["conversation"]

    def tearDown(self):
        self.temp.cleanup()

    def send(self, text):
        return self.client.post(f"/api/conversations/{self.conversation['id']}/messages", json={"content": text, "settings": {}})

    def test_bare_help_is_local_and_token_is_exact(self):
        response = self.send("/help")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/help вопрос", response.get_json()["conversation"]["messages"][-1]["content"])
        self.assertFalse(self.provider.calls)
        self.project.start.assert_not_called()
        self.assertIsNone(parse_help("/helper"))
        self.assertEqual(parse_help(" /HELP\nВопрос "), "Вопрос")

    def test_retired_external_mcp_routes_and_ui_are_removed(self):
        for path in ("/api/weather-mcp/start", "/api/orchestration-mcp/worldbank/start",
                     "/api/orchestration-mcp/mediawiki/start"):
            self.assertEqual(self.client.post(path).status_code, 404)
        page = self.client.get("/").get_data(as_text=True)
        for marker in ('id="weather-mcp-start"', 'id="mediawiki-mcp-start"', 'id="worldbank-mcp-start"'):
            self.assertNotIn(marker, page)

    def test_help_forces_rag_and_records_actual_mcp_results(self):
        response = self.send("/help Как устроен проект?")
        self.assertEqual(response.status_code, 200, response.get_json())
        message = response.get_json()["conversation"]["messages"][-1]
        self.assertEqual(len(message["technical"]["mcp_tool_calls"]), 2)
        system = self.provider.calls[-1][0][0]["content"]
        self.assertIn("day31", system)
        self.assertIn("app.py", system)
        self.assertIn("ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ RAG", system)
        self.assertNotIn("text", message["technical"]["rag"]["chunks"][0])
        self.assertIn("Источники контекста", message["content"])
        self.assertEqual(self.rag.retrieve_calls[-1][0], "Как устроен проект?")

    def test_global_mcp_disable_is_respected(self):
        self.assertEqual(self.client.post("/api/mcp-control/disable").status_code, 200)
        self.project.stop.assert_called_once()
        response = self.send("/help Какая ветка?")
        self.assertEqual(response.status_code, 200)
        self.project.start.assert_not_called()
        self.project.call_tool.assert_not_called()
        self.assertIn("MCP принудительно отключён", self.provider.calls[-1][0][0]["content"])

    def test_schema_question_includes_data_contract_beside_general_api_context(self):
        original = self.rag.retrieve("API")
        schema = {**original, "chunks": [{**original["chunks"][0], "chunk_id": "schema-chunk",
                  "source": "docs/DATA_SCHEMAS.md", "text": "parent_id задаёт дерево; exchange_id связывает обмен."}]}
        with mock.patch.object(self.rag, "retrieve", side_effect=[original, schema]):
            response = self.send("/help Какова схема диалога и связь сообщений?")
        self.assertEqual(response.status_code, 200)
        system = self.provider.calls[-1][0][0]["content"]
        self.assertIn("parent_id задаёт дерево; exchange_id связывает обмен.", system)
        chunks = response.get_json()["conversation"]["messages"][-1]["technical"]["rag"]["chunks"]
        self.assertIn("docs/DATA_SCHEMAS.md", [item["source"] for item in chunks])

    def test_mcp_failure_remains_explicit_and_provider_failure_is_persisted(self):
        self.project.start.side_effect = RuntimeError("Project MCP unavailable")
        self.assertEqual(self.send("/help Ветка?").status_code, 200)
        self.assertIn("Project MCP unavailable", self.provider.calls[-1][0][0]["content"])
        self.provider.fail = True
        response = self.send("/help Структура?")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["conversation"]["messages"][-1]["technical"]["request_status"], "failed")

    def test_missing_index_does_not_call_provider(self):
        with mock.patch.object(self.rag, "retrieve", side_effect=RuntimeError("Сначала постройте индекс документов.")):
            response = self.send("/help Структура?")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(self.provider.calls)


if __name__ == "__main__":
    unittest.main()
