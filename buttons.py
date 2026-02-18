from telegram import ReplyKeyboardMarkup, KeyboardButton

# Головне меню
def main_keyboard():
    keyboard = [
        [KeyboardButton("⚡ Перевірити чергу")],
        [KeyboardButton("📅 Коли світло?")],
        [KeyboardButton("📋 Мої черги")],
        [KeyboardButton("➕ Додати чергу")],
        [KeyboardButton("🗑 Видалити чергу")],
        [KeyboardButton("⏰ Налаштувати сповіщення")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Кнопки для вибору конкретної черги
def queues_keyboard(queues):
    if not queues:
        return main_keyboard()
        
    keyboard = []
    for q in queues:
        # Формуємо текст кнопки так само, як бот очікує в handle_message
        text = q["queue"] if q["name"] == "Без назви" else f"{q['queue']} — {q['name']}"
        keyboard.append([KeyboardButton(text)])

    keyboard.append([KeyboardButton("⬅ Назад")]) 
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Кнопки для вибору часу сповіщення
def notify_buttons():
    keyboard = [
        [KeyboardButton("5"), KeyboardButton("15"), KeyboardButton("30")],
        [KeyboardButton("60"), KeyboardButton("120")],
        [KeyboardButton("⬅ Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)