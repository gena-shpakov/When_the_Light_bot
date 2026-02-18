import os
import re
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from config import TOKEN
from data import (
    user_queues, user_notify_time, load_data, 
    get_queues, add_queue, remove_queue, set_notify_time
)
from parser import get_queue_intervals, calculate_stats, get_last_posts
from buttons import main_keyboard, queues_keyboard, notify_buttons

# --- FLASK SERVER (Для Render) ---
server = Flask('')

@server.route('/')
def home():
    return "Бот працює", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    server.run(host='0.0.0.0', port=port, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()

# --- ГЛОБАЛЬНІ ЗМІННІ ДЛЯ МОНІТОРИНГУ ---
last_post_hash = {}     
sent_notifications = {} 

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
async def safe_send(bot, chat_id, text, reply_markup=None):
    """Безпечна відправка повідомлень з обробкою помилок"""
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"🔥 Помилка відправки користувачу {chat_id}: {e}")

def parse_time_safe(time_str, now):
    """Перетворює рядок часу 'HH:MM' у об'єкт datetime"""
    if time_str == "24:00":
        return datetime.combine(now.date(), datetime.min.time()) + timedelta(days=1)
    t = datetime.strptime(time_str, "%H:%M")
    return datetime.combine(now.date(), t.time())

# --- ОБРОБНИКИ КОМАНД ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! ⚡ Я твій персональний менеджер світла.\n"
        "Я буду стежити за графіками та попереджати тебе про вимкнення.",
        reply_markup=main_keyboard()
    )

async def nowlight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    queues = get_queues(user_id)
    if not queues:
        await update.message.reply_text("Спочатку додай свою чергу!")
        return

    q_num = queues[0]["queue"]
    intervals = await get_queue_intervals(q_num)
    if not intervals:
        await update.message.reply_text("Дані відсутні.")
        return

    now = datetime.now()
    is_off = False
    next_change = None
    
    # Створюємо список всіх подій (початок і кінець)
    events = []
    for s_str, e_str in intervals:
        s_dt = parse_time_safe(s_str, now)
        e_dt = parse_time_safe(e_str, now)
        
        # Обробка інтервалів, що переходять через північ
        if e_dt <= s_dt:
            # Якщо зараз ніч і ми після початку, але перед кінцем
            if now < e_dt: 
                s_dt -= timedelta(days=1)
            else:
                e_dt += timedelta(days=1)
        
        events.append((s_dt, e_dt, s_str, e_str))

    # Перевіряємо поточний стан
    for s_dt, e_dt, s_str, e_str in events:
        if s_dt <= now < e_dt:
            is_off = True
            next_change = e_str # Світло з'явиться в кінці інтервалу
            break
    
    # Якщо світло є, шукаємо найближче вимкнення
    if not is_off:
        future_starts = [s_dt for s_dt, e_dt, s_str, e_str in events if s_dt > now]
        if future_starts:
            next_event_dt = min(future_starts)
            # Знаходимо рядок часу для цього dt
            next_change = [s_str for s_dt, e_dt, s_str, e_str in events if s_dt == next_event_dt][0]

    status = f"⚡ Черга {q_num}\n\n"
    if is_off:
        status += f"🔌 ЗАРАЗ НЕМАЄ СВІТЛА\n⛔ Очікується увімкнення о {next_change or 'невідомо'}"
    else:
        status += f"💡 ЗАРАЗ Є СВІТЛО\n🟢 Вимкнення за графіком о {next_change or 'немає за графіком'}"

    await update.message.reply_text(status, reply_markup=main_keyboard())

# --- ФОНОВА ПЕРЕВІРКА ТА РОЗСИЛКА ---
async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
    """Функція, що працює кожні 5 хвилин: перевіряє графіки та шле сповіщення"""
    app = context.application
    now = datetime.now()
    
    posts = await get_last_posts()
    if not posts: return
    
    latest_post = posts[-1]
    post_hash = hash(latest_post)

    for user_id, queues in user_queues.items():
        uid_int = int(user_id)
        notify_min = user_notify_time.get(user_id, 30)

        for q_data in queues:
            q_num = q_data["queue"]
            q_name = q_data["name"]
            user_q_key = f"{user_id}_{q_num}"

            if last_post_hash.get(user_q_key) != post_hash:
                intervals = await get_queue_intervals(q_num)
                if intervals:
                    times_text = "\n".join([f"• {s} — {e}" for s, e in intervals])
                    msg = f"⚡️ ОНОВЛЕНО ГРАФІК ({q_num} {q_name}):\n\n{times_text}"
                    await safe_send(app.bot, uid_int, msg)
                    last_post_hash[user_q_key] = post_hash

            intervals = await get_queue_intervals(q_num)
            if not intervals: continue

            for s_str, e_str in intervals:
                start_dt = parse_time_safe(s_str, now)
                
                if start_dt < now - timedelta(hours=12):
                    start_dt += timedelta(days=1)
                
                notify_time_target = start_dt - timedelta(minutes=notify_min)
                
                notif_key = f"{user_id}_{q_num}_{s_str}_{start_dt.strftime('%Y%m%d')}"

                if now >= notify_time_target and now < start_dt:
                    if notif_key not in sent_notifications:
                        alert = f"⏰ Через {notify_min} хв СВІТЛО БУДЕ ВИМКНЕНО!\nЧерга: {q_num} ({q_name})"
                        await safe_send(app.bot, uid_int, alert)
                        sent_notifications[notif_key] = True

        keys_to_delete = [k for k, v in sent_notifications.items() if k.startswith(user_id) and "some_date_logic" in k]

# --- ОБРОБКА ПОВІДОМЛЕНЬ МЕНЮ ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    
    if text == "⬅ Назад":
        context.user_data["action"] = None
        await update.message.reply_text("Головне меню:", reply_markup=main_keyboard())
        return
    
    if text == "⚡ Перевірити чергу":
        user_id = str(update.effective_user.id)
        queues = get_queues(user_id)
        if not queues:
            await update.message.reply_text("Твій список порожній. Додай чергу, щоб перевірити її статус.", reply_markup=main_keyboard())
            return
        
        q_num = queues[0]["queue"]
        intervals = await get_queue_intervals(q_num)
        stats = await calculate_stats(q_num)
        
        if not intervals or stats is None:
            await update.message.reply_text(
                f"⚠️ **Дані тимчасово недоступні.**\n\n"
                "Не вдалося отримати графік. Можливі причини:\n"
                "• Проблеми зі з'єднанням (як у твоїй помилці NetworkError)\n"
                "• Обленерго ще не оновило пост у Telegram\n"
                "• Змінився формат повідомлень на каналі\n\n"
                "Спробуй натиснути кнопку ще раз через хвилину.",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
            return
        
        schedule_text = "\n".join([f"• {s} — {e}" for s, e in intervals])
        
        response = (
            f"📅 *Графік на {stats['date']}* (черга {q_num}):\n\n"
            f"{schedule_text}\n\n"
            f"📊 *Статистика:*\n"
            f"🔌 Без світла: {stats['total_off']}\n"
            f"💡 Зі світлом: {stats['total_on']}\n"
            f"🔄 Кількість вимкнень: {stats['num_outages']}"
        )
        await update.message.reply_text(response, parse_mode="Markdown", reply_markup=main_keyboard())
        return

    if text == "➕ Додати чергу":
        context.user_data["action"] = "add"
        await update.message.reply_text("Введи чергу (наприклад: 4.1 або 4.1 Дім)", parse_mode="Markdown")
        return
    
    elif text == "🗑 Видалити чергу":
        queues = get_queues(user_id)
        if not queues:
            await update.message.reply_text("Немає чого видаляти")
            return
        context.user_data["action"] = "del"
        await update.message.reply_text("Яку чергу видалити?", reply_markup=queues_keyboard(queues))
        return

    elif text == "📋 Мої черги":
        queues = get_queues(user_id)
        if not queues:
            await update.message.reply_text("Твій список порожній.")
        else:
            res = "🔢 Твої черги:*\n\n" + "\n".join([f"• {q['queue']} ({q['name']})" for q in queues])
            await update.message.reply_text(res, parse_mode="Markdown", reply_markup=queues_keyboard(queues))
            return

    elif text == "⏰ Налаштувати сповіщення":
        await update.message.reply_text("Обери час сповіщення:", reply_markup=notify_buttons())
        return

    elif text in ["5", "15", "30", "60", "120"]:
        set_notify_time(user_id, int(text))
        await update.message.reply_text(f"✅ Готово! Буду попереджати за {text} хв.")
        return

    elif text == "📅 Коли світло?":
        await nowlight(update, context)
        return
    
    # Логіка введення даних після натискання кнопок
    action = context.user_data.get("action")
    if action == "add":
        context.user_data["action"] = None
        parts = text.text.split(maxsplit=1)
        if add_queues(user_id, parts[0], parts[1] if len(parts) > 1 else "Без назви"):
            await update.message.reply_text("✅ Додано успішно!", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ Помилка: черга вже є або невірний формат")

    elif action == "del":
        context.user_data["action"] = None
        queue_to_del = text.split()[0]
        if remove_queue(user_id, queue_to_del):
            await update.message.reply_text(f"🗑 Видалено чергу {queue_to_del}", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ Чергу не знайдено")

# --- ЗАПУСК БОТА ---
def main():
    print("🔋 Завантаження даних з Supabase...")
    load_data() 
    
    request = HTTPXRequest(connect_timeout=15, read_timeout=20)
    application = Application.builder().token(TOKEN).request(request).build()

    # Реєстрація обробників
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Налаштування періодичної перевірки (кожні 300 сек)
    if application.job_queue:
        application.job_queue.run_repeating(periodic_check, interval=300, first=10)

    print("🚀 Бот запущений та готовий до роботи!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()