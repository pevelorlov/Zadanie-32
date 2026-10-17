# MCP текущего ассистента

- project/server.py: get_git_branch и list_project_files фиксированного рабочего корня, только чтение.
- scheduler/server.py: 11 инструментов к общему SQLite расписаний; модели разрешён более узкий набор в app.py.
- Filesystem: пакет @modelcontextprotocol/server-filesystem из node_modules приложения.
  Для своего проекта корень workspace, для внешнего — его root. Модели доступен
  только безопасный write_file при явной просьбе экспортировать отчёт.

Жизненный цикл — mcp_manager.py, постоянные запреты — mcp_control.py,
выбор корней — workspaces.py. Общее разрешение и отдельные переключатели
Project/Filesystem/Scheduler действуют на все проекты. Остановка соединения
не равна постоянному запрету. Исполнитель расписаний отделён от Scheduler MCP.

Единый пользовательский интерфейс — кнопка MCP рядом с настройками чата.
[Полное описание управления](../docs/MCP_MANAGEMENT.md),
[архитектура](../docs/ARCHITECTURE.md). Внешние справочные MCP удалены.
