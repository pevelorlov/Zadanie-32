# Установка и настройки

## Окружение

Текущая поставка ориентирована на Windows и PowerShell. Нужны Python с venv,
Node.js/npm для Filesystem MCP и Git для веток и подключения GitHub.
Зависимости Python заданы requirements.txt, Node — package.json/package-lock.json.
Точной закреплённой версии Python в проекте нет; соответствие установленному
окружению проверяется тестами. Часть Python-зависимостей задана диапазонами,
поэтому новый install не гарантирует побайтово идентичное окружение.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
```

Создайте .env по образцу .env.example и укажите собственный DEEPSEEK_API_KEY.
Не помещайте ключ в документацию, репозиторий или чат. Запустите run.bat.
Он использует Python из .venv; автоматической установки зависимостей в bat нет.
main.py выбирает свободный порт 5000–5100 на 127.0.0.1 и открывает браузер.
Порт 5031 в демонстрации — адрес запущенного экземпляра, не постоянный контракт.
debug выключен; HTTP-запросы обслуживаются в потоках.

## Переменные окружения

| Переменная | Значение по умолчанию в коде | Назначение |
| --- | --- | --- |
| DEEPSEEK_API_KEY | Нет | Ключ генеративного провайдера |
| DEEPSEEK_MODEL | deepseek-v4-flash | Начальная модель UI; неподдерживаемое значение заменяется на flash |
| DEEPSEEK_LOG_LEVEL | INFO | Уровень журналов |
| WHISPER_AUTOSTART | true | Отключается значениями 0/false/no |
| WHISPER_SERVER_PATH | tools/whisper/bin/whisper-server.exe | Локальный whisper.cpp сервер |
| WHISPER_MODEL_PATH | models/ggml-large-v3-turbo.bin | Локальная модель распознавания |
| WHISPER_FFMPEG_DIR | tools/ffmpeg/bin | Каталог FFmpeg |
| WHISPER_PORT | 8091 | Локальный порт Whisper |
| WHISPER_LANGUAGE | ru | Язык распознавания |

DEEPSEEK_PROJECT_ROOT и DEEPSEEK_SCHEDULER_DB задаются менеджерами дочерним
MCP-процессам: это корень выбранного проекта и путь к scheduler SQLite.
Их не нужно использовать для переключения проекта в UI.

## Настройки запроса

Источник — AgentSettings и PROVIDER_CAPABILITIES в agent.py. Приложение допускает
deepseek-v4-flash и deepseek-v4-pro; в коде для обеих записано окно 1 000 000
токенов. Это локальная конфигурация интерфейса, не проверка актуального каталога
или доступности моделей в аккаунте DeepSeek.

| Поле | Начальное значение | Проверка приложения |
| --- | --- | --- |
| system_prompt | «Ты полезный и внимательный ассистент.» | Непустой, до 20 000 символов |
| temperature | 1 | 0–2 |
| top_p | 1 | 0–1 |
| reasoning_enabled | false | Булево |
| reasoning_effort | high | low/high/max |
| max_tokens | null | При указании 1–65 536 |
| stop | [] | До 16 строк по 500 символов |
| response_format | text | text/json_object |
| logprobs | false | Булево |
| top_logprobs | null | 0–20, только вместе с logprobs |

seed, frequency_penalty и presence_penalty не предлагаются. SDK использует
https://api.deepseek.com, timeout 180 секунд и max_retries=1. Вспомогательные
операции используют свои параметры, а не всегда выбранный пользовательский
пресет. Пресет хранит роль и настройки; профиль хранит предпочтения человека.
Снимок фактически применённых настроек сохраняется у сообщения.

## Локальные модели

Поиск использует intfloat/multilingual-e5-small на CPU; rerank —
cross-encoder/mmarco-mMiniLMv2-L12-H384-v1. При первом отсутствии кэша может
потребоваться скачивание весов. После загрузки документы обрабатываются локально.
Это не локальная модель ответов. Голосовой ввод требует отдельной установки
Whisper/FFmpeg (setup_voice.ps1); отсутствие голосового сервиса не запрещает
текстовый чат. Инструкции диагностики — OPERATIONS.md.
