"""Проверки собственных MCP-серверов без внешних HTTP-запросов."""

import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from mcp.server.mcpserver.exceptions import ToolError

from mcp_manager import ProjectMCPManager, SchedulerMCPManager, StdioMCPManager






class MCPRegistrationTests(unittest.TestCase):
    def test_filesystem_write_file_creates_report_inside_allowed_workspace(self):
        project_dir = Path(__file__).resolve().parent
        server_script = project_dir / "node_modules" / "@modelcontextprotocol" / "server-filesystem" / "dist" / "index.js"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            manager = StdioMCPManager(
                command="node", args=[str(server_script), str(workspace)],
                process_name="filesystem-write-test", starting_message="start", workspace=workspace,
            )
            try:
                manager.start()
                tools = manager.list_tools()["tools"]
                self.assertIn("write_file", {tool["name"] for tool in tools})
                report_path = workspace / "reports" / "pipeline-test.md"
                report_path.parent.mkdir(parents=True)
                output = manager.call_tool("write_file", {
                    "path": str(report_path), "content": "# Отчёт\n\nТемпература: 12 °C.\n",
                })
                self.assertFalse(output["is_error"])
                self.assertEqual(report_path.read_text(encoding="utf-8"), "# Отчёт\n\nТемпература: 12 °C.\n")
            finally:
                manager.stop()

    def test_each_server_registers_expected_tools(self):
        project_dir = Path(__file__).resolve().parent
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        definitions = {
            "project": (ProjectMCPManager(project_dir), {"get_git_branch", "list_project_files"}),
            "scheduler": (SchedulerMCPManager(project_dir, Path(temporary.name) / "scheduler.sqlite3"), {
                "create_scheduled_task", "list_scheduled_tasks", "get_scheduled_task",
                "update_scheduled_task", "pause_scheduled_task", "resume_scheduled_task",
                "delete_scheduled_task", "run_scheduled_task_now", "get_scheduled_task_runs",
                "get_scheduler_summary", "get_scheduler_capabilities",
            }),
        }
        for name, (manager, expected) in definitions.items():
            with self.subTest(server=name):
                try:
                    manager.start()
                    tools = manager.list_tools()["tools"]
                    self.assertEqual({tool["name"] for tool in tools}, expected)
                    self.assertTrue(all(tool["input_schema"]["type"] == "object" for tool in tools))
                finally:
                    manager.stop()


if __name__ == "__main__":
    unittest.main()
