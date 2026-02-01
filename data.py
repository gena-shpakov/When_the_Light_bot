import os
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

# Ініціалізація клієнта Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Локальний кеш для швидкості (щоб не робити запит до бази при кожному кліку)
user_queues = {}
user_notify_time = {}

# --------- СИНХРОНІЗАЦІЯ З БАЗОЮ ---------

def load_data():
    """Завантажує всі дані з Supabase в оперативну пам'ять"""
    try:
        response = supabase.table("users").select("*").execute()
        for row in response.data:
            uid = str(row.get('user_id'))
            user_queues[uid] = row.get('queues', [])
            user_notify_time[uid] = row.get('notify_time', 30)
        print(f"✅ Дані синхронізовано: {len(response.data)} користувачів")
    except Exception as e:
        print(f"❌ Помилка завантаження бази: {e}")

def save_user_to_db(user_id: str):
    """Зберігає дані конкретного користувача в Supabase"""
    user_id = str(user_id)
    data = {
        "user_id": user_id,
        "queues": user_queues.get(user_id, []),
        "notify_time": user_notify_time.get(user_id, 30)
    }
    try:
        supabase.table("users").upsert(data).execute()
    except Exception as e:
        print(f"❌ Помилка збереження в DB для {user_id}: {e}")

# --------- ФУНКЦІЇ ЧЕРГ ---------

def get_queues(user_id: str):
    return user_queues.get(str(user_id), [])

def add_queue(user_id: str, queue: str, name: str):
    user_id = str(user_id)
    if user_id not in user_queues:
        user_queues[user_id] = []

    for q in user_queues[user_id]:
        if q["queue"] == queue:
            return False

    user_queues[user_id].append({"queue": queue, "name": name})
    save_user_to_db(user_id) # Замість запису у файл
    return True

def remove_queue(user_id: str, queue: str):
    user_id = str(user_id)
    if user_id not in user_queues:
        return False

    original_len = len(user_queues[user_id])
    user_queues[user_id] = [q for q in user_queues[user_id] if q["queue"] != queue]

    if len(user_queues[user_id]) == original_len:
        return False 

    save_user_to_db(user_id)
    return True

# --------- ФУНКЦІЇ СПОВІЩЕНЬ ---------

def get_notify_time(user_id: str, default: int = 30):
    return int(user_notify_time.get(str(user_id), default))

def set_notify_time(user_id: str, minutes: int):
    user_id = str(user_id)
    user_notify_time[user_id] = minutes
    save_user_to_db(user_id)

# Функції для сумісності (якщо вони десь викликаються)
def save_queues(): pass
def save_notify_time(): pass