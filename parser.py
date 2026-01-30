import httpx
import asyncio
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from config import CHANNEL_URL

# Використовуємо асинхронну функцію для отримання постів
async def get_last_posts(limit=15, retries=3, delay=5):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    # Створюємо асинхронний клієнт
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for attempt in range(1, retries + 1):
            try:
                if not CHANNEL_URL:
                    print("[Error] CHANNEL_URL не знайдено в конфігу")
                    return []
                
                # Асинхронний запит
                r = await client.get(CHANNEL_URL, timeout=15.0)
                r.raise_for_status()

                soup = BeautifulSoup(r.text, "html.parser")
                posts = soup.find_all("div", class_="tgme_widget_message_text")
                if not posts:
                    return []

                return [p.get_text("\n").strip() for p in posts[-limit:]]

            except (httpx.ConnectError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
                print(f"[Parser] Спроба {attempt}/{retries} не вдалася: {e}")
                if attempt < retries:
                    print(f"[Parser] Очікування {delay} секунд перед наступною спробою...")
                    await asyncio.sleep(delay) # Асинхронна пауза

    print("[Parser] Усі спроби отримання даних провалилися.")
    return []


# Тепер ця функція теж має бути async
async def get_queue_schedule(queue: str):
    posts = await get_last_posts() # Додаємо await

    for text in reversed(posts):
        # Покращений regex: прибираємо ^ та $, щоб знайти чергу навіть з емодзі
        pattern = rf"{re.escape(queue)}\s+(.*)"
        match = re.search(pattern, text)

        if match:
            times_part = match.group(1)
            # Підтримка форматів 8:00 та 08:00
            times = re.findall(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", times_part)
            if times:
                return times

    return None


async def get_queue_intervals(queue: str):
    times = await get_queue_schedule(queue) # Додаємо await
    if not times:
        return None

    intervals = []
    for t in times:
        try:
            start, end = t.split("-")
            intervals.append((start.strip(), end.strip()))
        except ValueError:
            continue
    return intervals


async def calculate_stats(queue: str):
    intervals = await get_queue_intervals(queue) # Додаємо await
    if not intervals:
        return None

    total_off = 0

    for start_str, end_str in intervals:
        start, start_shift = parse_time_safe(start_str)
        end, end_shift = parse_time_safe(end_str)

        if end_shift:
            end += timedelta(days=end_shift)

        if end < start:
            end += timedelta(days=1)

        total_off += int((end - start).total_seconds() // 60)

    total_on = 24 * 60 - total_off
    num_outages = len(intervals)

    off_hours, off_minutes = divmod(total_off, 60)
    on_hours, on_minutes = divmod(total_on, 60)

    return {
        "total_off": f"{off_hours} год {off_minutes} хв",
        "total_on": f"{on_hours} год {on_minutes} хв",
        "num_outages": num_outages
    }

    
def parse_time_safe(time_str: str):
    time_str = time_str.strip()
    try:
        if time_str == "24:00":
            t = datetime.strptime("00:00", "%H:%M")
            return t, 1
        else:
            return datetime.strptime(time_str, "%H:%M"), 0
    except ValueError:
        return datetime.strptime("00:00", "%H:%M"), 0
    
def extract_date_from_post(post_text):
    months_ua = {
        "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5,
        "червня": 6, "липня": 7, "серпня": 8, "вересня": 9,
        "жовтня": 10, "листопада": 11, "грудня": 12
    } 
    
    match = re.search(r"(\d{1,2})\s*(січня|лютого|березня|квітня|травня|червня|липня|серпня|вересня|жовтня|листопада|грудня)", post_text.lower())
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        return day, month_name
    return None, None