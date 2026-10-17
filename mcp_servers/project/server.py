"""Текущая ветка и список файлов фиксированного проекта через stdio MCP."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="project-mcp", version="1.0.0")
ROOT = Path(os.environ.get("DEEPSEEK_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", "data", "logs", "models",
            "rag_documents", "workspace", "artifacts", "saved_runs", "program-map-to-delete"}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          encoding="utf-8", errors="replace", timeout=15, check=False)


@server.tool(structured_output=True)
def get_git_branch() -> dict[str, Any]:
    """Получить актуальную ветку подключённого проекта; различает detached HEAD и отсутствие Git."""
    check = git("rev-parse", "--is-inside-work-tree")
    if check.returncode:
        return {"available": False, "reason": "Папка не является доступным Git-репозиторием."}
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    commit = git("rev-parse", "--verify", "HEAD")
    return {"available": True, "branch": branch.stdout.strip() or None,
            "detached": branch.returncode != 0,
            "commit": commit.stdout.strip() if commit.returncode == 0 else None}


def visible_file(name: str) -> bool:
    path = Path(name)
    return (not any(part in EXCLUDED for part in path.parts)
            and not (path.name.startswith(".env") and path.name != ".env.example")
            and path.suffix.lower() not in {".pem", ".key", ".pfx", ".pyc"}
            and (ROOT / path).is_file() and not (ROOT / path).is_symlink()
            and (ROOT / path).resolve().is_relative_to(ROOT))


@server.tool(structured_output=True)
def list_project_files() -> dict[str, Any]:
    """Список отслеживаемых и неигнорируемых файлов проекта без данных, зависимостей и секретов."""
    result = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if result.returncode:
        files = []
        for directory, directories, names in os.walk(ROOT, followlinks=False):
            directories[:] = [name for name in directories if name not in EXCLUDED and not name.startswith(".")]
            for name in sorted(names):
                relative = (Path(directory) / name).relative_to(ROOT).as_posix()
                if visible_file(relative):
                    files.append(relative)
                if len(files) > 3000:
                    break
            if len(files) > 3000:
                break
        source = "filesystem"
    else:
        files = sorted({name for name in result.stdout.split("\0") if name and visible_file(name)})
        source = "git"
    return {"available": True, "source": source, "files": files[:3000], "total": len(files), "truncated": len(files) > 3000}


if __name__ == "__main__":
    server.run(transport="stdio")
