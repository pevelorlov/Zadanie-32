# HTTP API проекта

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
| GET | `/` | `index` |
| POST | `/api/conversations` | `create_conversation` |
| DELETE | `/api/conversations/<conversation_id>` | `delete_conversation` |
| GET | `/api/conversations/<conversation_id>` | `get_conversation` |
| PATCH | `/api/conversations/<conversation_id>` | `rename_conversation` |
| GET | `/api/conversations/<conversation_id>/artifacts/<artifact_id>` | `download_artifact` |
| POST | `/api/conversations/<conversation_id>/branches` | `create_branch` |
| PATCH | `/api/conversations/<conversation_id>/branches/active` | `change_active_branch` |
| PATCH | `/api/conversations/<conversation_id>/context` | `update_conversation_context` |
| POST | `/api/conversations/<conversation_id>/copy-to-project` | `copy_conversation_to_project` |
| GET | `/api/conversations/<conversation_id>/export` | `export_conversation` |
| POST | `/api/conversations/<conversation_id>/extract-project-memory` | `extract_project_memory_from_history` |
| POST | `/api/conversations/<conversation_id>/facts` | `create_manual_fact` |
| DELETE | `/api/conversations/<conversation_id>/facts/<fact_id>` | `remove_manual_fact` |
| PUT | `/api/conversations/<conversation_id>/facts/<fact_id>` | `update_manual_fact` |
| GET | `/api/conversations/<conversation_id>/memory-context` | `get_memory_context` |
| POST | `/api/conversations/<conversation_id>/messages` | `send_message` |
| PATCH | `/api/conversations/<conversation_id>/project` | `set_conversation_project` |
| POST | `/api/conversations/<conversation_id>/rag-compare` | `compare_rag_answers` |
| POST | `/api/conversations/<conversation_id>/rag-evidence-check` | `check_rag_evidence` |
| POST | `/api/conversations/<conversation_id>/rag-pipeline-compare` | `compare_rag_pipelines` |
| PATCH | `/api/conversations/<conversation_id>/task-memory` | `update_conversation_task_memory` |
| GET | `/api/conversations/<conversation_id>/task-state` | `get_conversation_task_state` |
| PATCH | `/api/conversations/<conversation_id>/task-state` | `update_conversation_task_state` |
| POST | `/api/conversations/<conversation_id>/task-state/events` | `apply_conversation_task_event` |
| POST | `/api/import` | `import_conversation` |
| POST | `/api/invariants` | `create_invariant_set` |
| DELETE | `/api/invariants/<set_id>` | `delete_invariant_set` |
| PUT | `/api/invariants/<set_id>` | `update_invariant_set` |
| GET | `/api/invariants/context/<conversation_id>` | `get_invariant_context` |
| GET | `/api/mcp-control` | `mcp_control_status` |
| POST | `/api/mcp-control/disable` | `mcp_control_disable` |
| POST | `/api/mcp-control/enable` | `mcp_control_enable` |
| GET | `/api/mcp/activity/<activity_id>` | `mcp_activity` |
| GET | `/api/mcp/servers` | `mcp_servers_status` |
| POST | `/api/mcp/servers/<name>/<action>` | `mcp_server_action` |
| POST | `/api/mcp/start` | `mcp_start` |
| GET | `/api/mcp/status` | `mcp_status` |
| POST | `/api/mcp/stop` | `mcp_stop` |
| GET | `/api/mcp/tools` | `mcp_tools` |
| GET | `/api/memory/policy` | `get_memory_policy` |
| GET | `/api/memory/user` | `get_user_memory` |
| POST | `/api/memory/user` | `create_user_memory` |
| DELETE | `/api/memory/user/<memory_id>` | `delete_user_memory` |
| PUT | `/api/memory/user/<memory_id>` | `update_user_memory` |
| POST | `/api/presets` | `create_preset` |
| DELETE | `/api/presets/<preset_id>` | `delete_preset` |
| PUT | `/api/presets/<preset_id>` | `update_preset` |
| GET | `/api/profiles` | `list_profiles` |
| POST | `/api/profiles` | `create_profile` |
| PATCH | `/api/profiles/<profile_id>` | `update_profile` |
| PATCH | `/api/profiles/active` | `change_active_profile` |
| GET | `/api/projects` | `list_projects` |
| POST | `/api/projects` | `create_project` |
| GET | `/api/projects/<project_id>` | `get_project` |
| PATCH | `/api/projects/<project_id>` | `update_project` |
| GET | `/api/projects/<project_id>/memory` | `get_project_memory` |
| POST | `/api/projects/<project_id>/memory` | `create_project_memory` |
| DELETE | `/api/projects/<project_id>/memory/<memory_id>` | `delete_project_memory` |
| PUT | `/api/projects/<project_id>/memory/<memory_id>` | `update_project_memory` |
| GET | `/api/rag/chunks` | `rag_chunks` |
| GET | `/api/rag/evaluations` | `rag_evaluation_state` |
| POST | `/api/rag/index` | `rag_build_index` |
| POST | `/api/rag/search` | `rag_search` |
| GET | `/api/rag/state` | `rag_state` |
| POST | `/api/scheduler/notifications/read` | `read_scheduler_notifications` |
| GET | `/api/scheduler/state` | `scheduler_state` |
| POST | `/api/scheduler/tasks` | `create_scheduled_task_api` |
| DELETE | `/api/scheduler/tasks/<task_id>` | `delete_scheduled_task_api` |
| PATCH | `/api/scheduler/tasks/<task_id>` | `update_scheduled_task_api` |
| POST | `/api/scheduler/tasks/<task_id>/<action>` | `scheduled_task_action` |
| GET | `/api/scheduler/tasks/<task_id>/runs` | `scheduled_task_runs` |
| GET | `/api/scheduler/tools` | `scheduler_tools` |
| GET | `/api/state` | `state` |
| GET | `/api/task-control` | `task_control_status` |
| POST | `/api/task-control/disable` | `task_control_disable` |
| POST | `/api/task-control/enable` | `task_control_enable` |
| POST | `/api/voice/start` | `voice_start` |
| GET | `/api/voice/status` | `voice_status` |
| POST | `/api/voice/transcribe` | `voice_transcribe` |
| POST | `/api/workspace/select` | `select_workspace` |
