"""Run the owner's private ALIVE chat and daily reminders."""

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import json
import logging
import os
from secrets import token_hex
import sqlite3
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .app import Day, WorkoutState, connect, daily_workout_goal

DEFAULT_MORNING = time(8)
DEFAULT_EVENING = time(21)
WINDOW = timedelta(minutes=15)
LOG = logging.getLogger("alive.reminders")
METRICS = {"pain": "Боль", "stiffness": "Утренняя скованность", "fatigue": "Утомляемость"}
STIFFNESS_PROMPT = "Утренняя скованность. Ответь числом минут (0–1440)."
COMMANDS = {
    "start": "Открыть ALIVE", "today": "Что записано сегодня",
    "checkin": "Отметить самочувствие", "reminders": "Расписание напоминаний",
    "wakeup": "Таймер перерыва на разминку",
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
        return {}, 0, False
    row = database.execute(
        "SELECT state_json FROM alive_workout_state WHERE owner = ?", (f"telegram:{owner}",),
    ).fetchone()
    if row is None:
        return {}, 0, False
    state = json.loads(row[0])
    day = state["diary"].get(date) or {}
    completed = sum(did_exercise(workout) for workout in day.get("workouts", []))
    summary = state.get("summary")
    pending = bool(summary and summary.get("date") == date and did_exercise(summary))
    return day, completed, pending


def progress_line(completed, goal):
    return f"ЛФК за сегодня — {min(completed, goal)}/{goal}."


def message(slot, completed, pending, goal):
    remaining = max(0, goal - completed)
    progress = progress_line(completed, goal)
    if pending:
        return f"{progress} В ALIVE есть несохранённый итог. Сохрани его, чтобы занятие появилось в дневнике."
    if slot == "morning":
        if not remaining:
            return f"{progress} Дневная цель выполнена. Если ещё не отметил утреннюю скованность — самое время."
        return (f"{progress} Утро. Не откладывай ЛФК на потом. Пропускать без причины не рекомендуется. "
                "Сейчас можно отметить утреннее самочувствие.")
    if not remaining:
        return f"Вечерняя отметка. {progress} Дневная цель выполнена."
    next_workout = "Осталось ещё одно занятие." if remaining == 1 else "Осталось два занятия."
    return (f"Вечерняя отметка. {progress} {next_workout} "
            "Пропускать без причины не рекомендуется.")


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


def say(settings, text, markup=None, *, parse_mode=None):
    payload = {"chat_id": settings.owner, "text": text}
    if markup is not None:
        payload["reply_markup"] = markup
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode
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
        entry, completed, pending = read_diary(database, settings.owner, day)
    lines = [f"Сегодня · {day[8:10]}.{day[5:7]}", progress_line(completed, daily_workout_goal())]
    if pending:
        lines.append("В ALIVE есть несохранённый итог занятия.")
    for metric, label in METRICS.items():
        value = entry.get(metric)
        lines.append(f"{label} — {metric_value(metric, value) if value is not None else 'без отметки'}")
    rows = [[open_app("Начать ЛФК", app_link(settings.url, workout="nass"))]]
    say(settings, "\n".join(lines), inline(rows))


def owner_message(settings, message):
    chat = message.get("chat", {})
    return chat.get("type") == "private" and chat.get("id") == settings.owner


@contextmanager
def wake_database(settings):
    with closing(sqlite3.connect(settings.database, timeout=8)) as database, database:
        database.execute("""CREATE TABLE IF NOT EXISTS alive_wakeup_timer (
            owner INTEGER PRIMARY KEY, id TEXT NOT NULL, due_at INTEGER NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS alive_wakeup_breaks (
            owner INTEGER NOT NULL, timer_id TEXT NOT NULL, completed_at INTEGER NOT NULL,
            local_day TEXT NOT NULL, PRIMARY KEY (owner, timer_id)
        )""")
        yield database


def start_wakeup(settings, now, minutes):
    due_at = int(now.timestamp()) + minutes * 60
    with wake_database(settings) as database:
        database.execute(
            """INSERT INTO alive_wakeup_timer (owner, id, due_at) VALUES (?, ?, ?)
               ON CONFLICT(owner) DO UPDATE SET id = excluded.id, due_at = excluded.due_at,
                   notified = 0, attempts = 0""",
            (settings.owner, token_hex(8), due_at),
        )
    at = datetime.fromtimestamp(due_at, settings.zone)
    return f"WAKE UP · таймер на {minutes} мин. Напомню в {at:%H:%M}."


def wakeup_command(settings, now, argument):
    if argument == "stop":
        with wake_database(settings) as database:
            result = database.execute("DELETE FROM alive_wakeup_timer WHERE owner = ?", (settings.owner,))
        say(settings, "Таймер WAKE UP отменён." if result.rowcount else "Активного таймера WAKE UP нет.")
        return
    if argument:
        if argument.isascii() and argument.isdecimal() and len(argument) <= 3 and 1 <= int(argument) <= 720:
            say(settings, start_wakeup(settings, now, int(argument)))
        else:
            say(settings, "Укажи от 1 до 720 минут, например /wakeup 45. Отмена — /wakeup stop.")
        return
    with wake_database(settings) as database:
        timer = database.execute(
            "SELECT due_at FROM alive_wakeup_timer WHERE owner = ? AND notified = 0", (settings.owner,),
        ).fetchone()
        completed, = database.execute(
            "SELECT COUNT(*) FROM alive_wakeup_breaks WHERE owner = ? AND local_day = ?",
            (settings.owner, now.astimezone(settings.zone).date().isoformat()),
        ).fetchone()
    title = f"Текущий пинг в {datetime.fromtimestamp(timer[0], settings.zone):%H:%M}." if timer else "Когда напомнить?"
    buttons = [action(f"{minutes} мин", f"wake:start:{minutes}") for minutes in (30, 45, 60)]
    say(settings, f"WAKE UP · {title}\nПерерывов за сегодня: {completed}.\n\n"
        "Выбери время или введи /wakeup 45. Новый таймер заменяет предыдущий.",
        inline([buttons]))


def wakeup_callback(settings, now, operation, value):
    if operation == "start" and value in ("30", "45", "60"):
        return start_wakeup(settings, now, int(value))
    with wake_database(settings) as database:
        key = (settings.owner, value)
        if operation == "done":
            result = database.execute(
                "DELETE FROM alive_wakeup_timer WHERE owner = ? AND id = ? AND notified = 1", key,
            )
            if result.rowcount:
                database.execute(
                    """INSERT INTO alive_wakeup_breaks (owner, timer_id, completed_at, local_day)
                       VALUES (?, ?, ?, ?)""",
                    (*key, int(now.timestamp()), now.astimezone(settings.zone).date().isoformat()),
                )
                return "Перерыв отмечен."
        elif operation == "snooze":
            result = database.execute(
                """UPDATE alive_wakeup_timer SET id = ?, due_at = ?, notified = 0, attempts = 0
                   WHERE owner = ? AND id = ? AND notified = 1""",
                (token_hex(8), int(now.timestamp()) + 600, *key),
            )
            if result.rowcount:
                return "Напомню через 10 минут."
    return "Эта кнопка уже неактуальна. Новый таймер — /wakeup."


def tick_wakeup(settings, now):
    timestamp = int(now.timestamp())
    with wake_database(settings) as database:
        timer = database.execute(
            """UPDATE alive_wakeup_timer SET notified = 1, attempts = attempts + 1
               WHERE owner = ? AND due_at <= ? AND notified = 0 RETURNING id, attempts""",
            (settings.owner, timestamp),
        ).fetchone()
    if timer is None:
        return
    timer_id, attempts = timer
    buttons = [[action("Размялся", f"wake:done:{timer_id}"),
                action("Через 10 мин", f"wake:snooze:{timer_id}")]]
    try:
        say(settings, "<b>WAKE UP · 3–4 минуты</b>\nПора встать и размяться.\n\n"
            "<b>1. Ходьба · 2 минуты</b>\nВстань и спокойно пройдись.\n\n"
            "<b>2. Круги плечами · 3 вперёд и 3 назад</b>\nДвигай плечами плавно, сидя или стоя.\n\n"
            "<b>3. Повороты головы · по 3 на сторону</b>\n"
            "По желанию. Сядь прямо, поставь стопы на пол и поворачивай голову, не двигая плечами.\n\n"
            "<i>Двигайся в комфортной амплитуде, без боли.</i>", inline(buttons), parse_mode="HTML")
    except TelegramFailure as error:
        if error.status == 429 and type(error.retry_after) is int and error.retry_after > 0 and attempts < 3:
            with wake_database(settings) as database:
                database.execute(
                    "UPDATE alive_wakeup_timer SET notified = 0, due_at = ? WHERE owner = ? AND id = ?",
                    (timestamp + error.retry_after, settings.owner, timer_id),
                )
        LOG.warning("WAKE UP delivery: Telegram status %s", error.status)


def handle_callback(settings, callback, now):
    if callback.get("from", {}).get("id") != settings.owner or not owner_message(
        settings, callback.get("message", {})
    ):
        return
    parts = callback.get("data", "").split(":", 2)
    if len(parts) == 3 and parts[0] == "wake":
        answer = wakeup_callback(settings, now, parts[1], parts[2])
        telegram(settings, "answerCallbackQuery", {"callback_query_id": callback["id"], "text": answer})
        return
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
    command, _, argument = text.partition(" ")
    command = command.partition("@")[0].lower()
    if command == "/wakeup":
        wakeup_command(settings, now, argument.strip().lower())
        return
    day = now.date().isoformat()
    if datetime.fromtimestamp(msg.get("date", 0), settings.zone).date() != now.date():
        return
    if command == "/start":
        say(settings, "ALIVE · ЛФК и дневник.\n/today — сегодня\n/checkin — самочувствие\n"
            "/reminders — напоминания\n/wakeup — таймер разминки",
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
            _, completed, pending = read_diary(database, settings.owner, day)

        retry_at = None
        try:
            send_message(settings, message(slot, completed, pending, daily_workout_goal()), slot)
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
            now = datetime.now(settings.zone)
            tick(settings, now)
            tick_wakeup(settings, now)
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
