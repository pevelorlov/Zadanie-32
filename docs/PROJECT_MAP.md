# Карта проекта DeepSeek Agent

Полное содержание — [README документации](README.md). Поток данных подробнее —
[ARCHITECTURE](ARCHITECTURE.md), точка поставки — [CURRENT_STATE](CURRENT_STATE.md).

## Технологии и запуск

Python/Flask, HTML/CSS/JavaScript. Единственный провайдер ответов — DeepSeek API.
OpenAI-совместимый SDK не является вторым провайдером. BASE_DIR — корень исходников ассистента; workspaces.py выбирает рабочую папку,
RAG и MCP для project_id диалога. run.bat → main.py → свободный порт 5000–5100 на 127.0.0.1.

## Основные файлы

| Модуль | Ответственность |
| --- | --- |
| app.py | HTTP API, права профилей, оркестрация запросов, маршрутизация /help |
| agent.py | AgentSettings, DeepSeekProvider, сборка контекста, tools и usage |
| developer_help.py | Копии документации, справка и контекст RAG + Project MCP |
| code_review.py | CLI-ревью Git diff, отдельный BM25 RAG кода/docs и общий DeepSeekProvider |
| context_manager.py | full, summary, sliding, facts, дерево сообщений |
| storage.py | JSON schema v3, профили, проекты, атомарное сохранение |
| memory_manager.py, task_memory.py | Память пользователя/проекта и независимая память задачи |
| task_state.py, task_handoff.py, task_policy.py | Этапы задачи, handoff и проверка ограничений |
| artifacts.py | Файловые результаты, версии и SHA-256 |
| document_index/ | Загрузчики, chunking, локальные эмбеддинги, SQLite, поиск и цитаты |
| mcp_manager.py | StdioMCPManager, ProjectMCPManager, MCPManager (Filesystem), SchedulerMCPManager |
| mcp_servers/project/server.py | get_git_branch и list_project_files, только чтение |
| mcp_servers/scheduler/server.py, scheduler.py | Расписания, инструменты и фоновое выполнение |
| mcp_control.py | Общий и индивидуальные постоянные выключатели MCP, выключатель машины задач |
| presets.py, invariants.py | Настройки и инварианты |
| voice.py | Локальный Whisper, FFmpeg и транскрибация |
| main.py, logging_setup.py | Запуск, завершение, порт и маскирование журналов |
| templates/index.html, static/app.js, static/style.css | Интерфейс |
| static/markdown.js, static/vendor/ | Безопасное отображение Markdown ответов, локальная сборка markdown-it |

## Поток запросов

Обычный чат: static/app.js → POST /api/conversations/<id>/messages → app.py →
память/история/необязательный RAG → Agent.reply → DeepSeekProvider → JSON-хранилище.
Failed/pending-запросы не считаются успешным обменом. Четыре стратегии сохранены;
parent_id задаёт дерево, exchange_id связывает вопрос и ответ, active_leaf_id
выбирает путь. Locked facts не перезаписываются. Summary/facts имеют отдельный учёт.

/help — локальная справка. /help вопрос — structural top-8 и дополнительный
поиск top-4 для схемы, без дублей. Project MCP лениво запускается, получает
список инструментов и свежие get_git_branch/list_project_files. Затем модель
получает документацию, живой MCP-снимок и выбранную историю. /help не меняет
файлы и этапы задач. Права доступа и пауза учитываются до выполнения команды.

POST /api/rag/index копирует README и Markdown-руководства docs в rag_documents
и строит fixed/structural индекс. Исторические отчёты RESULTS, COMPARISON,
SCENARIOS, CONTROL_AFTER_FIX и весь docs/archive исключены. GET /api/rag/state показывает root,
source_count, stale. Контрольные вопросы — docs/day31_control_questions.json.
Полные чанки остаются в SQLite, technical истории содержит компактные ссылки,
настройки, usage и фактический аудит MCP. Текущая Git-ветка не индексируется.

## MCP и безопасность

Остались Project, Filesystem и Scheduler. Удалены внешние справочные MCP.
Project исключает из списка .env, data, модели, зависимости и рабочие результаты.
Filesystem запускается для явного экспорта; модели доступен только write_file
с принудительным путём reports внешнего корня или workspace/reports ассистента и уникальным именем. Заблокированный
экспорт откатывается. Общий и индивидуальные выключатели запрещают запуск и каждый tools/call.
Единое окно MCP рядом с настройками показывает все три сервера, область выбранного
проекта и отдельное состояние исполнителя расписаний. Контракт — MCP_MANAGEMENT.md.
GET /api/mcp/servers не запускает соединения; POST /api/mcp/servers/<name>/<action>
управляет разрешениями и соединениями. Синяя панель чата появляется только с реальным вызовом.
Scheduler запускается через main.py, хранит задания в SQLite, не догоняет
пропуски и не использует удалённые погодные зависимости. /help может быть
самодостаточным поручением о проекте. Голос остаётся локальным.

## Данные и проверка

В data: profiles.json, presets.json, projects, conversations, память,
инварианты, mcp_control.json, mcp_server_control.json, task_control.json, rag_index.sqlite3,
scheduler.sqlite3. JSON сохраняется атомарно, SQLite использует WAL.
Проекты с полем workspace связывают память и чаты с рабочей папкой, RAG и MCP.
Выбор хранится по профилю, но конкретный чат всегда использует свой project_id.
Подключение GitHub/local и изоляция описаны в WORKSPACES.md.

Схемы — DATA_SCHEMAS.md, API — API_REFERENCE.md (генератор generate_api_reference.py).
Тесты: test_app.py, test_document_index.py, test_developer_help.py,
test_mcp_servers.py, test_scheduler.py, test_workspaces.py и test_mcp_management.py. Тестовые данные — во временных каталогах,
провайдер подменяется. Реальная сеть и DeepSeek проверяются отдельно.
Проверка ссылок/RAG-корпуса/API — scripts/check_documentation.py;
хеши контрольной точки — scripts/document_snapshot.py; интерфейсная регрессия MCP —
scripts/test_mcp_activity_ui.js; Markdown — scripts/test_markdown_ui.js. Команды и backup — OPERATIONS.md.

## Подключаемые рабочие проекты

workspaces.py: WorkspaceService и Workspace, shallow clone публичного GitHub,
локальные папки, отдельные индексы/сравнения и менеджеры MCP. Новый маршрут
POST /api/workspace/select. /api/projects принимает workspace. Экспорт файлов
и планировщик учитывают выбранный проект. См. docs/WORKSPACES.md и test_workspaces.py.

## Автоматическое ревью PR

`.github/workflows/ai-review.yml` → доверенный base checkout → Git-объекты PR →
`code_review.py` → diff от merge-base и отдельный BM25 RAG кода/docs head →
DeepSeekProvider → валидация JSON/изменённых строк → Markdown, JSON и аудит →
обновление комментария PR и Actions artifact. Код PR не исполняется, данные
чата и его индекс не используются. Workflow выключен без Repository variables,
runner Windows self-hosted регистрируется отдельно. Локальная проверка —
`test_code_review.py`, учебный diff — `scripts/day32_demo.py`.
Ограничения, настройка и незавершённая проверка на реальном PR — DAY32_CODE_REVIEW.md.
