# HTTP API: основные контракты

Полный каталог методов и путей генерируется из app.py в [API_REFERENCE](API_REFERENCE.md).
Этот документ объясняет тело запросов, привязку проекта и ответы основных сценариев.
Это документация существующего Flask API, а не опубликованная OpenAPI-спецификация.

## Общие правила

Запросы JSON передаются с Content-Type: application/json. Успех обычно содержит
ok:true; ошибка — ok:false и error. Некоторые ошибки дополнительно возвращают
conversation или состояние MCP. Заголовок X-Request-ID связывает HTTP-запрос с журналом.
ID сущностей — 32 hex-символа. Профиль берётся из активного профиля приложения;
произвольный profile_id в запросе не является механизмом авторизации.

GET /api/state возвращает provider capabilities, default_settings, profiles,
active_profile_id, projects, conversations, presets, active_workspace_project_id
и self_workspace_root. Ответ содержит только доступные проекты/диалоги, но
список профилей общий. Профиль переключается PATCH /api/profiles/active с
`{"profile_id":"<id>"}`. Сетевая аутентификация отсутствует.

## Проект и рабочая папка

POST /api/projects создаёт проект; для рабочего проекта передайте:

```json
{
  "name": "Мой проект",
  "create_dialog": true,
  "workspace": {"kind": "github", "source": "https://github.com/owner/repository"}
}
```

kind может быть local с абсолютным путём в source. Клонирование синхронное,
индексация фоновая. Успех 201 возвращает project и, при запросе, conversation.
Проект без workspace остаётся проектом памяти с корнем ассистента.
POST /api/workspace/select с project_id выбирает контекст профиля; null означает
«Сам ассистент». Ответ содержит project_id, name и root.

Для RAG/MCP-маршрутов UI передаёт query `workspace_project_id=<id>`; пустое
значение явно выбирает свой корень. Если параметра нет, берётся сохранённый
выбор профиля. На маршрутах конкретного диалога корень всегда определяется
project_id диалога: query его не переопределяет. Недоступный проект возвращает 404.

## Диалог и сообщение

POST /api/conversations с необязательными title/project_id создаёт JSON-диалог.
При отсутствии project_id используется текущий выбор. GET конкретного диалога
возвращает его состояние, видимую ветку и вычисляемые метрики.

```json
{
  "content": "/help Как устроен проект?",
  "settings": {},
  "preset_id": null,
  "rag": {"enabled": true, "routing_mode": "strict", "strategy": "structural", "mode": "baseline", "candidate_k": 5, "final_k": 5},
  "mcp_activity_id": "0123456789abcdef0123456789abcdef"
}
```

Тело передаётся POST /api/conversations/<id>/messages. settings обязательно
должен быть объектом; {} означает настройки по умолчанию. content — 1–50 000
символов. preset_id связывает конфигурацию с пресетом, но не заменяет settings.
automatic:true допускается только при включённой машине задач и её автоматическом
режиме; сервер сам формирует продолжение из состояния.

Успех возвращает ok и conversation. /help распознаётся как отдельный токен,
без учёта регистра; /helpful не является командой. Пустой /help локален.
Для внешнего рабочего проекта сервер переопределяет настройки поиска на
baseline/structural/strict при наличии индекса. У истории с сообщениями перенос
или копирование в другой workspace запрещены с 409.

Типовые ответы: 400 — неверные настройки/тело, 404 — отсутствует или недоступен
диалог, 409 — пауза/недопустимое состояние, 502 — ошибка генерации. Политическая
блокировка может вернуться как сохранённый ответ с technical.request_status=blocked;
одного HTTP 200 недостаточно для утверждения об успешном выполнении задачи.

## RAG без генерации

- GET /api/rag/state — job, latest_run, files, sources и project со stale/fingerprint-состоянием.
- POST /api/rag/index — fixed_chunk_size, fixed_overlap, structural_max_size,
  structural_overlap; 202 запускает job, 409 означает конфликт индексации.
- POST /api/rag/search с query/top_k — локальный поиск по двум стратегиям,
  без DeepSeek; ответ results.fixed/results.structural, run_id.
- GET /api/rag/chunks — strategy, page, page_size, source; просмотр чанков.
- GET /api/rag/evaluations — вопросы и сохранённые сравнения выбранного workspace.

Маршруты rag-compare, rag-pipeline-compare и rag-evidence-evaluate конкретного
диалога вызывают модель и могут расходовать средства; это не обычный search.
Точные имена/методы берите из генерируемого каталога.

## MCP и расписания

GET /api/mcp/servers возвращает global_enabled, workspace, executor и servers.
Каждый сервер имеет id, enabled, allowed, scope, status. POST
/api/mcp/servers/<name>/<action> принимает enable/disable/start/stop/tools.
name — project/filesystem/scheduler. tools возвращает каталог, не исполняет его.
GET /api/mcp/activity/<id> показывает только зарегистрированное выполнение;
до регистрации 404 допустим. Нет calls — нет синей MCP-панели.

POST /api/scheduler/tasks принимает title, prompt, schedule_type, run_at или
delay_minutes, interval_minutes, обязательный объект settings, необязательные
project_id/source_conversation_id и списки зависимостей. Успех 201 содержит
task и conversation. В текущей конфигурации внешние зависимости не зарегистрированы,
пустые списки — нормальный вариант. Правила времени и состояний — SCHEDULER.md.

## Память, этапы и файлы

API памяти различает user/project scope; ручные записи имеют kind/key/value.
task-memory позволяет переключить enabled, а не произвольно переписать снимок.
task-state и task-events управляют этапами по допустимым событиям. Маршруты
веток выбирают checkpoint/продолжение; не меняют стратегию истории.
Файловые результаты доступны через маршруты artifacts конкретного диалога.
Проверяйте реальные payload-поля обработчика перед написанием нового клиента:
генерируемый каталог — перечень маршрутов, не JSON Schema для всех 81 операций.
