# Эксплуатация

## Локальный запуск

Для разработки используются Python 3.12 и Node.js 24. Из корня проекта в PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix miniapp ci
npm --prefix miniapp run build
.\.venv\Scripts\python.exe -m backend
```

Открой [локальный интерфейс](http://127.0.0.1:4174/). `python -m backend` включает локальный профиль и слушает только loopback. Для разработки интерфейса запусти `npm --prefix miniapp run dev` в отдельном терминале. Vite проксирует `/api` на порт 4174. Если меняешь `ALIVE_API_PORT`, задай одинаковое значение для API и Vite.

Добавь `?demo=sample` для вымышленных записей или `?demo=empty` для пустого дневника. Для проверки SQLite и PDF используй обычный локальный профиль. Тестовую базу можно изолировать через `ALIVE_DATABASE`.

## Конфигурация

Скопируй [шаблон](../.env.example) в `.env`, подставь данные своего бота и домена. Передай файл контейнерам через `--env-file`. После создания бота открой с ним личный чат и отправь `/start`, чтобы он мог отвечать и отправлять напоминания.

| Переменная | Назначение |
| --- | --- |
| `ALIVE_TELEGRAM_BOT_TOKEN` | Токен бота для API и воркера |
| `ALIVE_TELEGRAM_USER_ID` | ID профиля Telegram с доступом к дневнику |
| `ALIVE_DATABASE` | Путь к SQLite, в образе по умолчанию `/data/lfk.sqlite3` |
| `ALIVE_LOCAL_DEV` | Локальный доступ, для развёртывания используется `0` |
| `ALIVE_REMINDER_APP_URL` | Внешний HTTPS-адрес Mini App для кнопок бота |
| `ALIVE_PUBLIC_HOST` | Домен Caddy без схемы, например `alive.example.org` |
| `ALIVE_UPSTREAM` | Адрес API в сети Docker, по умолчанию `alive-app:8080` |
| `ALIVE_TIMEZONE` | Часовой пояс IANA, по умолчанию `UTC` |
| `ALIVE_MORNING_REMINDER` | Утреннее время, по умолчанию `08:00` |
| `ALIVE_EVENING_REMINDER` | Вечернее время, по умолчанию `21:00` |
| `ALIVE_DAILY_WORKOUT_GOAL` | Дневная цель ЛФК (1 или 2 занятия). Значение должно совпадать у API и воркера. По умолчанию 1 |

Времена задаются в формате `ЧЧ:ММ`, вечерний слот начинается как минимум через 15 минут после утреннего. Держи `.env`, базу и пользовательские PDF вне Git. Для файла окружения установи права `0600`.

## Развёртывание Docker

Пример для Linux с доменом и Docker. Перед запуском направь DNS на сервер и открой порты 80 и 443 для Caddy. Из корня проекта.

```sh
npm --prefix miniapp ci
npm --prefix miniapp run build
docker build -f deploy/Dockerfile -t alive-web:local .
docker network create alive-net
sudo install -d -m 0700 -o 10001 -g 10001 /srv/alive/data

docker run -d --name alive-app --network alive-net --restart unless-stopped \
  --env-file .env --env ALIVE_LOCAL_DEV=0 \
  --mount type=bind,src=/srv/alive/data,dst=/data alive-web:local

docker run --rm --network alive-net --env-file .env \
  --mount "type=bind,src=$PWD/backend/reminders.py,dst=/app/backend/reminders.py,readonly" \
  alive-web:local python -m backend.reminders --check

docker run -d --name alive-reminders --network alive-net --restart unless-stopped \
  --env-file .env --no-healthcheck \
  --mount type=bind,src=/srv/alive/data,dst=/data \
  --mount "type=bind,src=$PWD/backend/reminders.py,dst=/app/backend/reminders.py,readonly" \
  alive-web:local python -m backend.reminders

docker run -d --name alive-https --network alive-net --restart unless-stopped \
  --env ALIVE_PUBLIC_HOST=alive.example.org -p 80:80 -p 443:443 \
  --mount "type=bind,src=$PWD/deploy/Caddyfile,dst=/etc/caddy/Caddyfile,readonly" \
  --mount type=volume,src=alive-caddy-data,dst=/data \
  --mount type=volume,src=alive-caddy-config,dst=/config caddy:2
```

Подставь свой домен в команде запуска Caddy. Передавай настройки прокси через `--env`, чтобы ему не требовался доступ к токену бота.

API слушает 8080 внутри сети Docker. API и воркер работают с одним монтированием SQLite. Caddy хранит сертификаты в постоянном Docker-томе. Для обновлений используй отдельные каталоги выпусков для смонтированных файлов и версионные теги образов. Перед заменой сохраняй предыдущие контейнеры и делай резервную копию базы. На один токен Telegram запускай только один воркер.

## Проверка и диагностика

```sh
docker ps --filter name=alive- --format '{{.Names}} {{.Image}} {{.Status}}'
docker logs --tail 30 alive-reminders
docker exec alive-reminders python -m backend.reminders --check
curl -fsS -o /dev/null https://alive.example.org/
curl -sS -o /dev/null -w '%{http_code}\n' https://alive.example.org/api/state
```

Подставь свой домен. У API ожидается `healthy`, у воркера — запись `Telegram polling ready`. Запрос состояния без Telegram должен вернуть `401`. Проверка `--check` проверяет токен, личный чат и отсутствие webhook. `docker stop alive-reminders` останавливает и пинги, и обработку команд.

## Резервная копия SQLite

Копию можно сделать без остановки сервисов через SQLite Backup API. Запускай от пользователя с правом чтения базы.

```sh
umask 077
install -d -m 0700 /srv/alive/backups
backup="/srv/alive/backups/lfk-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
python3 - "$backup" <<'PY'
from contextlib import closing
import sqlite3
import sys

source = "file:/srv/alive/data/lfk.sqlite3?mode=ro"
with closing(sqlite3.connect(source, uri=True)) as current:
    with closing(sqlite3.connect(sys.argv[1])) as backup:
        current.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
PY
```

Для восстановления проверь копию отдельно, останови API и воркер, перенеси текущий файл базы и его служебные файлы в закрытое место, затем восстанови `lfk.sqlite3` с правами `0600` и UID:GID `10001:10001`. После запуска проверь доступ из Telegram. Защищай копию так же, как рабочую базу.
