"""Ревью из чата: fake GitHub/Actions, временные данные, без сети и DeepSeek."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile
from urllib.error import HTTPError

from agent import Agent
from app import create_app
from chat_review import (ChatReviewService, GitHubClient, ReviewError, review_intent,
                         unpack_report, _locks)
from context_manager import completed_exchanges
from test_app import FakeProvider, FakeVoiceService, FakeMCPManager, FakeRagIndexService

SHA = "a" * 40
REPORT = "<!-- deepseek-agent-review -->\n## Ревью\n" + SHA + "\nПотенциальные баги: не найдены."
TECHNICAL = {"finish_reason": "stop", "usage": {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40},
             "settings": {"model": "deepseek-v4-flash"}}


def archive(head=SHA, report=REPORT):
    stream = BytesIO()
    with ZipFile(stream, "w") as zipfile:
        zipfile.writestr("review.md", report)
        zipfile.writestr("audit.json", json.dumps({"head": head, "status": "completed", "technical": TECHNICAL,
            "sources": [{"source": "docs/API.md", "kind": "documentation", "start_line": 1, "end_line": 9, "score": 2}]}))
        zipfile.writestr("review.json", '{"summary":"OK", "findings":[]}')
    return stream.getvalue()


class FakeGitHub:
    def __init__(self, active=False):
        self.audit = []
        self.posts = []
        self.active = active
        self.changed = False
        self.bad_comment = False
        self.bad_artifact = False
        self.conclusion = "success"
        self.pr = {"state": "open", "draft": False, "user": {"login": "owner"},
                   "head": {"sha": SHA, "ref": "feature", "repo": {"full_name": "owner/repo"}}}

    def request(self, path, method="GET", body=None, binary=False):
        self.audit.append({"method": method, "path": path, "status": "completed"})
        if method == "POST":
            self.posts.append(path)
            return {}
        if "/workflows/" in path:
            return {"workflow_runs": [{"id": 4, "head_sha": SHA, "head_branch": "feature", "event": "pull_request_target",
                                      "status": "in_progress" if self.active else "completed", "run_attempt": 1}]}
        if path.endswith("/pulls/1"):
            pr = deepcopy(self.pr)
            if self.changed and self.posts:
                pr["head"]["sha"] = "b" * 40
            return pr
        if "/jobs?" in path:
            return {"jobs": [{"steps": [{"name": "Review", "status": "completed", "conclusion": "success"}]}]}
        if path.endswith("/actions/runs/4"):
            return {"run_attempt": 1 if self.active else 2, "status": "completed", "conclusion": self.conclusion}
        if path.endswith("/zip"):
            return archive()
        raise AssertionError(path)

    def pages(self, path, key=None, max_pages=30):
        if path.endswith("/files"):
            return [{"filename": "main.py", "patch": "@@ -1 +1 @@\n-a\n+b", "status": "modified"},
                    {"filename": ".env", "patch": "DO_NOT_SEND", "status": "modified"}]
        if path.endswith("/artifacts"):
            attempt = 1 if self.active or self.bad_artifact else 2
            return [{"id": 7, "name": f"deepseek-review-1-{SHA}-{attempt}"}]
        if path.endswith("/comments"):
            return [{"id": 9, "user": {"login": "other" if self.bad_comment else "github-actions[bot]"}, "body": REPORT}]
        raise AssertionError(path)


class ChatReviewTests(unittest.TestCase):
    def service(self, client):
        return ChatReviewService(lambda: client, sleep=lambda _: None, poll_seconds=0)

    def run_service(self, client, target=None, previous=None, progress=lambda _: None):
        with mock.patch("chat_review.repository", return_value="owner/repo"):
            return self.service(client).run(Path("."), target or {"number": 1}, previous=previous, progress=progress)

    def test_natural_language_and_repeat(self):
        for text in ("Проверь PR №1", "Сделай ревью PR #1", "Можешь проверить PR 1?", "/review 1",
                     "Проведи ревью https://github.com/owner/repo/pull/1"):
            with self.subTest(text=text):
                self.assertEqual(review_intent(text)["number"], 1)
        self.assertIsNone(review_intent("Что такое PR?"))
        self.assertIsNone(review_intent("Расскажи, как запустить ревью PR 1"))
        self.assertIsNone(review_intent("Не проверяй PR 1"))
        self.assertIsNone(review_intent('Напиши пример «Проверь PR 1»'))
        self.assertIsNone(review_intent("Проверь арифметику 2+2"))
        self.assertIsNone(review_intent("/help Проверь PR 1"))
        self.assertIsNone(review_intent("/reviewer 1"))
        self.assertIsNone(review_intent("Сделай commit и push"))
        self.assertIsNone(review_intent("Сделай merge PR 1"))  # merge не является запросом ревью
        self.assertIsNone(review_intent("Удалить ветку PR 1"))
        self.assertIsNone(review_intent("Проверь PR 1, но не запускай Actions"))
        self.assertIsNone(review_intent("Как проверить PR 1?"))
        self.assertIsNone(review_intent("Покажи пример команды /review 1"))
        self.assertIsNone(review_intent("Перечисли баги PR 1"))
        self.assertEqual(review_intent("Повтори проверку после исправлений")["number"], None)

    def test_ambiguous_or_foreign_url(self):
        for text in ("Проверь PR 1 и PR 2", "Проверь PR 2 https://github.com/owner/repo/pull/1",
                     "Сделай ревью https://evil.example/owner/repo/pull/1"):
            with self.assertRaises(ReviewError):
                review_intent(text)

    def test_complete_flow_reruns_only_one_permitted_endpoint(self):
        client = FakeGitHub()
        progress = []
        result = self.run_service(client, progress=lambda s: progress.append(deepcopy(s)))
        self.assertEqual(client.posts, ["/repos/owner/repo/actions/runs/4/rerun"])
        self.assertEqual(result["state"]["attempt"], 2)
        self.assertEqual(result["state"]["comment_id"], 9)
        self.assertEqual(result["state"]["phase"], "completed")
        self.assertEqual(result["technical"]["usage"]["total_tokens"], 40)
        self.assertNotIn("DO_NOT_SEND", str(progress))
        self.assertTrue(any(s.get("diff") for s in progress))
        self.assertEqual(result["state"]["sources"][0]["source"], "docs/API.md")

    def test_attach_running_job_does_not_launch_duplicate(self):
        client = FakeGitHub(active=True)
        result = self.run_service(client)
        self.assertFalse(client.posts)
        self.assertEqual(result["state"]["attempt"], 1)

    def test_old_artifact_and_unconfirmed_publication_rejected(self):
        for field in ("bad_artifact", "bad_comment", "changed"):
            client = FakeGitHub()
            setattr(client, field, True)
            with self.subTest(field=field), self.assertRaises(ReviewError):
                self.run_service(client)

    def test_failed_run_and_timeout(self):
        client = FakeGitHub()
        client.conclusion = "failure"
        with self.assertRaises(ReviewError):
            self.run_service(client)
        with mock.patch("chat_review.repository", return_value="owner/repo"):
            service = ChatReviewService(lambda: FakeGitHub(), timeout=1, clock=mock.Mock(side_effect=[0, 2]))
            with self.assertRaisesRegex(ReviewError, "время ожидания"):
                service.run(Path("."), {"number": 1})

    def test_repository_isolation_and_previous_target(self):
        with self.assertRaises(ReviewError):
            self.run_service(FakeGitHub(), {"number": 1, "repo": "other/repo"})
        with self.assertRaises(ReviewError):
            self.run_service(FakeGitHub(), {"number": None}, previous={"repo": "other/repo", "number": 1})
        result = self.run_service(FakeGitHub(), {"number": None}, previous={"repo": "owner/repo", "number": 1})
        self.assertEqual(result["state"]["number"], 1)

    def test_draft_closed_fork_not_launched(self):
        for kind in ("draft", "closed", "fork"):
            client = FakeGitHub()
            if kind == "draft": client.pr["draft"] = True
            elif kind == "closed": client.pr["state"] = "closed"
            else: client.pr["head"]["repo"]["full_name"] = "other/repo"
            with self.subTest(kind=kind), self.assertRaises(ReviewError):
                self.run_service(client)
            self.assertFalse(client.posts)

    def test_duplicate_lock_and_wrong_snapshot(self):
        _locks.add(("owner/repo", 1))
        try:
            with self.assertRaises(ReviewError): self.run_service(FakeGitHub())
        finally:
            _locks.discard(("owner/repo", 1))
        with self.assertRaises(ReviewError): unpack_report(archive(head="b" * 40), SHA)
        with self.assertRaises(ReviewError): unpack_report(b"not a zip", SHA)

    def test_does_not_accept_previous_completed_attempt_after_rerun(self):
        client = FakeGitHub()
        original = client.request
        reads = []
        def request(path, *args, **kwargs):
            if path.endswith('/actions/runs/4'):
                reads.append(path)
                if len(reads) == 1:
                    return {'run_attempt': 1, 'status': 'completed', 'conclusion': 'success'}
            return original(path, *args, **kwargs)
        client.request = request
        result = self.run_service(client)
        self.assertEqual(len(reads), 2)
        self.assertEqual(result['state']['attempt'], 2)


class GitHubTransportTests(unittest.TestCase):
    def test_no_token_in_http_error(self):
        opener = mock.Mock()
        opener.open.side_effect = HTTPError('https://api.github.com', 403, 'secret-value', {}, None)
        with mock.patch('chat_review.build_opener', return_value=opener):
            with self.assertRaises(ReviewError) as error:
                GitHubClient('secret-value').request('/repos/owner/repo/actions/runs/4/rerun', 'POST')
        self.assertNotIn('secret-value', str(error.exception))

    def test_artifact_redirect_strips_authorization(self):
        api_opener, blob_opener = mock.Mock(), mock.Mock()
        api_opener.open.side_effect = HTTPError('https://api.github.com', 302, 'redirect',
            {'Location': 'https://artifacts.blob.core.windows.net/report?sig=opaque'}, None)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'zip'
        blob_opener.open.return_value = response
        with mock.patch('chat_review.build_opener', side_effect=[api_opener, blob_opener]):
            self.assertEqual(GitHubClient('private-token').request('/repos/owner/repo/actions/artifacts/1/zip', binary=True), b'zip')
        first = api_opener.open.call_args.args[0]
        second = blob_opener.open.call_args.args[0]
        self.assertEqual(first.get_header('Authorization'), 'Bearer private-token')
        self.assertIsNone(second.get_header('Authorization'))

    def test_foreign_artifact_redirect_rejected(self):
        opener = mock.Mock()
        opener.open.side_effect = HTTPError('https://api.github.com', 302, 'redirect',
            {'Location': 'https://evil.example/report'}, None)
        with mock.patch('chat_review.build_opener', return_value=opener):
            with self.assertRaises(ReviewError):
                GitHubClient('private-token').request('/repos/owner/repo/actions/artifacts/1/zip', binary=True)
        self.assertEqual(opener.open.call_count, 1)


class FakeReviewService:
    def __init__(self):
        self.calls = []
        self.fail = False

    def run(self, root, target, previous=None, progress=lambda _: None):
        self.calls.append({"root": str(root), "target": target, "previous": previous})
        state = {"repo": "owner/repo", "number": 1, "head": SHA, "phase": "completed", "steps": [], "files": [],
                 "run_url": "https://github.com/owner/repo/actions/runs/4", "comment_url": "https://github.com/owner/repo/pull/1#issuecomment-9"}
        progress(state)
        if self.fail:
            raise ReviewError("Actions завершился ошибкой.")
        return {"state": state, "report": REPORT, "technical": deepcopy(TECHNICAL)}


class ChatReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = FakeProvider()
        self.service = FakeReviewService()
        with mock.patch("app.ProjectMCPManager"):
            self.app = create_app(Path(self.temp.name), Agent(self.provider), FakeVoiceService(), FakeMCPManager(),
                                  rag_index_service=FakeRagIndexService(), review_service=self.service)
        self.client = self.app.test_client()
        self.conv = self.client.post("/api/conversations", json={}).get_json()["conversation"]

    def send(self, text, activity=None):
        return self.client.post(f"/api/conversations/{self.conv['id']}/messages",
                                json={"content": text, "settings": {}, "mcp_activity_id": activity})

    def test_natural_request_and_repeat_are_not_normal_model_answers(self):
        response = self.send("Проверь PR №1", "a" * 32)
        self.assertEqual(response.status_code, 200)
        messages = response.get_json()["conversation"]["messages"]
        self.assertEqual(messages[-1]["technical"]["github_review"]["number"], 1)
        self.assertEqual(messages[-1]["parent_id"], messages[-2]["id"])
        self.assertEqual(messages[-1]["exchange_id"], messages[-2]["exchange_id"])
        self.assertEqual(messages[-1]["technical"]["usage"]["total_tokens"], 40)
        activity = self.client.get("/api/mcp/activity/" + "a" * 32).get_json()["activity"]
        self.assertEqual(activity["review"]["head"], SHA)
        self.assertFalse(activity["calls"])
        self.assertEqual(self.send("Повтори проверку после исправлений").status_code, 200)
        self.assertEqual(self.service.calls[-1]["previous"]["number"], 1)
        self.assertFalse(self.provider.calls)

    def test_failed_review_is_not_a_completed_exchange(self):
        self.service.fail = True
        response = self.send("Сделай ревью PR 1")
        self.assertEqual(response.status_code, 502)
        conv = response.get_json()["conversation"]
        self.assertTrue(all(m["technical"]["request_status"] == "failed" for m in conv["messages"]))
        self.assertFalse(completed_exchanges(conv["messages"]))

    def test_ambiguous_request_is_rejected_without_tools(self):
        self.assertEqual(self.send("Проверь PR 1 и PR 2").status_code, 400)
        self.assertFalse(self.service.calls)
        self.assertFalse(self.provider.calls)

    def test_other_profile_cannot_poll_activity(self):
        self.send("Проверь PR 1", "b" * 32)
        storage = self.app.extensions["json_storage"]
        with mock.patch.object(storage, "active_profile_id", return_value="other-profile"):
            self.assertEqual(self.client.get("/api/mcp/activity/" + "b" * 32).status_code, 404)
            self.assertEqual(self.send("Проверь PR 1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
