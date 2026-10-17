"""Изолированный Git-репозиторий и fake-provider; сеть не используется."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent import AgentResult
from code_review import (allowed_path, changed_lines, retrieve, run_review, snapshot,
                         MAX_FILE_BYTES)


class FakeProvider:
    def __init__(self, content=None, finish="stop"):
        self.content = content
        self.finish = finish
        self.messages = None

    def complete(self, messages, settings):
        self.messages = messages
        content = self.content or json.dumps({"summary": "Есть ошибка деления.", "findings": [{
            "category": "bug", "severity": "P1", "path": "calculate.py", "side": "new",
            "line": 2, "title": "Деление на ноль", "body": "При count=0 возникает ZeroDivisionError. Проверьте count."}]})
        return AgentResult(content, "", {"finish_reason": self.finish, "usage": {"total_tokens": 12}})


class CodeReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.output = Path(self.tmp.name) / "output"
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.write("calculate.py", "def average(total, count):\n    return total / count if count else 0\n")
        self.write("docs/RULES.md", "# average total count\nПри count=0 возвращать 0; деление на ноль запрещено.\n")
        self.write("data/private.md", "DO_NOT_SEND_PRIVATE_DATA")
        self.write(".env", "DEEPSEEK_API_KEY=DO_NOT_SEND_SECRET")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.write("calculate.py", "def average(total, count):\n    return total / count\n")
        self.write("data/private.md", "DO_NOT_SEND_PRIVATE_DATA_CHANGED")
        self.git("add", ".")
        self.git("commit", "-m", "known regression")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL).decode()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_end_to_end_fake_and_private_exclusion(self):
        fake = FakeProvider()
        audit = run_review(self.root, self.base, "HEAD", self.output, provider=fake)
        self.assertEqual(audit["status"], "completed")
        self.assertFalse(audit["network_used"])
        payload = json.loads(fake.messages[1]["content"])
        self.assertIn("return total / count", payload["diff"])
        self.assertEqual(payload["changed_files"], ["calculate.py"])
        self.assertIn("data/private.md", payload["excluded_files"])
        self.assertNotIn("DO_NOT_SEND", str(fake.messages))
        self.assertEqual({c["kind"] for c in payload["rag"]}, {"code", "documentation"})
        report = (self.output / "review.md").read_text(encoding="utf-8")
        self.assertIn("Потенциальные баги", report)
        self.assertIn("Архитектурные замечания", report)
        self.assertIn("Рекомендации", report)
        self.assertIn("calculate.py:2", report)

    def test_dry_run_does_not_call_provider(self):
        fake = FakeProvider()
        audit = run_review(self.root, self.base, "HEAD", self.output, provider=fake, dry_run=True)
        self.assertIsNone(fake.messages)
        self.assertEqual(audit["status"], "prepared")
        self.assertFalse((self.output / "review.md").exists())

    def test_reject_hallucinated_location_and_incomplete_answer(self):
        for provider in (FakeProvider('{"summary":"test", "findings":[{"path":"invented.py"}]}'),
                         FakeProvider(finish="length"), FakeProvider("not json")):
            with self.subTest(provider=provider):
                with self.assertRaises(ValueError):
                    run_review(self.root, self.base, "HEAD", self.output, provider=provider)
                self.assertFalse((self.output / "review.md").exists())
                self.assertEqual(json.loads((self.output / "audit.json").read_text())["status"], "failed")

    def test_only_committed_head_is_used(self):
        self.write("calculate.py", "UNCOMMITTED_MUST_NOT_BE_SENT")
        data = snapshot(self.root, self.base, "HEAD")
        self.assertNotIn("UNCOMMITTED", data.sources["calculate.py"])
        self.assertNotIn("UNCOMMITTED", data.diff)

    def test_deleted_and_renamed_files(self):
        self.git("mv", "calculate.py", "renamed.py")
        self.git("commit", "-m", "rename")
        data = snapshot(self.root, self.base, "HEAD")
        self.assertIn("calculate.py", data.changed_files)
        self.assertIn("renamed.py", data.changed_files)
        lines = changed_lines(data.diff)
        self.assertIn(2, lines[("calculate.py", "old")])
        self.assertIn(2, lines[("renamed.py", "new")])

    def test_unicode_and_diff_header_like_source(self):
        self.write("пример.py", "# first\n# second\n")
        self.git("add", ".")
        self.git("commit", "-m", "unicode")
        data = snapshot(self.root, self.base, "HEAD")
        self.assertIn(2, changed_lines(data.diff)[("пример.py", "new")])
        diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n--- text\n+++ text\n"
        self.assertEqual(changed_lines(diff)[("a.py", "new")], {1})

    def test_allowlist_and_lexical_retrieval(self):
        for name in (".env", "data/x.md", "../outside.py", "models/x.py", "docs/archive/old.md", "credentials.py"):
            self.assertFalse(allowed_path(name))
        chunks = retrieve({"main.py": "def unique_handler(): pass", "docs/API.md": "unique_handler контракт"}, "unique_handler")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(c["score"] > 0 for c in chunks))
        self.assertTrue(allowed_path(".github/workflows/ai-review.yml"))
        self.assertTrue(allowed_path("requirements.txt"))

    def test_merge_base_excludes_base_only_changes(self):
        head = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-b", "base-advanced", self.base)
        self.write("base_only.py", "base_branch_only = True\n")
        self.git("add", ".")
        self.git("commit", "-m", "unrelated base change")
        data = snapshot(self.root, "HEAD", head)
        self.assertEqual(data.base, self.base)
        self.assertNotIn("base_only.py", data.changed_files)

    def test_symlink_is_not_read_and_large_source_is_audited(self):
        self.write("big.py", "a" * (MAX_FILE_BYTES + 1))
        self.git("add", ".")
        oid = subprocess.check_output(["git", "-C", str(self.root), "hash-object", "-w", "--stdin"],
                                      input=b"../../outside-secret").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",linked.py")
        self.git("commit", "-m", "large and symlink baseline")
        baseline = self.git("rev-parse", "HEAD").strip()
        self.write("calculate.py", "def average(total, count):\n    return 1\n")
        self.git("add", "calculate.py")
        self.git("commit", "-m", "small change")
        data = snapshot(self.root, baseline, "HEAD")
        self.assertNotIn("linked.py", data.sources)
        self.assertIn("linked.py", data.skipped_sources)
        self.assertIn("big.py", data.skipped_sources)

    def test_empty_findings_and_stale_output_cleanup(self):
        run_review(self.root, self.base, "HEAD", self.output,
                   provider=FakeProvider('{"summary":"Замечаний нет", "findings":[]}'))
        self.assertTrue((self.output / "review.md").exists())
        with self.assertRaises(ValueError):
            run_review(self.root, "no-such-ref", "HEAD", self.output, provider=FakeProvider())
        self.assertFalse((self.output / "review.md").exists())
        self.assertFalse((self.output / "audit.json").exists())

    def test_diff_limit_fails_before_provider(self):
        self.write("large.py", "x = '" + "a" * 190000 + "'\n")
        self.git("add", ".")
        self.git("commit", "-m", "too large")
        fake = FakeProvider()
        with self.assertRaises(ValueError):
            run_review(self.root, self.base, "HEAD", self.output, provider=fake)
        self.assertIsNone(fake.messages)


if __name__ == "__main__":
    unittest.main()
