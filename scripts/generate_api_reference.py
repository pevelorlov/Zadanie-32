"""Воспроизводимый каталог Flask-маршрутов из AST app.py, без запуска приложения."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "flask_app"
                    and decorator.args and isinstance(decorator.args[0], ast.Constant)):
                routes.append((decorator.args[0].value, decorator.func.attr.upper(), node.name))
    intro = """# HTTP API проекта

Подробные примеры тел запросов и границы доступа: [API_GUIDE](API_GUIDE.md).

## Основной контракт чата

Приложение Flask слушает локальный адрес. JSON-запросы используют Content-Type:
application/json. Успех содержит ok: true; ошибки — ok: false и error.
Права доступа к проектам и диалогам зависят от активного профиля.

POST /api/conversations создаёт диалог: {"title": "Новый диалог"}.
Ответ содержит conversation с id и сообщениями.

POST /api/conversations/<conversation_id>/messages принимает content (1–50000
символов), обязательный объект settings (допустим {}), необязательные preset_id,
rag и mcp_activity_id. Настройки
модели валидирует AgentSettings.from_dict в agent.py. Ответ: {ok, conversation}.
В conversation.messages находятся сообщения, technical с usage и снимками настроек.
Ошибка провайдера сохраняет пользовательское сообщение как failed и возвращает 502.

content: "/help" возвращает локальную справку. content: "/help вопрос" запускает
RAG по документации рабочего проекта диалога и два read-only вызова Project MCP, если он разрешён.
Поля rag обычного чата не меняют этот маршрут. technical.developer_help: true,
technical.rag содержит run_id и компактные чанки; technical.mcp_tool_calls — аудит
фактических вызовов и их результатов. Изменение файлов не выполняется.

## Рабочие проекты

POST /api/projects принимает workspace: {kind: github|local, source: URL|папка}
и create_dialog: true. Создаются отдельные проект, чат и RAG; индексация фоновая.
POST /api/workspace/select принимает project_id: id|null и сохраняет выбор профиля.
Запросы чата используют project_id самого диалога. RAG и Filesystem lifecycle
принимают workspace_project_id в query. Доступ проверяется по профилю.
В обычном чате внешнего проекта RAG включён автоматически. technical.workspace
фиксирует project_id, имя и корень. См. WORKSPACES.md.

## Управление документацией и MCP

GET /api/rag/state: файлы, sources, latest_run, job, модели и project
({root, source_count, stale}). stale сравнивает исходники документации с их копией.
POST /api/rag/index: копирует README/docs для рабочей копии и запускает индексацию;
202 с job. Параметры: fixed_chunk_size, fixed_overlap, structural_max_size,
structural_overlap. Если сборка уже идёт — 409. GET /api/rag/state показывает итог
и ошибки. Только успешно завершённый запуск становится текущим.
POST /api/mcp-control/disable запрещает все MCP и останавливает Project MCP тоже.
POST /api/mcp-control/enable снимает общий запрет, сохраняя индивидуальные.
GET /api/mcp/servers показывает все три сервера без запуска; POST
/api/mcp/servers/<name>/<action> управляет разрешениями и соединениями.
Состояние исполнителя расписаний отдельно от Scheduler MCP. См. MCP_MANAGEMENT.md.

## Полный каталог маршрутов

Таблица извлечена из декораторов app.py скриптом scripts/generate_api_reference.py.
Для контрактов остальных подсистем см. PROJECT_MAP.md и тематические документы.

| Метод | Путь | Обработчик в app.py |
| --- | --- | --- |
"""
    rows = "\n".join(f"| {method} | `{path}` | `{name}` |" for path, method, name in sorted(routes))
    (ROOT / "docs" / "API_REFERENCE.md").write_text(intro + rows + "\n", encoding="utf-8")
    print(f"HTTP routes: {len(routes)}")


if __name__ == "__main__":
    main()
