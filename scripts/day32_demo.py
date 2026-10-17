"""Учебные регрессии во временном Git: без push, PR и изменения данных приложения."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from code_review import run_review

BASE_CODE = '''def average(total, count):
    return total / count if count else 0


def merge_facts(existing, generated):
    locked = [fact for fact in existing if fact.get("locked")]
    return locked + generated
'''
BROKEN_CODE = '''def average(total, count):
    return total / count


def merge_facts(existing, generated):
    return generated
'''
RULES = """# Контракты учебного модуля
average(total, count): при count=0 возвращает 0. Пустой набор допустим.
merge_facts(existing, generated): ручные facts с locked=true обязательно сохраняются.
Автоматическое обновление не вправе удалить locked facts из existing.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Реальный платный DeepSeek API; иначе dry-run")
    args = parser.parse_args()
    if args.live:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        print("Реальный DeepSeek API: учебный diff и RAG отправляются по сети, возможен расход средств.", flush=True)
    with tempfile.TemporaryDirectory(prefix="day32-demo-") as temp:
        repo = Path(temp)
        def git(*command):
            return subprocess.check_output(["git", "-C", str(repo), *command], stderr=subprocess.DEVNULL).decode().strip()
        git("init")
        git("config", "user.name", "Day32 Demo")
        git("config", "user.email", "demo@example.invalid")
        (repo / "review_probe.py").write_text(BASE_CODE, encoding="utf-8")
        (repo / "docs").mkdir()
        (repo / "docs" / "CONTRACTS.md").write_text(RULES, encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "correct baseline")
        base = git("rev-parse", "HEAD")
        (repo / "review_probe.py").write_text(BROKEN_CODE, encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "two deliberate regressions")
        output = ROOT / "reports" / ("day32_demo_live" if args.live else "day32_demo_dry")
        try:
            audit = run_review(repo, base, "HEAD", output, dry_run=not args.live)
        except Exception as error:
            print(f"Demo не завершено ({type(error).__name__}); отчёт не публикуется.")
            return 1
        print(json.dumps({"status": audit["status"], "output": str(output),
                          "real_pr": False, "network_used": audit["network_used"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
