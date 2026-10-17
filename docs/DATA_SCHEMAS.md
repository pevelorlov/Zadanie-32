# Схемы данных ассистента

## JSON-диалоги: schema_version 3

Источник схемы — storage.py: JsonStorage.create_conversation и методы нормализации.
Хранилище — data/conversations/<id>.json. id — 32 hex-символа.
Поля верхнего уровня: schema_version, id, title, created_at, updated_at,
project_id (или null), owner_profile_id, messages, context_management, summaries,
facts, fact_revisions, task_state, task_memory, task_memory_revisions,
task_handoffs и artifacts. Старые линейные диалоги получают parent_id при чтении.

## Сообщения и ветвление

Сообщение обмена user/assistant содержит id, exchange_id, role, content,
created_at, parent_id и technical. Служебный role=event может не иметь exchange_id и technical. User также содержит author_profile_id,
assistant — reasoning_content. exchange_id связывает вопрос с ответом.
parent_id задаёт дерево. context_management.active_leaf_id выбирает активный
путь; pending_branch_from_id задаёт точку следующего продолжения.

technical.request_status: pending перед запросом, completed при успехе, failed
при ошибке; blocked при блокировке контроллером; local для служебных ответов без модели. Ошибочные запросы
исключаются из будущего контекста. technical.settings — снимок AgentSettings,
configuration_source — происхождение настроек. usage учитывает input_tokens,
output_tokens, total_tokens, cached_input_tokens, uncached_input_tokens,
reasoning_tokens. Токены summary/facts учитываются отдельно от обычного диалога.

У /help technical.developer_help равен true. technical.rag содержит run_id,
strategy и компактные метаданные chunks без полного текста. technical.mcp_tool_calls
содержит name, server, arguments, is_error и result реальных вызовов.

## Стратегии контекста и память

context_management.mode: full, summary, sliding или facts. Ветвление работает
поверх каждой стратегии. summaries хранят неизменяемые версии сводки,
active_summary_id выбирает текущую. Для sliding_window_exchanges и
facts_window_exchanges допустимы 1–50. Facts с locked=true сохраняются при
автоматическом обновлении. task_memory независима от машины задач; см. MEMORY_ARCHITECTURE.md.
task_state и handoff обслуживают планирование, выполнение, проверку и завершение;
справочная команда /help не изменяет этапы.

## Профили, проекты и прочие JSON

data/profiles.json — профили пользователей и активный профиль;
data/projects/<id>.json — проекты долговременной памяти, участники и инструкции.
Проект может содержать workspace: kind, root, url (GitHub), downloaded_at.
Он выбирает рабочую папку, RAG и MCP всех его диалогов; project_id связывает
чат с этим проектом. Подробнее — WORKSPACES.md.
data/presets.json — настройки моделей; data/invariants.json — инварианты.
data/mcp_control.json и data/task_control.json — постоянные общие выключатели.
Форматы нормализуют storage.py, memory_manager.py, presets.py, invariants.py
и mcp_control.py. JSON записывается атомарной заменой временного файла.

## Scheduler SQLite: data/scheduler.sqlite3

Точная схема — scheduler.py: SchedulerRepository._initialize.
scheduled_tasks: id, title, prompt, schedule_type (once/interval), run_at,
interval_seconds, next_run_at, status (enabled/paused/completed/missed), running,
owner_profile_id, conversation_id, source_conversation_id, project_id,
mcp_servers_json, allowed_tools_json, settings_json, last_run_at, created_at,
updated_at. scheduled_task_runs ссылается на task_id и хранит отдельные запуски.
SQLite использует WAL и внешние ключи; удаление задания каскадно удаляет запуски.

Данные пользователя, ключи и содержимое реальных диалогов не являются
документацией и не включаются в проектный RAG.

## Рабочие проекты

data/workspace_selection.json хранит project_id|null для каждого профиля.
data/workspaces/<project_id>/ содержит documents, rag_index.sqlite3 и
rag_evaluations.json. GitHub-клоны находятся в workspaces/repositories.
technical.workspace ответа содержит project_id, root и name.


## Разрешения MCP

`data/mcp_server_control.json`: `{ "project": true, "filesystem": true, "scheduler": true }`.
Булевы разрешения типов серверов общие для всех профилей/проектов; сохраняются атомарно.
Отсутствующий файл разрешает все типы, повреждённый файл запрещает их.
`data/mcp_control.json` сохраняет общий выключатель с приоритетом над индивидуальными.
Снятие общего запрета не изменяет индивидуальные разрешения. См. MCP_MANAGEMENT.md.


## Объекты JSON подробнее

| Объект | Поля и правила |
| --- | --- |
| Профили (schema_version 2) | active_profile_id, profiles; у профиля id/name/is_default/preferences/custom_instructions/settings/manual_memory/learned_memory/extraction_revisions/даты |
| Проект | id/name/description/owner_profile_id/participant_profile_ids/settings/manual_memory/learned_memory/extraction_revisions; workspace необязателен |
| Запись памяти | id/scope/kind/key/value/source/locked/confidence/review_status/status/даты и ссылки происхождения |
| Контекст | mode, active_leaf_id, pending_branch_from_id, active_summary_id, окна и параметры summary |
| Summary | id/content/supersedes_summary_id/source_exchange_ids/source_message_ids/covered_exchange_ids/technical |
| Sticky Fact | id/key/value/locked и происхождение; изменения и usage в fact_revisions |
| Task State | description/stage/current_step/expected_action/plan/activity/transition_mode/stage_run_id/active_handoff_ids/required_artifacts/transition_history |
| Task Memory | enabled/goal/clarifications/constraints/terms/decisions/open_questions/revision/updated_at |
| Артефакт | id/path/filename/mime_type/size_bytes/sha256/version/active/source_message_id/stage_run_id/storage_path/created_at |
| Наборы инвариантов | data/invariants.json: schema_version=1, sets с id/name/scope/owner_id/rules/enabled и датами |

Пример описания workspace в проекте (фиктивные пути и ID):

```json
{
  "workspace": {
    "kind": "github",
    "root": "C:/Projects/agent/data/workspaces/repositories/0123456789abcdef0123456789abcdef",
    "url": "https://github.com/owner/repository",
    "downloaded_at": "2026-10-17T00:00:00+00:00"
  }
}
```

root — абсолютный локальный путь, а не URL для обращения при каждом запросе.
ID каталога клона и project_id — разные сущности. Для local url отсутствует
или пуст, root указывает на исходную папку. technical.workspace является снимком
выбранного корня конкретного ответа, не переключателем следующего запроса.

## Аудит сообщения

| technical-поле | Смысл |
| --- | --- |
| request_status | pending/completed/failed/blocked/local; не все статусы есть у каждого role |
| settings/configuration_source | Применённые параметры и происхождение пресета |
| usage | Метрики токенов провайдера; агрегируются отдельно по назначению |
| memory_context/profile_snapshot | Исторический снимок выбранной памяти/профиля |
| context_management | Реально использованная стратегия, объём истории и summary |
| task_memory/task_state/task_handoff_context | Снимки задачи на момент запроса |
| invariants/policy_audit | Активные правила и решение контроллера |
| rag | Настройки поиска, run_id, маршрутизация и компактные источники |
| mcp_tool_calls | Реальные обращения: server/name/arguments/is_error/result и служебные метрики |
| developer_help/workspace | Признак /help и привязка рабочего проекта |
| scheduled_automation | task_id/run_id/scheduled_for для отложенного запуска |

Состав technical зависит от маршрута; клиент должен обрабатывать отсутствие
необязательных полей. GET-ответ диалога дополнительно вычисляет visible_messages,
доступные события и счётчики. Не все поля представления обязаны храниться в JSON
на диске. Временная MCP-activity хранится в памяти процесса и не является
постоянной таблицей аудита; история сообщений хранит итоговые вызовы.

## RAG SQLite: отношения и ключи

| Таблица | Ключ | Содержимое |
| --- | --- | --- |
| index_runs | id | Время, модель, dimensions, settings_json, число документов/чанков, ошибки |
| documents | run_id + document_id | source/title/document_type/content_hash |
| chunks | run_id + chunk_id | strategy, document_id, source/title/section/page/order/token_count/text/text_hash |
| embeddings | run_id + chunk_id | model_name/dimensions/vector BLOB |

documents ссылается на index_runs; chunks — на documents; embeddings — на chunks.
Каскадное удаление определено в DDL. Стратегия stored chunk — fixed или structural;
combined является способом поиска поверх них. Вектор — NumPy float32-данные,
параметры/ошибки — JSON-строки. Точный DDL находится в document_index/store.py.
Индексы не содержат пользовательскую память автоматически.

## Scheduler SQLite: запуски

scheduled_task_runs имеет id, task_id, scheduled_for, started_at, completed_at,
status, result_text, error, conversation_message_id, duration_ms, unread.
Для scheduled_tasks status и running — разные поля: enabled может временно
иметь running=1. once после исполнения становится completed; failed относится
к записи запуска. Даты расписаний нормализуются к UTC+07.

## Запись и перенос

JSON сохраняется через временный файл и os.replace; RLock действует внутри
процесса. SQLite соединения включают foreign_keys, используют WAL и собственные
транзакции. Это не распределённая транзакция между JSON, SQLite и отчётами.
ID проверяются как 32 hex-символа, файловые пути артефактов нормализуются отдельно.

Экспорт имеет format=deepseek-agent-export, schema_version=1, conversation,
набор использованных пресетов и необязательный снимок project. Импорт создаёт
новые ID и владельца, не переносит всю библиотеку профилей/политику/векторный индекс.
Пути workspace и физические файлы требуют отдельного внимания при переносе.
Наличие JSON-схемы 3 не означает наличие отдельного файла JSON Schema: нормализация
реализована Python-кодом. Резервное копирование — OPERATIONS.md.
