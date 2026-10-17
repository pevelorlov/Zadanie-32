"""Изоляция рабочих проектов, индексов, истории и файловых корней."""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from agent import Agent
from app import create_app
from developer_help import ProjectDocumentation
from document_index import RagIndexService
from mcp_manager import ProjectMCPManager
from test_app import FakeMCPManager, FakeProvider, FakeVoiceService, ProjectReportPipelineProvider
from test_document_index import FakeEmbedder, FakeReranker
from workspaces import github_url


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider = FakeProvider()
        self.rag = RagIndexService(self.root / "own-docs", self.root / "own.sqlite3", FakeEmbedder(), FakeReranker())
        self.app = create_app(self.root / "data", Agent(self.provider), FakeVoiceService(),
                              FakeMCPManager(), rag_index_service=self.rag)
        self.app.config["TESTING"] = True
        self.app.extensions["mcp_control"].set_enabled(False)
        self.app.extensions["task_control"].set_enabled(False)
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["workspace_service"].stop()
        self.temp.cleanup()

    def project(self, name):
        directory = self.root / name
        directory.mkdir()
        (directory / "README.md").write_text(f"# {name}\n\n{name} documentation unique marker.", encoding="utf-8")
        response = self.client.post("/api/projects", json={"name": name, "create_dialog": True,
            "workspace": {"kind": "local", "source": str(directory)}})
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        service = self.app.extensions["workspace_service"]
        bundle = service.get(data["project"]["id"], self.app.extensions["json_storage"].active_profile_id())
        deadline = time.monotonic() + 4
        while bundle.rag.state()["job"]["running"] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(bundle.rag.state()["job"]["phase"], "completed")
        return data, bundle

    def test_switch_changes_rag_and_filesystem_and_persists_selection(self):
        a, wa = self.project("ALPHA")
        b, wb = self.project("BETA")
        self.assertNotEqual(wa.rag.store.database_path, wb.rag.store.database_path)
        self.assertEqual(wa.filesystem.status()["workspace"], str(self.root / "ALPHA"))
        for item, word in ((a, "ALPHA"), (b, "BETA")):
            pid = item["project"]["id"]
            self.assertEqual(self.client.post("/api/workspace/select", json={"project_id": pid}).status_code, 200)
            result = self.client.post("/api/rag/search", json={"query": "documentation", "top_k": 2}).get_json()
            self.assertIn(word, result["results"]["structural"][0]["text"])
            self.assertEqual(self.client.get("/api/mcp/status").get_json()["mcp"]["workspace"], str(self.root / word))
        profile = self.app.extensions["json_storage"].active_profile_id()
        selected = json.loads((self.root / "data/workspace_selection.json").read_text())
        self.assertEqual(selected[profile], b["project"]["id"])
        self.client.post("/api/workspace/select", json={"project_id": None})
        self.assertEqual(self.client.get("/api/rag/state").get_json()["project"]["kind"], "self")

    def test_ordinary_chat_uses_its_project_even_when_another_is_selected(self):
        a, _ = self.project("ALPHA")
        b, _ = self.project("BETA")
        for item, marker in ((a, "ONLY_ALPHA_MEMORY"), (b, "ONLY_BETA_MEMORY")):
            saved = self.client.post(f"/api/projects/{item['project']['id']}/memory", json={
                "kind": "decision", "key": "project.marker", "value": marker})
            self.assertEqual(saved.status_code, 201)
        self.client.post("/api/workspace/select", json={"project_id": a["project"]["id"]})
        cid = b["conversation"]["id"]
        response = self.client.post(f"/api/conversations/{cid}/messages?workspace_project_id={a['project']['id']}",
                                    json={"content": "Explain the documentation", "settings": {}})
        self.assertEqual(response.status_code, 200, response.get_json())
        answer = response.get_json()["conversation"]["messages"][-1]
        self.assertEqual(answer["technical"]["workspace"]["project_id"], b["project"]["id"])
        calls = [messages for messages, _ in self.provider.calls if "ТЕКУЩИЙ РАБОЧИЙ ПРОЕКТ" in messages[0]["content"]]
        self.assertTrue(calls)
        self.assertIn("BETA documentation unique marker", calls[0][0]["content"])
        self.assertNotIn("ALPHA documentation", calls[0][0]["content"])
        self.assertIn("ONLY_BETA_MEMORY", calls[0][0]["content"])
        self.assertNotIn("ONLY_ALPHA_MEMORY", calls[0][0]["content"])
        moved = self.client.patch(f"/api/conversations/{cid}/project", json={"project_id": a["project"]["id"]})
        self.assertEqual(moved.status_code, 409)

    def test_other_profile_cannot_read_workspace_or_index(self):
        a, _ = self.project("PRIVATE_ALPHA")
        profile = self.client.post("/api/profiles", json={"name": "Other"}).get_json()["profile"]
        self.client.patch("/api/profiles/active", json={"profile_id": profile["id"]})
        pid = a["project"]["id"]
        self.assertEqual(self.client.post("/api/workspace/select", json={"project_id": pid}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/rag/state?workspace_project_id={pid}").status_code, 404)
        self.assertIsNone(self.client.get("/api/state").get_json()["active_workspace_project_id"])

    def test_rag_comparisons_are_isolated_between_projects(self):
        a, _ = self.project("ALPHA")
        b, _ = self.project("BETA")
        cid = a["conversation"]["id"]
        response = self.client.post(f"/api/conversations/{cid}/rag-compare", json={
            "question": "documentation", "settings": {}, "strategy": "structural", "top_k": 2})
        self.assertEqual(response.status_code, 200, response.get_json())
        own = self.client.get(f"/api/rag/evaluations?workspace_project_id={a['project']['id']}").get_json()
        other = self.client.get(f"/api/rag/evaluations?workspace_project_id={b['project']['id']}").get_json()
        self.assertEqual(len(own["items"]), 1)
        self.assertEqual(other["items"], [])

    def test_empty_project_can_start_a_task_without_a_ready_rag_index(self):
        folder = self.root / "empty-project"
        folder.mkdir()
        result = self.client.post("/api/projects", json={"name": "Empty", "create_dialog": True,
            "workspace": {"kind": "local", "source": str(folder)}}).get_json()
        cid = result["conversation"]["id"]
        normal = self.client.post(f"/api/conversations/{cid}/messages", json={"content": "Помоги начать проект", "settings": {}})
        self.assertEqual(normal.status_code, 200, normal.get_json())
        self.assertFalse(normal.get_json()["conversation"]["messages"][-1]["technical"]["rag"]["enabled"])
        help_result = self.client.post(f"/api/conversations/{cid}/messages", json={"content": "/help Что есть в проекте?", "settings": {}})
        self.assertEqual(help_result.status_code, 200)
        self.assertIn("Индекс документации проекта ещё не готов", help_result.get_json()["conversation"]["messages"][-1]["content"])

    def test_explicit_file_export_writes_only_selected_project(self):
        a, wa = self.project("ALPHA")
        b, wb = self.project("BETA")
        self.app.extensions["chat_agent"].provider = ProjectReportPipelineProvider()
        self.app.extensions["mcp_control"].set_enabled(True)
        self.client.post("/api/workspace/select", json={"project_id": a["project"]["id"]})
        cid = b["conversation"]["id"]
        response = self.client.post(f"/api/conversations/{cid}/messages", json={
            "content": "Подготовь и сохрани отчёт о проекте в файл.", "settings": {}})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(len(list((wb.root / "reports").glob("*.md"))), 1)
        self.assertFalse((wa.root / "reports").exists())
        self.assertIn("Flask и DeepSeek API", next((wb.root / "reports").glob("*.md")).read_text(encoding="utf-8"))


class WorkspaceSourceTests(unittest.TestCase):
    def test_github_url_rejects_credentials_other_hosts_and_commands(self):
        self.assertEqual(github_url("https://github.com/tt-a1i/archify.git/"), "https://github.com/tt-a1i/archify")
        for url in ("file:///repo", "git@github.com:a/b", "https://token@github.com/a/b", "https://github.com.evil/a/b",
                    "https://github.com/a/b/tree/main", "https://github.com/a/b?token=secret", "https://github.com/a/b\n--upload-pack=evil"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                github_url(url)

    def test_external_documentation_supports_rst_and_schemas_without_executing_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "README.rst").write_text("Project\n=======\nDocumentation", encoding="utf-8")
            (root / "README").write_text("Plain README without extension", encoding="utf-8")
            (root / "schemas").mkdir()
            (root / "schemas/api.yaml").write_text("openapi: 3.0.0", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs/.env").write_text("SECRET=private", encoding="utf-8")
            docs = ProjectDocumentation(root, root / "snapshot", external=True)
            docs.sync()
            self.assertTrue((root / "snapshot/README.rst.txt").is_file())
            self.assertTrue((root / "snapshot/README.txt").is_file())
            self.assertTrue((root / "snapshot/schemas/api.yaml.txt").is_file())
            self.assertFalse((root / "snapshot/docs/.env").exists())

    def test_real_project_mcp_uses_selected_repository_not_assistant_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-b", "selected-workspace", str(root)], check=True, capture_output=True)
            (root / "README.md").write_text("Selected project", encoding="utf-8")
            manager = ProjectMCPManager(root)
            try:
                manager.start()
                manager.list_tools()
                self.assertEqual(manager.call_tool("get_git_branch", {})["result"]["branch"], "selected-workspace")
                self.assertEqual(manager.call_tool("list_project_files", {})["result"]["files"], ["README.md"])
            finally:
                manager.stop()


if __name__ == "__main__":
    unittest.main()
