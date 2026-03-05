"""Simple Telegram bot: schedule with auto-updates on changes."""

import asyncio
import logging
import hashlib
import os
import time
from datetime import datetime
from typing import Set

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None
    
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from schedule import get_schedule_image_bytes
from database import Database

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
import subprocess
import sys

def ensure_playwright():
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True
        )
    except Exception:
        pass

# База данных для отметок

DB = Database()

# Telegram user_id админа (только он может смотреть отметки).
# Задай переменную окружения BOT_ADMIN_ID=123456789
ADMIN_USER_ID = int(os.getenv("BOT_ADMIN_ID", "5082025415") or "0")
BOT_TZ = os.getenv("BOT_TZ", "Asia/Novosibirsk")
# Для тестов: можно принудительно задать дату/время, например:
# BOT_FAKE_DATE=2026-03-02 или BOT_FAKE_DATETIME=2026-03-02T09:00:00
# BOT_FAKE_DATE = os.getenv("BOT_FAKE_DATE", "").strip()
# BOT_FAKE_DATETIME = os.getenv("BOT_FAKE_DATETIME", "").strip()

# Главное меню (кнопки в чате)


# Чаты, которые подписаны на автообновления расписания
SUBSCRIBERS: Set[int] = set()
# Последний отправленный хэш расписания (картинка или текст)
LAST_SCHEDULE_HASH: str | None = None


def _now() -> datetime:
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(BOT_TZ)
        except Exception:
            tz = None

    # Тестовый оверрайд даты/времени
    # if BOT_FAKE_DATETIME:
    #     try:
    #         dt = datetime.fromisoformat(BOT_FAKE_DATETIME)
    #         if tz is not None and dt.tzinfo is None:
    #             dt = dt.replace(tzinfo=tz)
    #         return dt
    #     except Exception:
    #         pass

    # if BOT_FAKE_DATE:
    #     try:
    #         d = datetime.fromisoformat(BOT_FAKE_DATE).date()
    #         dt = datetime(d.year, d.month, d.day, 12, 0, 0)
    #         if tz is not None:
    #             dt = dt.replace(tzinfo=tz)
    #         return dt
    #     except Exception:
    #         pass

    if tz is None:
        return datetime.now()
    return datetime.now(tz)


def _is_admin(update: Update) -> bool:
    return bool(ADMIN_USER_ID) and update.effective_user and update.effective_user.id == ADMIN_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот расписания колледжа.\n"
        "Выбери действие кнопками ниже или используй /schedule.",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Доступные команды:\n"
        "/schedule — расписание подгрупп 2507а1 и 2507а2 (картинкой)\n"
        "/mark — отметиться (только в понедельник и четверг)\n"
        "/subscribe — включить автообновления расписания\n"
        "/unsubscribe — отключить автообновления расписания\n"
        "/myid — показать твой Telegram ID\n"
        "/attendance [YYYY-MM-DD] — список отметившихся за дату (только для админа в ЛС)\n"
        "Админ: /whitelist, /whitelist_add, /whitelist_remove, /whitelist_set\n"
        "/help — это сообщение",
    )


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Расписание с сайта колледжа. Работает в ЛС и в группах."""
    msg = await update.message.reply_text("⏳ Загружаю расписание...")
    try:
        result = await asyncio.to_thread(get_schedule_image_bytes)

        if isinstance(result, (bytes, bytearray)):
            try:
                await msg.delete()
            except Exception:
                pass
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=result,
                caption="📅 Расписание подгрупп 2507а1 и 2507а2",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text(str(result), parse_mode="HTML")
    except Exception as e:
        logger.exception("Schedule fetch error")
        await msg.edit_text(f"❌ Ошибка: {e}")


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return
    await update.message.reply_text(
        f"Ваш Telegram ID: <code>{update.effective_user.id}</code>",
        parse_mode="HTML",
    )


async def mark_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отметка присутствия. Разрешено только по понедельникам и четвергам, и только из вайтлиста."""
    if not update.effective_user or not update.effective_chat:
        return

    if not DB.is_in_whitelist(update.effective_user.id):
        await update.message.reply_text(
            "⛔ Ты не в списке допущенных к отметке. Обратись к администратору.",
            parse_mode="HTML",
        )
        return

    now = _now()
    weekday = now.weekday()  # 0=Mon ... 6=Sun
    if weekday not in (0, 3):
        await update.message.reply_text(
            "Отметиться можно только в <b>понедельник</b> и <b>четверг</b>.",
            parse_mode="HTML",
        )
        return

    date_str = now.date().isoformat()
    full_name = " ".join(
        [p for p in [update.effective_user.first_name, update.effective_user.last_name] if p]
    ).strip()
    username = update.effective_user.username
    chat_title = getattr(update.effective_chat, "title", None)
    chat_type = update.effective_chat.type

    inserted = DB.add_attendance(
        chat_id=update.effective_chat.id,
        chat_title=chat_title,
        chat_type=chat_type,
        user_id=update.effective_user.id,
        username=username,
        full_name=full_name or None,
        date=date_str,
        weekday=weekday,
        created_at=int(time.time()),
    )

    if inserted:
        await update.message.reply_text(
            f"✅ Отмечено на <b>{date_str}</b>.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"ℹ️ Ты уже отмечался(ась) сегодня (<b>{date_str}</b>).",
            parse_mode="HTML",
        )


def _split_message(text: str, limit: int = 3800) -> list[str]:
    """Делит длинный текст на куски для Telegram."""
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines():
        add = len(line) + 1
        if buf and size + add > limit:
            parts.append("\n".join(buf))
            buf = []
            size = 0
        buf.append(line)
        size += add
    if buf:
        parts.append("\n".join(buf))
    return parts


async def attendance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Просмотр отметившихся за день. Только админ и только в ЛС."""
    if not update.effective_chat or not update.effective_user:
        return

    # В личке Telegram обычно chat_id == user_id. Это более надёжная проверка,
    # чем сравнение по type (на случай нестандартных типов/объектов).
    is_private_dm = (update.effective_chat.type == "private") or (
        update.effective_chat.id == update.effective_user.id
    )
    if not is_private_dm:
        await update.message.reply_text("Напиши команду /attendance мне в личные сообщения.")
        return

    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    now = _now()
    date_str = now.date().isoformat()
    if context.args:
        date_str = context.args[0].strip()

    rows = DB.list_attendance_by_date(date_str)
    if not rows:
        await update.message.reply_text(f"Нет отметок на {date_str}.")
        return

    lines: list[str] = [f"📌 <b>Отметки за {date_str}</b>", ""]
    current_chat = None
    for r in rows:
        chat_label = r.get("chat_title") or str(r.get("chat_id"))
        if chat_label != current_chat:
            current_chat = chat_label
            lines.append(f"🗂 <b>{chat_label}</b>")
        # Приоритет: подпись из вайтлиста, иначе имя
        label = r.get("whitelist_label") or r.get("full_name") or str(r.get("user_id"))
        uname = r.get("username")
        if uname:
            lines.append(f"- {label} (@{uname})")
        else:
            lines.append(f"- {label}")

    text = "\n".join(lines).strip()
    for chunk in _split_message(text):
        await update.message.reply_text(chunk, parse_mode="HTML")


async def whitelist_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавить пользователя в вайтлист: /whitelist_add <user_id> <подпись> или ответом на сообщение: /whitelist_add <подпись>."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    reply = update.message.reply_to_message
    if reply and reply.from_user:
        user_id = reply.from_user.id
        label = " ".join(context.args).strip() if context.args else (reply.from_user.full_name or str(user_id))
        username = reply.from_user.username
        full_name = reply.from_user.full_name
    else:
        if len(context.args) < 2:
            await update.message.reply_text(
                "Использование:\n"
                "/whitelist_add <user_id> <подпись>\n"
                "или ответь на сообщение пользователя: /whitelist_add <подпись>"
            )
            return
        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ user_id должен быть числом.")
            return
        label = " ".join(context.args[1:]).strip() or str(user_id)
        username = full_name = None

    if DB.add_to_whitelist(user_id, label, username, full_name):
        await update.message.reply_text(f"✅ Добавлен в вайтлист: {user_id} — <b>{label}</b>", parse_mode="HTML")
    else:
        DB.set_whitelist_label(user_id, label)
        await update.message.reply_text(f"ℹ️ Пользователь {user_id} уже в вайтлисте. Подпись обновлена: <b>{label}</b>", parse_mode="HTML")


async def whitelist_remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удалить из вайтлиста: /whitelist_remove <user_id>."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /whitelist_remove <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом.")
        return
    if DB.remove_from_whitelist(user_id):
        await update.message.reply_text(f"✅ Пользователь {user_id} удалён из вайтлиста.")
    else:
        await update.message.reply_text(f"ℹ️ Пользователь {user_id} не был в вайтлисте.")


async def whitelist_set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменить подпись: /whitelist_set <user_id> <новая подпись>."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /whitelist_set <user_id> <новая подпись>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом.")
        return
    label = " ".join(context.args[1:]).strip()
    if DB.set_whitelist_label(user_id, label):
        await update.message.reply_text(f"✅ Подпись обновлена: {user_id} — <b>{label}</b>", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Пользователь {user_id} не в вайтлисте. Добавь его через /whitelist_add.")


async def whitelist_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список вайтлиста."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    rows = DB.list_whitelist()
    if not rows:
        await update.message.reply_text("Вайтлист пуст.")
        return
    lines = ["📋 <b>Вайтлист</b>", ""]
    for r in rows:
        label = r.get("label", "")
        uid = r.get("user_id", "")
        uname = r.get("username")
        if uname:
            lines.append(f"• {label} (id: {uid}, @{uname})")
        else:
            lines.append(f"• {label} (id: {uid})")
    text = "\n".join(lines)
    for chunk in _split_message(text):
        await update.message.reply_text(chunk, parse_mode="HTML")


async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий на кнопки меню."""
    if not update.message or not update.message.text:
        return
    t = update.message.text.strip()
    if t == "📅 Расписание":
        await schedule_cmd(update, context)
    elif t == "✅ Отметиться":
        await mark_cmd(update, context)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подписка чата на автообновления расписания."""
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    await update.message.reply_text(
        "✅ Этот чат подписан на автообновления расписания.\n"
        "Я буду присылать новое расписание, как только оно изменится на сайте."
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отписка чата от автообновлений расписания."""
    chat_id = update.effective_chat.id
    SUBSCRIBERS.discard(chat_id)
    await update.message.reply_text("❌ Автообновления расписания для этого чата отключены.")


async def check_schedule_updates(application: Application) -> None:
    """Проверяет расписание и шлёт обновление только если оно поменялось."""
    global LAST_SCHEDULE_HASH

    try:
        result = await asyncio.to_thread(get_schedule_image_bytes)
    except Exception as e:
        logger.exception(f"Ошибка при автообновлении расписания: {e}")
        return

    # Вычисляем хэш содержимого (картинки или текста)
    if isinstance(result, (bytes, bytearray)):
        data = bytes(result)
    else:
        data = str(result).encode("utf-8", errors="ignore")

    current_hash = hashlib.sha256(data).hexdigest()

    # Если это первый запуск — просто запоминаем хэш, но не спамим подписчикам
    if LAST_SCHEDULE_HASH is None:
        LAST_SCHEDULE_HASH = current_hash
        logger.info("Инициализирован хэш расписания для автообновлений.")
        return

    # Ничего не изменилось
    if current_hash == LAST_SCHEDULE_HASH:
        return

    # Обновилось: запоминаем новый хэш и рассылаем всем подписчикам
    LAST_SCHEDULE_HASH = current_hash
    logger.info("Обнаружено изменение расписания, рассылаю подписчикам.")

    for chat_id in list(SUBSCRIBERS):
        try:
            if isinstance(result, (bytes, bytearray)):
                await application.bot.send_photo(
                    chat_id=chat_id,
                    photo=result,
                    caption="📅 Обновлённое расписание подгрупп 2507а1 и 2507а2",
                    parse_mode="HTML",
                )
            else:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=str(result),
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.exception(
                f"Не удалось отправить автообновление расписания в чат {chat_id}: {e}"
            )


async def auto_updates_loop(application: Application) -> None:
    """Фоновый цикл: периодически вызывает check_schedule_updates."""
    while True:
        try:
            await asyncio.sleep(60 * 60)  # каждые 60 минут
            await check_schedule_updates(application)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"Ошибка в цикле автообновлений расписания: {e}")


async def post_init(application: Application) -> None:
    """Хук, который вызывается после старта Application и запуска event loop."""
    # Запускаем фоновый цикл автообновлений расписания
    application.create_task(auto_updates_loop(application))


def main() -> None:
    TOKEN = os.getenv("BOT_TOKEN")

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("schedule", schedule_cmd))
    application.add_handler(CommandHandler("mark", mark_cmd))
    application.add_handler(CommandHandler("myid", myid_cmd))
    application.add_handler(CommandHandler("attendance", attendance_cmd))
    # Вайтлист (только админ)
    application.add_handler(CommandHandler("whitelist", whitelist_list_cmd))
    application.add_handler(CommandHandler("whitelist_add", whitelist_add_cmd))
    application.add_handler(CommandHandler("whitelist_remove", whitelist_remove_cmd))
    application.add_handler(CommandHandler("whitelist_set", whitelist_set_cmd))
    # Команды для подписки/отписки
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    # Кнопки меню
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text_handler))
    # application.add_handler(CommandHandler("расписание", schedule_cmd))

    logger.info("Schedule bot started with auto-updates!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
