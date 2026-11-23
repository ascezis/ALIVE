# Backend

FastAPI хранит состояние ЛФК и дневник в SQLite и формирует PDF через ReportLab. Отдельный процесс `python -m backend.reminders` обрабатывает личный чат Telegram и расписание напоминаний.

- [Локальный запуск проекта](../docs/operations.md#локальный-запуск)
- [API, модель данных и импорт каталога](../docs/data.md)
- [Воркер и расписание](../docs/bot.md)
