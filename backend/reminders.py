"""Run the owner's private ALIVE chat and daily reminders."""

import argparse
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import json
import logging
import os
import sqlite3
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .app import Day, WorkoutState, connect

DEFAULT_MORNING = time(8)
DEFAULT_EVENING = time(21)
WINDOW = timedelta(minutes=15)
LOG = logging.getLogger("alive.reminders")
METRICS = {"pain": "Боль", "stiffness": "Утренняя скованность", "fatigue": "Утомляемость"}
STIFFNESS_PROMPT = "Утренняя скованность. Ответь числом минут (0–1440)."
COMMANDS = {
    "start": "Открыть ALIVE", "today": "Что записано сегодня",
    "checkin": "Отметить самочувствие", "reminders": "Расписание напоминаний",
}


@dataclass(frozen=True)
class Settings:
    owner: int
    url: str
    database: str
    token: str = field(repr=False)
    evening: time = DEFAULT_EVENING
    morning: time = DEFAULT_MORNING
    zone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))

    @classmethod
    def from_environment(cls):
        owner = int(os.environ["ALIVE_TELEGRAM_USER_ID"])
        token = os.environ["ALIVE_TELEGRAM_BOT_TOKEN"]
        url = os.environ["ALIVE_REMINDER_APP_URL"]
        morning = parse_time(os.environ.get("ALIVE_MORNING_REMINDER", "08:00"))
        evening = parse_time(os.environ.get("ALIVE_EVENING_REMINDER", "21:00"))
        zone = ZoneInfo(os.environ.get("ALIVE_TIMEZONE", "UTC"))
        parsed = urlsplit(url)
        if (owner <= 0 or not token or parsed.scheme != "https" or not parsed.hostname
                or parsed.username or (
                    datetime.combine(datetime.min.date(), evening) -
                    datetime.combine(datetime.min.date(), morning)
                ) < WINDOW):
            raise ValueError("Invalid reminder configuration")
        return cls(owner, url, os.environ.get("ALIVE_DATABASE", "/data/lfk.sqlite3"), token, evening, morning, zone)


def due_slot(now, evening=DEFAULT_EVENING, morning=DEFAULT_MORNING):
    schedule = (("morning", morning), ("evening", evening))
    return next(
        (name for name, at in schedule if timedelta(0) <= now - datetime.combine(now.date(), at, now.tzinfo) < WINDOW),
        None,
    )


def did_exercise(workout):
    return workout.get("mode") == "video" or "done" in (workout.get("results") or ())


def read_diary(database, owner, date):
    table = database.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alive_workout_state'"
    ).fetchone()
    if table is None:
        return {}, "empty"
    row = database.execute(
        "SELECT state_json FROM alive_workout_state WHERE owner = ?", (f"telegram:{owner}",),
    ).fetchone()
    if row is None:
        return {}, "empty"
    state = json.loads(row[0])
    day = state["diary"].get(date) or {}
    if any(did_exercise(workout) for workout in day.get("workouts", [])):
        return day, "recorded"
    summary = state.get("summary")
    if summary and summary.get("date") == date and did_exercise(summary):
        return day, "summary"
    return day, "empty"


def message(slot, status):
    if status == "summary":
        return "Занятие уже пройдено. Открой ALIVE и сохрани итог в дневнике."
    if status == "recorded":
        return ("ЛФК за сегодня уже записана. Если ещё не отметил утреннюю скованность — самое время."
                if slot == "morning" else "ЛФК за сегодня записана. На сегодня задача закрыта.")
    if slot == "morning":
        return ("Утро. Не откладывай ЛФК на потом. Пропускать без причины не рекомендуется. "
                "Выбери время, а сейчас отметь утреннее самочувствие.")
    return ("Проверка дня. В дневнике за сегодня ещё нет ЛФК. Пропускать без причины не рекомендуется. "
            "Если на сегодня уже всё, отметь утомляемость и выбери время для ЛФК завтра.")


class TelegramFailure(Exception):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.retry_after = retry_after


def telegram(settings, method, payload=None):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = Request(
        f"https://api.telegram.org/bot{settings.token}/{method}",
        data=data, headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except HTTPError as error:
        retry = None
        if error.code == 429:
            try:
                retry = json.load(error).get("parameters", {}).get("retry_after")
            except (ValueError, AttributeError):
                pass
        raise TelegramFailure(error.code, retry) from None
    except (URLError, OSError, ValueError):
        raise TelegramFailure("uncertain") from None
    if not result.get("ok"):
        raise TelegramFailure(result.get("error_code", "uncertain"))
    return result["result"]


def app_link(url, **parameters):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(parameters)
    return parts._replace(query=urlencode(query)).geturl()


def reminder_link(url, slot):
    return app_link(url, checkin="fatigue") if slot == "evening" else url


def action(label, data):
    return {"text": label, "callback_data": data}


def open_app(label, url):
    return {"text": label, "web_app": {"url": url}}


def inline(rows):
    return {"inline_keyboard": rows}


def say(settings, text, markup=None):
    payload = {"chat_id": settings.owner, "text": text}
    if markup is not None:
        payload["reply_markup"] = markup
    return telegram(settings, "sendMessage", payload)


def score_buttons(day, metric):
    return [
        [action(str(value), f"score:{day}:{metric}:{value}") for value in values]
        for values in (range(6), range(6, 11))
    ]


def send(settings, text, slot):
    link = reminder_link(settings.url, slot)
    if slot == "morning":
        return say(settings, text, inline([[open_app("Открыть ALIVE", link)]]))
    day = datetime.now(settings.zone).date().isoformat()
    rows = score_buttons(day, "fatigue") + [[open_app("Открыть оценку в ALIVE", link)]]
    return say(settings, text + "\n\nУтомляемость за день: 0 — нет, 10 — очень сильная.", inline(rows))


def ensure_schedule(database):
    database.execute(
        """CREATE TABLE IF NOT EXISTS alive_reminder_override (
            owner INTEGER PRIMARY KEY, local_day TEXT NOT NULL, at_time TEXT NOT NULL
        )"""
    )


def evening_time(database, settings, day):
    row = database.execute(
        "SELECT at_time FROM alive_reminder_override WHERE owner = ? AND local_day = ?",
        (settings.owner, day),
    ).fetchone()
    return time.fromisoformat(row[0]) if row else settings.evening


def parse_time(value):
    digits = value[:2] + value[3:]
    if len(value) != 5 or value[2] != ":" or not (digits.isascii() and digits.isdecimal()):
        raise ValueError("Use HH:MM")
    return datetime.strptime(value, "%H:%M").time()


def evening_sent(database, settings, day):
    if not database.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alive_reminder_delivery'"
    ).fetchone():
        return False
    return database.execute(
        """SELECT 1 FROM alive_reminder_delivery WHERE owner = ? AND local_day = ?
           AND slot = 'evening' AND status IN ('sending', 'sent', 'uncertain')""",
        (settings.owner, day),
    ).fetchone() is not None


def move_evening(settings, now, value):
    try:
        at = parse_time(value)
    except ValueError:
        return "Укажи время в формате ЧЧ:ММ, например /reminders 23:30."
    day = now.date().isoformat()
    with closing(sqlite3.connect(settings.database, timeout=8)) as database, database:
        ensure_schedule(database)
        database.execute("BEGIN IMMEDIATE")
        current = evening_time(database, settings, day)
        if evening_sent(database, settings, day):
            return "Вечернее напоминание на сегодня уже отправлено."
        if at <= current or at <= now.time():
            return f"Выбери время позже {max(current, now.time()):%H:%M} в пределах сегодняшнего дня."
        database.execute(
            """INSERT INTO alive_reminder_override VALUES (?, ?, ?)
               ON CONFLICT(owner) DO UPDATE SET local_day = excluded.local_day, at_time = excluded.at_time""",
            (settings.owner, day, at.isoformat(timespec="minutes")),
        )
    return f"Сегодня напомню в {at:%H:%M}. Завтра снова в {settings.evening:%H:%M}."


def schedule_message(settings, now):
    day = now.date().isoformat()
    with closing(sqlite3.connect(settings.database, timeout=8)) as database:
        ensure_schedule(database)
        at = evening_time(database, settings, day)
        sent = evening_sent(database, settings, day)
    text = (f"Часовой пояс — {settings.zone.key}\nУтро — {settings.morning:%H:%M}\nВечер сегодня — {at:%H:%M}\n"
            f"Обычное вечернее время — {settings.evening:%H:%M}")
    if sent:
        say(settings, text + "\n\nВечернее напоминание на сегодня уже отправлено.")
        return
    local = datetime.combine(now.date(), at, settings.zone)
    options = [local + timedelta(minutes=minutes) for minutes in (15, 30, 45)]
    buttons = [action(f"{option:%H:%M}", f"move:{day}:{option:%H:%M}") for option in options
               if option.date() == now.date() and option > now]
    say(settings, text + "\n\nДо отправки можно перенести вечернее напоминание на сегодня. "
        "Укажи время командой /reminders ЧЧ:ММ или выбери кнопку.", inline([buttons]) if buttons else None)


def save_metric(settings, day, metric, value):
    if metric not in METRICS or not (0 <= value <= (1440 if metric == "stiffness" else 10)):
        raise ValueError("Invalid diary value")
    owner = f"telegram:{settings.owner}"
    with closing(connect(settings.database)) as database, database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT revision, state_json FROM alive_workout_state WHERE owner = ?", (owner,),
        ).fetchone()
        revision, state = (row[0], WorkoutState.model_validate_json(row[1])) if row else (0, WorkoutState())
        entry = state.diary.get(day) or Day()
        if getattr(entry, metric) != value:
            state.diary[day] = entry.model_copy(update={metric: value})
            database.execute(
                """INSERT INTO alive_workout_state VALUES (?, ?, ?)
                   ON CONFLICT(owner) DO UPDATE SET revision = excluded.revision, state_json = excluded.state_json""",
                (owner, revision + 1, json.dumps(state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)),
            )


def metric_value(metric, value):
    return f"{value} мин" if metric == "stiffness" else f"{value}/10"


def today_message(settings, day):
    with closing(sqlite3.connect(settings.database, timeout=8)) as database:
        entry, status = read_diary(database, settings.owner, day)
    workout = {"recorded": "записана", "summary": "пройдена, осталось сохранить итог",
               "empty": "пока без записи"}[status]
    lines = [f"Сегодня · {day[8:10]}.{day[5:7]}", f"ЛФК — {workout}"]
    for metric, label in METRICS.items():
        value = entry.get(metric)
        lines.append(f"{label} — {metric_value(metric, value) if value is not None else 'без отметки'}")
    rows = [[open_app("Начать ЛФК", app_link(settings.url, workout="nass"))]]
    say(settings, "\n".join(lines), inline(rows))


def owner_message(settings, message):
    chat = message.get("chat", {})
    return chat.get("type") == "private" and chat.get("id") == settings.owner


def handle_callback(settings, callback, now):
    if callback.get("from", {}).get("id") != settings.owner or not owner_message(
        settings, callback.get("message", {})
    ):
        return
    parts = callback.get("data", "").split(":", 2)
    day = now.date().isoformat()
    answer = "Открой /checkin или /reminders, чтобы обновить кнопки."
    if len(parts) == 3 and parts[1] == day:
        kind, _, choice = parts
        if kind == "metric" and choice in METRICS:
            telegram(settings, "answerCallbackQuery", {"callback_query_id": callback["id"]})
            if choice == "stiffness":
                say(settings, STIFFNESS_PROMPT, {"force_reply": True, "input_field_placeholder": "Минуты"})
            else:
                say(settings, f"{METRICS[choice]}: 0 — нет, 10 — очень сильная.",
                    inline(score_buttons(day, choice)))
            return
        if kind == "score":
            metric, _, raw = choice.partition(":")
            if metric in ("pain", "fatigue") and raw in {str(value) for value in range(11)}:
                save_metric(settings, day, metric, int(raw))
                answer = f"Сохранено: {METRICS[metric].lower()} {metric_value(metric, int(raw))}."
        if kind == "move":
            answer = move_evening(settings, now, choice)
    telegram(settings, "answerCallbackQuery", {"callback_query_id": callback["id"], "text": answer})


def handle_update(settings, update, now):
    if "callback_query" in update:
        handle_callback(settings, update["callback_query"], now)
        return
    msg = update.get("message", {})
    text = msg.get("text", "").strip()
    if not text or not owner_message(settings, msg) or msg.get("from", {}).get("id") != settings.owner:
        return
    day = now.date().isoformat()
    if datetime.fromtimestamp(msg.get("date", 0), settings.zone).date() != now.date():
        return
    command, _, argument = text.partition(" ")
    command = command.partition("@")[0].lower()
    if command == "/start":
        say(settings, "ALIVE · ЛФК и дневник.\n/today — сегодня\n/checkin — самочувствие\n/reminders — напоминания",
            inline([[open_app("Открыть ALIVE", settings.url)]]))
    elif command == "/today":
        today_message(settings, day)
    elif command == "/checkin":
        say(settings, "Что отметить за сегодня?", inline(
            [[action(label, f"metric:{day}:{metric}")] for metric, label in METRICS.items()]
        ))
    elif command == "/reminders":
        if argument.strip():
            say(settings, move_evening(settings, now, argument.strip()))
        else:
            schedule_message(settings, now)
    elif not command.startswith("/"):
        reply = msg.get("reply_to_message", {})
        if reply.get("from", {}).get("is_bot") and reply.get("text") == STIFFNESS_PROMPT:
            if datetime.fromtimestamp(reply.get("date", 0), settings.zone).date() != now.date():
                say(settings, "Эта форма была открыта в другой день. Вызови /checkin ещё раз.")
            elif text.isascii() and text.isdecimal() and 1 <= len(text) <= 4 and int(text) <= 1440:
                save_metric(settings, day, "stiffness", int(text))
                say(settings, f"Сохранено: утренняя скованность {int(text)} мин.")
            else:
                say(settings, STIFFNESS_PROMPT, {"force_reply": True, "input_field_placeholder": "Минуты"})


def tick(settings, now, send_message=send):
    day = now.date().isoformat()
    timestamp = int(now.timestamp())
    with closing(sqlite3.connect(settings.database, timeout=8)) as database:
        with database:
            ensure_schedule(database)
            database.execute("BEGIN IMMEDIATE")
            slot = due_slot(now, evening_time(database, settings, day), settings.morning)
            if slot is None:
                return
            key = (settings.owner, day, slot)
            database.execute(
                """CREATE TABLE IF NOT EXISTS alive_reminder_delivery (
                    owner INTEGER NOT NULL, local_day TEXT NOT NULL, slot TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL, retry_at INTEGER,
                    PRIMARY KEY (owner, local_day, slot)
                )"""
            )
            update = database.execute(
                """INSERT INTO alive_reminder_delivery VALUES (?, ?, ?, 'sending', 1, NULL)
                   ON CONFLICT(owner, local_day, slot) DO UPDATE
                   SET status = 'sending', attempts = attempts + 1, retry_at = NULL
                   WHERE status = 'retry' AND retry_at <= ? AND attempts < 3""",
                (*key, timestamp),
            )
            if update.rowcount == 0:
                return
            _, status = read_diary(database, settings.owner, day)

        retry_at = None
        try:
            send_message(settings, message(slot, status), slot)
            result = "sent"
        except TelegramFailure as error:
            if error.status == 429 and type(error.retry_after) is int and error.retry_after > 0:
                retry_at = timestamp + error.retry_after
                result = "retry"
            else:
                # A lost response may already have delivered the message.
                result = "uncertain" if error.status == "uncertain" or (
                    isinstance(error.status, int) and error.status >= 500
                ) else "rejected"
            LOG.warning("Reminder %s %s: Telegram status %s", day, slot, error.status)
        with database:
            database.execute(
                """UPDATE alive_reminder_delivery SET status = ?, retry_at = ?
                   WHERE owner = ? AND local_day = ? AND slot = ?""",
                (result, retry_at, *key),
            )
        LOG.info("Reminder %s %s: %s", day, slot, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate bot and private chat without sending anything")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = Settings.from_environment()
        if args.check:
            bot = telegram(settings, "getMe")
            chat = telegram(settings, "getChat", {"chat_id": settings.owner})
            if chat.get("type") != "private" or chat.get("id") != settings.owner:
                raise ValueError("Expected the owner's private chat")
            if telegram(settings, "getWebhookInfo").get("url"):
                raise ValueError("Long polling requires the Telegram webhook to be disabled")
            print(f"@{bot['username']}: private chat verified")
    except (KeyError, ValueError, TelegramFailure) as error:
        parser.exit(1, f"Reminder configuration failed ({type(error).__name__})\n")
    LOG.info("Schedule: %s and %s %s", settings.morning.strftime("%H:%M"), settings.evening.strftime("%H:%M"), settings.zone.key)
    if args.check:
        return
    offset = None
    registered = False
    polling = False
    while True:
        try:
            tick(settings, datetime.now(settings.zone))
        except (sqlite3.Error, ValueError) as error:
            LOG.warning("Diary is temporarily unavailable (%s)", type(error).__name__)
        try:
            if not registered:
                telegram(settings, "setMyCommands", {
                    "commands": [{"command": command, "description": description}
                                 for command, description in COMMANDS.items()],
                    "scope": {"type": "chat", "chat_id": settings.owner},
                })
                registered = True
                LOG.info("Private chat commands registered")
            options = {"timeout": 5, "limit": 20, "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                options["offset"] = offset
            updates = telegram(settings, "getUpdates", options)
            if not polling:
                polling = True
                LOG.info("Telegram polling ready")
            for update in updates:
                try:
                    handle_update(settings, update, datetime.now(settings.zone))
                except TelegramFailure as error:
                    LOG.warning("Chat reply failed: Telegram status %s", error.status)
                offset = update["update_id"] + 1
        except TelegramFailure as error:
            LOG.warning("Chat polling failed: Telegram status %s", error.status)
            sleep(min(max(error.retry_after or 5, 1), 30))
        except (sqlite3.Error, ValueError) as error:
            LOG.warning("Chat update interrupted (%s)", type(error).__name__)
            sleep(5)


if __name__ == "__main__":
    main()
