from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import NetworkError, TimedOut
import re
from datetime import datetime, timedelta
from telegram.request import HTTPXRequest
import threading
from flask import Flask
import os

from config import TOKEN, API_ID, API_HASH
from data import user_queues, save_queues, user_notify_time, save_notify_time
from parser import get_queue_schedule, get_queue_intervals, calculate_stats, get_last_posts
from buttons import main_keyboard, queues_keyboard, notify_buttons

app = Flask('')

@app.route('/')
def home():
    return "Ok", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host ='0.0.0.0', port=port)
    
threading.Thread(target=run_web).start()

sent_notifications = {}
last_post_ids = {}
last_user_schedules = {}

months_ua = [
    "січня", "лютого", "березня", "квітня",
    "травня", "червня", "липня", "серпня",
    "вересня", "жовтня", "листопада", "грудня"
]


# --- КОМАНДИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! ⚡\n"
        "Я бот для сповіщень про відключення світла.\n\n"
        "Введи свою чергу так:\n"
        "Приклад: 1.1",
        reply_markup=main_keyboard()
    )


async def setqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❗ Формат:\n"
            "/setqueue <черга> [назва]\n"
            "Приклади:\n"
            "/setqueue 4.1\n"
            "/setqueue 4.1 Дім"
        )
        return

    queue = context.args[0].strip()
    name = " ".join(context.args[1:]).strip() if len(context.args) > 1 else "Без назви"
    if not re.fullmatch(r"\d+(\.\d+)?", queue):
        await update.message.reply_text("❌ Неправильний формат. Наприклад: 4.1")
        return

    user_id = str(update.effective_user.id)

    if user_id not in user_queues:
        user_queues[user_id] = []

    for q in user_queues[user_id]:
        if q["queue"] == queue:
            await update.message.reply_text(f"ℹ️ Черга {queue} вже є у списку.", reply_markup=main_keyboard())
            return

    user_queues[user_id].append({"queue": queue, "name": name})
    save_queues()

    if name == "Без назви":
        await update.message.reply_text(f"✅ Чергу {queue} додано без назви.", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(
            f"✅ Чергу додано:\n• Черга: {queue}\n• Назва: {name}",
            reply_markup=main_keyboard()
        )


async def setnotify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Приклад: /setnotify 30")
        return

    try:
        minutes = int(context.args[0])
        if not 1 <= minutes <= 180:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи число від 1 до 180")
        return

    user_notify_time[str(update.effective_user.id)] = minutes
    save_notify_time()
    await update.message.reply_text(f"⏰ Попередження за {minutes} хвилин", reply_markup=main_keyboard())


async def mynotify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    minutes = user_notify_time.get(str(update.effective_user.id), 30)
    await update.message.reply_text(f"⏰ Час попередження: {minutes} хв", reply_markup=main_keyboard())


async def myqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    queues = user_queues.get(user_id)

    if not queues:
        await update.message.reply_text("Ти ще не додав(ла) жодної черги", reply_markup=main_keyboard())
        return

    text = "🔢 Твої черги:\n"
    for i, q in enumerate(queues, 1):
        if q["name"] == "Без назви":
            text += f"{i}. {q['queue']}\n"
        else:
            text += f"{i}. {q['queue']} — {q['name']}\n"

    await update.message.reply_text(text, reply_markup=queues_keyboard(queues))


async def delqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Вкажи номер черги для видалення.\nНаприклад: /delqueue 4.1")
        return

    queue = context.args[0]
    user_id = str(update.effective_user.id)

    if user_id not in user_queues or not any(q["queue"] == queue for q in user_queues[user_id]):
        await update.message.reply_text("❌ Такої черги немає у твоєму списку.", reply_markup=main_keyboard())
        return

    user_queues[user_id] = [q for q in user_queues[user_id] if q["queue"] != queue]
    save_queues()

    if not user_queues[user_id]:
        del user_queues[user_id]

    await update.message.reply_text(f"🗑 Чергу {queue} видалено.", reply_markup=main_keyboard())


# --- ПАРСИНГ ---
def extract_date_from_post(post_text):
    text = post_text.lower()
    for month in months_ua:
        match = re.search(rf"(\d{{1,2}})\s+{month}", text)
        if match:
            return int(match.group(1)), month
    now = datetime.now()
    return now.day, months_ua[now.month - 1]


def parse_time_safe_today(time_str, now):
    if time_str == "24:00":
        t = datetime.strptime("00:00", "%H:%M")
        return t.replace(year=now.year, month=now.month, day=now.day) + timedelta(days=1)
    else:
        t = datetime.strptime(time_str, "%H:%M")
        return t.replace(year=now.year, month=now.month, day=now.day)


async def check_queues(app):
    now = datetime.now()
    posts = await get_last_posts()
    if not posts:
        print("[Parser] Не вдалося отримати пости")
        return

    latest_post_id = hash(posts[-1])
    day, month = extract_date_from_post(posts[-1])
    date_line = f"📅 {day} {month}\n\n"

    for user_id, queues in user_queues.items():
        notify_minutes = user_notify_time.get(user_id, 30)

        for queue_data in queues:
            queue_number = queue_data["queue"]
            queue_name = queue_data["name"]

            intervals = await get_queue_intervals(queue_number)
            if not intervals:
                continue

            times_text = "\n".join([f"{s} - {e}" for s, e in intervals])
            previous_times = last_user_schedules.get(f"{user_id}_{queue_number}")

            if times_text != previous_times:
                stats = await calculate_stats(queue_number)
                stats_text = ""
                if stats:
                    stats_text = (
                        f"\n\n📊 Статистика за день:\n"
                        f"• Вимкнень: {stats['num_outages']}\n"
                        f"• Світло увімкнено: {stats['total_on']}\n"
                        f"• Світло вимкнено: {stats['total_off']}"
                    )

                header = f"⚡️ Оновлено графік для черги {queue_number}"
                if queue_name != "Без назви":
                    header += f" — {queue_name}"

                try:
                    await safe_send(app.bot, int(user_id),
                        f"{date_line}{header}:\n{times_text}{stats_text}"
                    )
                    last_user_schedules[f"{user_id}_{queue_number}"] = times_text
                    last_post_ids[f"{user_id}_{queue_number}"] = latest_post_id
                except Exception as e:
                    print(f"Помилка відправки {user_id}: {e}")

            # Відправка попереджень
            if user_id not in sent_notifications:
                sent_notifications[user_id] = []

            for start_str, end_str in intervals:
                start = parse_time_safe_today(start_str, now)
                end = parse_time_safe_today(end_str, now)
                if end < start:
                    end += timedelta(days=1)

                key_start = (queue_number, start_str, end_str, "before_start")
                if start - timedelta(minutes=notify_minutes) <= now <= start and key_start not in sent_notifications[user_id]:
                    await safe_send(
                        app.bot,
                        int(user_id),
                        f"⚡ Через {notify_minutes} хв світло буде вимкнено ({start_str}-{end_str})"
                    )
                    sent_notifications[user_id].append(key_start)

                key_end = (queue_number, start_str, end_str, "before_end")
                if end - timedelta(minutes=notify_minutes) <= now <= end and key_end not in sent_notifications[user_id]:
                    await safe_send(
                        app.bot,
                        int(user_id),
                        f"💡 Через {notify_minutes} хв світло буде увімкнено ({start_str}-{end_str})"
                    )
                    sent_notifications[user_id].append(key_end)


# --- ФУНКЦІЯ КНОПОК ---
async def handle_queue_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    queues = user_queues.get(user_id)

    if not queues:
        await safe_send(context.bot, update.effective_chat.id, "Ти ще не додав(ла) жодної черги", reply_markup=main_keyboard())
        return

    queue_data = queues[0] 
    queue_number = queue_data["queue"]

    times = await get_queue_schedule(queue_number)
    if not times:
        await safe_send(context.bot, update.effective_chat.id, "Немає даних по твоїй черзі", reply_markup=main_keyboard())
        return

    text = f"⚡ Графік для черги {queue_number}"
    if queue_data["name"] != "Без назви":
        text += f" — {queue_data['name']}"
    text += ":\n\n" + "\n".join(times)

    await safe_send(context.bot, update.effective_chat.id, text, reply_markup=queues_keyboard(queues))


# --- ОБРОБКА ПОВІДОМЛЕНЬ ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    
    if text in ["➕ Додати чергу", "🗑 Видалити чергу", "📋 Мої черги", "⬅ Назад"]:
        context.user_data["waiting_for_queue"] = False
        context.user_data["waiting_for_delete"] = False

    # 1. Видалення черги без команд
    if context.user_data.get("waiting_for_delete"):
        context.user_data["waiting_for_delete"] = False
        queue = text.strip()

        if user_id not in user_queues or not any(q["queue"] == queue for q in user_queues[user_id]):
            await safe_send(context.bot, update.effective_chat.id,
                "❌ Такої черги немає у твоєму списку.",
                reply_markup=main_keyboard()
            )
            return

        user_queues[user_id] = [q for q in user_queues[user_id] if q["queue"] != queue]
        save_queues()

        if not user_queues[user_id]:
            del user_queues[user_id]

        await update.message.reply_text(
            f"🗑 Чергу {queue} видалено.",
            reply_markup=main_keyboard()
        )
        return


    # 2. Додавання черги без команд
    if context.user_data.get("waiting_for_queue"):
        context.user_data["waiting_for_queue"] = False

        parts = text.split()
        queue = parts[0].strip()
        name = " ".join(parts[1:]).strip() if len(parts) > 1 else "Без назви"

        if not re.fullmatch(r"\d+(\.\d+)?", queue):
            await update.message.reply_text(
                "❌ Неправильний формат.\nПриклад: 4.1 або 4.1 Дім",
                reply_markup=main_keyboard()
            )
            return

        if user_id not in user_queues:
            user_queues[user_id] = []

        for q in user_queues[user_id]:
            if q["queue"] == queue:
                await update.message.reply_text(
                    f"ℹ️ Черга {queue} вже є у списку.",
                    reply_markup=main_keyboard()
                )
                return

        user_queues[user_id].append({"queue": queue, "name": name})
        save_queues()

        await update.message.reply_text(
            f"✅ Чергу додано:\n• Черга: {queue}\n• Назва: {name}",
            reply_markup=main_keyboard()
        )
        return


    # 3. Обробка кнопок
    if text == "➕ Додати чергу":
        context.user_data["waiting_for_queue"] = True
        await update.message.reply_text(
            "Введи номер черги та, за бажанням, назву.\n"
            "Приклад:\n4.1\n4.1 Дім"
        )

    elif text == "🗑 Видалити чергу":
        context.user_data["waiting_for_delete"] = True
        await update.message.reply_text("Введи номер черги для видалення:")

    elif text == "📋 Мої черги":
        await myqueue(update, context)

    elif text == "⚡ Перевірити чергу":
        await handle_queue_button(update, context)

    elif text == "📅 Коли світло?":
        await nowlight(update, context)

    elif text == "⏰ Налаштувати сповіщення":
        await update.message.reply_text("Вибери час сповіщення:", reply_markup=notify_buttons())

    elif text in ["5", "15", "30", "60", "120"]:
        minutes = int(text)
        user_notify_time[user_id] = minutes
        save_notify_time()
        await update.message.reply_text(
            f"⏰ Попередження за {minutes} хвилин",
            reply_markup=main_keyboard()
        )

    elif text in ["⬅ Назад", "Назад"]:
        await update.message.reply_text("Головне меню:", reply_markup=main_keyboard())


    # 4. Натискання на кнопку конкретної черги
    else:
        queues = user_queues.get(user_id, [])
        for q in queues:
            btn_text = q["queue"] if q["name"] == "Без назви" else f"{q['queue']} — {q['name']}"
            if text == btn_text:
                queue_number = q["queue"]

                times = await get_queue_schedule(queue_number)
                if not times:
                    await update.message.reply_text(
                        "Немає даних по цій черзі",
                        reply_markup=main_keyboard()
                    )
                    return

                result = f"⚡ Графік для черги {queue_number}"
                if q["name"] != "Без назви":
                    result += f" — {q['name']}"
                result += ":\n\n" + "\n".join(times)

                await update.message.reply_text(
                    result,
                    reply_markup=queues_keyboard(queues)
                )
                return

        # 5. Якщо взагалі нічого не співпало
        await update.message.reply_text(
            "❌ Невідома команда",
            reply_markup=main_keyboard()
        )

        
        
async def nowlight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    queues = user_queues.get(user_id)

    if not queues:
        await safe_send(context.bot, chat_id, "Ти ще не додав(ла) жодної черги", reply_markup=main_keyboard())
        return

    queue_data = queues[0]
    queue_number = queue_data["queue"]
    queue_name = queue_data["name"]

    intervals = await get_queue_intervals(queue_number)
    if not intervals:
        await safe_send(context.bot, chat_id, "Немає даних по твоїй черзі", reply_markup=main_keyboard())
        return

    now = datetime.now()

    # Перетворюємо строки у datetime
    off_periods = []
    for start_str, end_str in intervals:
        start = parse_time_safe_today(start_str, now)
        end = parse_time_safe_today(end_str, now)
        if end < start:
            end += timedelta(days=1)
        off_periods.append((start, end))

    # Сортуємо
    off_periods.sort(key=lambda x: x[0])

    # Будуємо інтервали, коли світло Є
    light_periods = []
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    prev_end = day_start
    for start, end in off_periods:
        if prev_end < start:
            light_periods.append((prev_end, start))
        prev_end = end

    if prev_end < day_end:
        light_periods.append((prev_end, day_end))

    header = f"⚡ Черга {queue_number}"
    if queue_name != "Без назви":
        header += f" — {queue_name}"

    # Перевіряємо де ми зараз
    for start, end in light_periods:
        if start <= now <= end:
            text = (
                f"{header}\n\n"
                f"💡 ЗАРАЗ Є СВІТЛО\n"
                f"🟢 За графіком:\n"
                f"з {start.strftime('%H:%M')} до {end.strftime('%H:%M')}\n"
                f"🕒 Поточний час: {now.strftime('%H:%M')}"
            )
            await safe_send(context.bot, chat_id, text, reply_markup=main_keyboard())
            return

    for start, end in off_periods:
        if start <= now <= end:
            text = (
                f"{header}\n\n"
                f"🔌 ЗАРАЗ НЕМАЄ СВІТЛА\n"
                f"⛔ За графіком:\n"
                f"з {start.strftime('%H:%M')} до {end.strftime('%H:%M')}\n"
                f"🕒 Поточний час: {now.strftime('%H:%M')}"
            )
            await safe_send(context.bot, chat_id, text, reply_markup=main_keyboard())
            return
        

# --- ПЕРІОДИЧНА ПЕРЕВІРКА ---
async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        await check_queues(context.application)
    except NetworkError as e:
        print("🌐 Network error, retrying later:", e)
    except Exception as e:
        print("🔥 Unexpected error:", e)


# --- ОБРОБКА ПОМИЛОК ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    
    if isinstance(error, NetworkError):
        print("🌐 Network error occurred:", error)
    
    elif isinstance(error, TimedOut):
        print("⏰ Request timed out:", error)
    else:
        print("🔥 An unexpected error occurred:", error)
        
async def safe_send(bot, chat_id, text, reply_markup=None):
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except NetworkError as e:
        print(f"🌐 Network error sending to {chat_id}: {e}")
    except Exception as e:
        print(f"🔥 Unexpected error sending to {chat_id}: {e}")


# --- ГОЛОВНА ФУНКЦІЯ ---
def main():
    request = HTTPXRequest(connect_timeout=10, read_timeout=20)
    app = Application.builder().token(TOKEN).request(request).build()

    # Команди
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setqueue", setqueue))
    app.add_handler(CommandHandler("myqueue", myqueue))
    app.add_handler(CommandHandler("check", handle_queue_button))
    app.add_handler(CommandHandler("setnotify", setnotify))
    app.add_handler(CommandHandler("mynotify", mynotify))
    app.add_handler(CommandHandler("delqueue", delqueue))
    app.add_handler(CommandHandler("light", nowlight))

    # Обробка текстових повідомлень
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Періодична перевірка
    app.job_queue.run_repeating(periodic_check, interval=300, first=5)

    # Обробка помилок
    app.add_error_handler(error_handler)

    print("Бот запущено...")
    app.run_polling()


if __name__ == "__main__":
    main()
