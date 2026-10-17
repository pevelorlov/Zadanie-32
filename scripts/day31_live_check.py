"""Явная живая проверка дня 31 через запущенный Flask и DeepSeek API (платные запросы)."""
import argparse
import json
from pathlib import Path
import sys
from contextlib import nullcontext

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5031")
    parser.add_argument("--in-process", action="store_true", help="Вызвать тот же Flask API без отдельного HTTP-сервера")
    parser.add_argument("--conversation-id", help="Продолжить существующий демонстрационный диалог")
    parser.add_argument("--question", help="Выполнить один заданный вопрос вместо полного набора")
    args = parser.parse_args()
    if args.in_process:
        from app import create_app
        client_context = nullcontext(create_app().test_client())
    else:
        client_context = httpx.Client(base_url=args.base_url, timeout=240)
    with client_context as client:
        def post(path, payload):
            response = client.post(path, json=payload)
            data = response.get_json() if args.in_process else response.json()
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {data.get('error')}")
            if not data.get("ok"):
                raise RuntimeError(data.get("error", "Request failed"))
            return data

        post("/api/mcp-control/enable", {})
        conversation = {"id": args.conversation_id} if args.conversation_id else post(
            "/api/conversations", {"title": "День 31 · демонстрация /help"})["conversation"]
        questions = [
            "/help",
            "/help Объясни структуру собственного проекта: где находятся HTTP API, провайдер модели, RAG и JSON-хранилище?",
            "/help Какая текущая Git-ветка и коммит? Перечисли основные файлы проекта по свежим данным MCP.",
            "/help Как отправить сообщение через HTTP API? Какая версия схемы JSON-диалога, как связаны сообщения и где хранятся чанки RAG?",
        ]
        if args.question:
            questions = [args.question]
        results = []
        target = ROOT / "artifacts" / "day31_live_results.json"
        if args.conversation_id and target.exists():
            previous = json.loads(target.read_text(encoding="utf-8"))
            if previous.get("conversation_id") == args.conversation_id:
                results = previous.get("results", [])
        for question in questions:
            payload = post(f"/api/conversations/{conversation['id']}/messages", {
                "content": question, "settings": {"temperature": 0.2, "max_tokens": 1800},
            })
            answer = payload["conversation"]["messages"][-1]
            results.append({"question": question, "answer": answer})
            technical = answer["technical"]
            if question != "/help":
                audit = technical.get("mcp_tool_calls", [])
                assert len(audit) == 2 and all(not item.get("is_error") for item in audit), audit
                assert technical.get("rag", {}).get("chunks"), "RAG did not supply documentation"
            output = {"conversation_id": conversation["id"], "transport": "Flask test_client + live DeepSeek" if args.in_process else args.base_url, "results": results}
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"question": question, "status": technical.get("request_status"),
                              "tokens": technical.get("usage", {}).get("total_tokens"),
                              "sources": [c["source"] for c in technical.get("rag", {}).get("chunks", [])]}, ensure_ascii=False), flush=True)
        print(f"Saved: {target}", flush=True)


if __name__ == "__main__":
    main()
