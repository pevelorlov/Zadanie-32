"""Поручение в чате → настоящий повторный запуск PR workflow → проверенный отчёт."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zipfile import ZipFile, BadZipFile

from code_review import MARKER, allowed_path

WORKFLOW = "ai-review.yml"
MAX_DOWNLOAD = 4_000_000
_locks_guard = threading.Lock()
_locks: set[tuple[str, int]] = set()


class ReviewError(RuntimeError):
    """Только безопасное для интерфейса сообщение, без тела HTTP-ошибки и ключей."""


def review_intent(text: str) -> dict | None:
    """Ограниченный явный intent; описания/цитаты/отрицания не запускают Actions."""
    value = text.strip()
    command = re.match(r"^/review(?:\s|$)", value, re.I)
    if not command:
        if re.match(r"^(?:(?:пожалуйста|можешь|можно|давай)\s*[, :]?\s*)?(?:сделай|сделать|проведи|провести)\b", value, re.I) and not re.search(r"ревью|анализ|проверк", value, re.I):
            return None
        if re.search(r"\bне\s+(?:провер|запуска|дела|повтор|провод)", value, re.I):
            return None
        if not re.match(r"^(?:(?:пожалуйста|можешь|можно|давай)\s*[, :]?\s*)?(?:проверь|проверить|запусти|запустить|повтори|повторить|сделай|сделать|проведи|провести|проанализируй)\b", value, re.I):
            return None
        if not re.search(r"\bPR\b|pull\s*request|пул.?реквест|ревью|github\.com/[^\s]+/pull/|повтори\s+проверку", value, re.I):
            return None
    links = re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)(?=[/\s?#.,;!)]|$)", value, re.I)
    numbers = re.findall(r"(?:\bPR\b|pull\s*request|пул.?реквест)\s*(?:№|#)?\s*(\d+)\b", value, re.I)
    if command and not numbers and not links:
        numbers = re.findall(r"^/review\s+#?(\d+)\b", value, re.I)
    targets = {(repo.lower(), int(number)) for repo, number in links}
    if len(targets) > 1 or len(set(numbers)) > 1:
        raise ReviewError("Укажите один PR для проверки.")
    if links:
        repo, number = links[0]
        if numbers and int(numbers[0]) != int(number):
            raise ReviewError("Номер PR и ссылка противоречат друг другу.")
        return {"repo": repo, "number": int(number)}
    # Не превращаем ссылку на другой домен в разрешение обращения к нему.
    if re.search(r"https?://", value, re.I):
        raise ReviewError("Нужна ссылка https://github.com/owner/repository/pull/номер.")
    return {"number": int(numbers[0]) if numbers else None, "repo": None}


def repository(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                            capture_output=True, text=True, timeout=10, check=False)
    raw = result.stdout.strip()
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?", raw)
    if result.returncode or not match:
        raise ReviewError("У выбранного проекта нет GitHub origin. Подключите нужный рабочий проект.")
    return match[1]


def credential() -> str:
    token = os.getenv("GITHUB_REVIEW_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}, timeout=15, check=False)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode == 0 and values.get("password"):
            return values["password"]
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise ReviewError("Нет локальной авторизации GitHub. Войдите через Git Credential Manager или задайте GITHUB_REVIEW_TOKEN в .env (Actions: write, Contents и Pull requests: read).")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubClient:
    def __init__(self, token=None):
        self._token = token
        self.audit: list[dict] = []

    def request(self, path, method="GET", body=None, binary=False):
        if not path.startswith("/repos/") or ".." in path:
            raise ReviewError("Некорректный путь GitHub API.")
        if self._token is None:
            self._token = credential()
        entry = {"method": method, "path": path, "status": "running",
                 "started_at": datetime.now(timezone.utc).isoformat()}
        self.audit.append(entry)
        request = Request("https://api.github.com" + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "DeepSeek-Agent-Review"}, method=method)
        try:
            try:
                response = build_opener(NoRedirect).open(request, timeout=30)
            except HTTPError as error:
                if not binary or error.code != 302:
                    raise
                location = error.headers.get("Location", "")
                url = urlsplit(location)
                if (url.scheme != "https" or url.username or not url.hostname
                        or not url.hostname.endswith((".blob.core.windows.net", ".actions.githubusercontent.com", ".githubusercontent.com"))):
                    raise ReviewError("Неожиданный адрес загрузки artifact.")
                # Ключ GitHub никогда не пересылается на хранилище artifacts.
                response = build_opener(NoRedirect).open(Request(location), timeout=30)
            with response:
                raw = response.read(MAX_DOWNLOAD + 1)
            if len(raw) > MAX_DOWNLOAD:
                raise ReviewError("Ответ GitHub превышает разрешённый размер.")
            value = raw if binary else (json.loads(raw) if raw else {})
            entry["status"] = "completed"
            return value
        except HTTPError as error:
            entry.update(status="failed", http_status=error.code)
            raise ReviewError(f"GitHub вернул HTTP {error.code}. Проверьте доступ к репозиторию и право Actions: write; повторный запуск не подтверждён.") from None
        except (URLError, TimeoutError, OSError, ValueError) as error:
            entry["status"] = "failed"
            if isinstance(error, ReviewError):
                raise
            raise ReviewError("Не удалось получить ответ GitHub. Проверьте соединение; состояние Actions доступно на GitHub.") from None

    def pages(self, path, key=None, max_pages=30):
        result = []
        for page in range(1, max_pages + 1):
            value = self.request(path + ("&" if "?" in path else "?") + urlencode({"per_page": 100, "page": page}))
            rows = value[key] if key else value
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise ReviewError("Слишком много данных GitHub; сузьте PR.")


def unpack_report(raw: bytes, head: str) -> tuple[str, dict, dict]:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if sum(e.file_size for e in entries) > MAX_DOWNLOAD or len(entries) > 10:
                raise ReviewError("Artifact превышает разрешённый размер.")
            if len({e.filename for e in entries}) != len(entries):
                raise ReviewError("Artifact содержит повторяющиеся имена.")
            # Никаких extract: читаем только три ожидаемых файла в памяти.
            report = archive.read("review.md").decode("utf-8")
            audit = json.loads(archive.read("audit.json"))
            review = json.loads(archive.read("review.json"))
    except (BadZipFile, KeyError, ValueError, UnicodeError):
        raise ReviewError("Artifact не содержит корректного отчёта ревью.") from None
    if (len(report) > 60000 or audit.get("head") != head or audit.get("status") != "completed"
            or audit.get("technical", {}).get("finish_reason") != "stop"
            or not report.startswith(MARKER) or head not in report):
        raise ReviewError("Отчёт не соответствует выбранному коммиту или не завершён.")
    return report, audit, review


class ChatReviewService:
    def __init__(self, client_factory=GitHubClient, *, poll_seconds=4, timeout=900,
                 sleep=time.sleep, clock=time.monotonic):
        self.client_factory = client_factory
        self.poll_seconds, self.timeout = poll_seconds, timeout
        self.sleep, self.clock = sleep, clock

    def run(self, root, target, previous=None, progress=lambda value: None):
        repo = repository(Path(root))
        if target.get("repo") and target["repo"].lower() != repo.lower():
            raise ReviewError("PR принадлежит другому репозиторию. Переключите рабочий проект, чтобы не смешивать контексты.")
        number = target.get("number")
        if number is None and previous and previous.get("repo", "").lower() == repo.lower():
            number = previous.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ReviewError("Укажите PR: например «Проверь PR №1» или «Сделай ревью https://github.com/owner/repo/pull/1». Для повторной проверки используется последний PR этой ветки чата.")
        key = (repo.lower(), number)
        with _locks_guard:
            if key in _locks:
                raise ReviewError("Этот PR уже проверяется в приложении. Дождитесь завершения, чтобы не запускать дубликат.")
            _locks.add(key)
        try:
            return self._run(repo, number, progress)
        finally:
            with _locks_guard:
                _locks.discard(key)

    def _run(self, repo, number, progress):
        client = self.client_factory()
        prefix = f"/repos/{repo}"
        state = {"repo": repo, "number": number, "phase": "metadata", "steps": [], "files": []}
        def emit(**values):
            state.update(values)
            progress(dict(state))
        emit()
        pr = client.request(f"{prefix}/pulls/{number}")
        if (pr.get("state") != "open" or pr.get("draft") or not pr.get("head", {}).get("repo")
                or pr["head"]["repo"]["full_name"].lower() != repo.lower()
                or pr["user"]["login"].lower() != repo.split("/")[0].lower()):
            raise ReviewError("Проверка настроена для открытых обычных PR владельца из веток того же репозитория. Fork, draft и закрытые PR не запускаются.")
        head = pr["head"]["sha"]
        emit(head=head, pr_url=f"https://github.com/{repo}/pull/{number}", phase="diff")
        files = client.pages(f"{prefix}/pulls/{number}/files")
        preview, length, public_files = [], 0, []
        for f in files:
            name = str(f["filename"])
            permitted = allowed_path(name)
            public_files.append({"path": name, "status": f.get("status"), "additions": f.get("additions", 0),
                                 "deletions": f.get("deletions", 0), "included": permitted})
            patch = f.get("patch")
            if permitted and isinstance(patch, str):
                block = f"--- {name}\n{patch}\n"
                if length + len(block) <= 60000:
                    preview.append(block)
                    length += len(block)
        emit(files=public_files, diff="\n".join(preview),
             diff_note="Предпросмотр GitHub: только разрешённые текстовые файлы, до 60000 символов; бинарные и недоступные patch не показаны. Пайплайн получает собственный Git diff.", phase="locating")
        runs = client.request(f"{prefix}/actions/workflows/{WORKFLOW}/runs?" + urlencode({"head_sha": head, "per_page": 100}))["workflow_runs"]
        runs = [r for r in runs if r.get("head_sha") == head and r.get("head_branch") == pr["head"]["ref"]
                and r.get("event") == "pull_request_target"]
        if not runs:
            raise ReviewError("Для этого коммита ещё нет PR-запуска ai-review.yml. Откройте или обновите PR при включённом workflow; затем поручение в чате сможет повторять проверку без терминала.")
        run = max(runs, key=lambda r: r["id"])
        run_id = int(run["id"])
        attempt = int(run.get("run_attempt", 1))
        emit(run_id=run_id, run_url=f"https://github.com/{repo}/actions/runs/{run_id}", attempt=attempt)
        if run["status"] == "completed":
            client.request(f"{prefix}/actions/runs/{run_id}/rerun", "POST")
            attempt += 1
            emit(phase="queued", attempt=attempt)
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            run = client.request(f"{prefix}/actions/runs/{run_id}")
            if int(run.get("run_attempt", 1)) == attempt:
                jobs = client.request(f"{prefix}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")["jobs"]
                steps = [{"name": s["name"], "status": s["status"], "conclusion": s.get("conclusion")}
                         for j in jobs for s in j.get("steps", [])]
                emit(phase=run["status"], steps=steps, conclusion=run.get("conclusion"))
                if run["status"] == "completed":
                    if run.get("conclusion") != "success":
                        raise ReviewError("GitHub Actions завершился без успеха. Подробности и ссылка на запуск показаны в карточке; успешное ревью не подтверждено.")
                    break
            self.sleep(self.poll_seconds)
        else:
            raise ReviewError("Истекло время ожидания Actions (15 минут). Запуск на GitHub не отменён; его состояние доступно по ссылке.")
        emit(phase="report")
        artifacts = client.pages(f"{prefix}/actions/runs/{run_id}/artifacts", "artifacts")
        expected = f"deepseek-review-{number}-{head}-{attempt}"
        artifact = next((a for a in artifacts if a["name"] == expected and not a.get("expired")), None)
        if artifact is None:
            raise ReviewError("Нет artifact именно этой попытки. Предыдущий отчёт не будет выдан за новый.")
        raw = client.request(f"{prefix}/actions/artifacts/{int(artifact['id'])}/zip", binary=True)
        report, audit, review = unpack_report(raw, head)
        current = client.request(f"{prefix}/pulls/{number}")
        if current["head"]["sha"] != head:
            raise ReviewError("Во время ревью PR изменился. Отчёт относится к предыдущему коммиту; повторите проверку.")
        comments = client.pages(f"{prefix}/issues/{number}/comments")
        comment = next((c for c in reversed(comments) if c.get("user", {}).get("login") == "github-actions[bot]"
                        and c.get("body", "").replace("\r\n", "\n").strip() == report.replace("\r\n", "\n").strip()), None)
        if comment is None:
            raise ReviewError("Actions успешен, но соответствующий комментарий бота не найден. Публикация не подтверждена.")
        # URL строим из проверенных числовых ID, а не из недоверенного отчёта.
        emit(phase="completed", sources=audit.get("sources", []), comment_id=int(comment["id"]),
             comment_url=f"https://github.com/{repo}/pull/{number}#issuecomment-{int(comment['id'])}",
             artifact_url=f"https://github.com/{repo}/actions/runs/{run_id}/artifacts/{int(artifact['id'])}",
             api_calls=client.audit, findings=review.get("findings", []))
        return {"state": state, "report": report, "technical": audit["technical"]}
