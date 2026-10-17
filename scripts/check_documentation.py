"""Проверка ссылок текущих docs, покрытия RAG и соответствия API-каталога AST."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from developer_help import ProjectDocumentation


def main():
    current = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    errors = []
    for path in current:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("# "):
            errors.append(f"Missing title: {path.name}")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = unquote(target.strip("<>" ).split("#", 1)[0])
            if not target or re.match(r"[a-z]+://", target):
                continue
            if not (path.parent / target).exists():
                errors.append(f"Broken link: {path.relative_to(ROOT)} -> {target}")
    sources = ProjectDocumentation(ROOT, ROOT / "rag_documents").sources()
    if set(current) != set(sources):
        errors.append("Current Markdown set differs from own RAG sources")
    if any("archive" in p.relative_to(ROOT).parts for p in sources):
        errors.append("Archive leaked into current RAG")
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    expected = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and isinstance(d.func.value, ast.Name) and d.func.value.id == "flask_app"
                        and d.func.attr in {"get", "post", "put", "patch", "delete"}
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    expected.add((d.func.attr.upper(), d.args[0].value, node.name))
    catalog = (ROOT / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")
    actual = set(re.findall(r"\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)` \| `([^`]+)` \|", catalog))
    if actual != expected:
        errors.append(f"API catalog drift: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    print(f"Current Markdown: {len(current)}; RAG sources: {len(sources)}; API routes: {len(expected)}")
    for error in errors:
        print(error)
    print("Documentation OK" if not errors else "Documentation FAILED")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
