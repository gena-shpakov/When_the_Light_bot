import json
import os

QUEUES_FILE = "user_queues.json"
NOTIFY_FILE = "user_notify_time.json"


# --------- ЧЕРГИ ---------

if os.path.exists(QUEUES_FILE):
    with open(QUEUES_FILE, "r", encoding="utf-8") as f:
        user_queues = json.load(f)
else:
    user_queues = {}


def save_queues():
    with open(QUEUES_FILE, "w", encoding="utf-8") as f:
        json.dump(user_queues, f, ensure_ascii=False, indent=2)


def get_queues(user_id: str):
    """
    Повертає список черг користувача:
    [
      {"queue": "4.1", "name": "Дім"},
      {"queue": "5.2", "name": "Робота"}
    ]
    """
    return user_queues.get(user_id, [])


def add_queue(user_id: str, queue: str, name: str):
    if user_id not in user_queues:
        user_queues[user_id] = []

    # Перевіряємо, чи така черга вже існує
    for q in user_queues[user_id]:
        if q["queue"] == queue:
            return False

    user_queues[user_id].append({
        "queue": queue,
        "name": name
    })
    save_queues()
    return True


def remove_queue(user_id: str, queue: str):
    if user_id not in user_queues:
        return False

    new_list = [q for q in user_queues[user_id] if q["queue"] != queue]

    if len(new_list) == len(user_queues[user_id]):
        return False 

    user_queues[user_id] = new_list
    save_queues()
    return True


# --------- СПОВІЩЕННЯ ---------

if os.path.exists(NOTIFY_FILE):
    with open(NOTIFY_FILE, "r", encoding="utf-8") as f:
        user_notify_time = json.load(f)
else:
    user_notify_time = {}


def save_notify_time():
    with open(NOTIFY_FILE, "w", encoding="utf-8") as f:
        json.dump(user_notify_time, f, ensure_ascii=False, indent=2)


def get_notify_time(user_id: str, default: int = 30):
    return int(user_notify_time.get(user_id, default))


def set_notify_time(user_id: str, minutes: int):
    user_notify_time[user_id] = minutes
    save_notify_time()
