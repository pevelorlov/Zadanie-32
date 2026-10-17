"""Хеши собственной поставки без runtime/секретов. --check ничего не изменяет."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "source_snapshot.json"


def files():
    candidates = []
    for pattern in ("*.py", "*.bat", "*.ps1", "README.md", "AGENTS.md", ".env.example",
                    ".gitignore", "requirements.txt", "package.json", "package-lock.json"):
        candidates.extend(ROOT.glob(pattern))
    for directory in ("document_index", "mcp_servers", "static", "templates", "config", "scripts", "docs"):
        folder = ROOT / directory
        for path in folder.rglob("*"):
            if (path.suffix.lower() in {".py", ".js", ".css", ".html", ".md", ".json"}
                    and "__pycache__" not in path.parts and "archive" not in path.relative_to(ROOT).parts
                    and path != TARGET):
                candidates.append(path)
    return sorted({p for p in candidates if p.is_file() and not p.is_symlink()
                   and p.resolve().is_relative_to(ROOT)})


def hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()}


def git(*args):
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                            encoding="utf-8", errors="replace", timeout=15)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = hashes()
    if args.check:
        saved = json.loads(TARGET.read_text(encoding="utf-8"))["sha256"]
        changed = sorted(name for name in set(saved) | set(current) if saved.get(name) != current.get(name))
        print(json.dumps({"ok": not changed, "file_count": len(current), "changed": changed}, ensure_ascii=False))
        return 1 if changed else 0
    value = {"format": "deepseek-agent-source-snapshot-v1",
             "captured_at": datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds"),
             "timezone": "Asia/Novosibirsk", "git_head": git("rev-parse", "HEAD"),
             "git_branch_at_capture": git("symbolic-ref", "--quiet", "--short", "HEAD"),
             "working_tree_dirty": bool(git("status", "--porcelain")),
             "scope": "Application source, tests, configuration examples and current documentation; no runtime, credentials or archive.",
             "sha256": current}
    TARGET.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Snapshot: {len(current)} files -> docs/source_snapshot.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
