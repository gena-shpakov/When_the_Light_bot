import httpx
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import time
from config import CHANNEL_URL

async def get_last_posts(limit=10):
    # Додаємо мітку часу, щоб Telegram не видавав закешовану сторінку
    url = f"https://t.me/s/{CHANNEL_URL.split('/')[-1]}?t={int(time.time())}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        try:
            r = await client.get(url, timeout=10.0)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            posts = soup.find_all("div", class_="tgme_widget_message_text")
            return [p.get_text("\n").strip() for p in posts[-limit:]]
        except (httpx.ConnectError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
            print(f"[Network Error] Немає зв'язку з Telegram: {e}")
            return[]
        except Exception as e:
            print(f"[Parser Error] {e}")
            return []

def normalize_time(t_str):
    """Додає нуль попереду, якщо час типу 8:00 -> 08:00"""
    t_str = t_str.strip().replace(".", ":")
    if len(t_str.split(":")[0]) == 1:
        t_str = "0" + t_str
    return t_str

def extract_date_info(text):
    now = datetime.now()
    match = re.search(r"(\d{2})\.(\d{2})", text)
    
    if match:
        day, month = map(int, match.groups())
        try:
            target_date = datetime(now.year, month, day)
            if target_date.month == 1 and now.month == 12:
                target_date = target_date.replace(year=now.year + 1)
                
            if target_date.date() == now.date():
                return f"сьогодні ({day:02d}.{month:02d})"
            elif target_date.date() == (now.date() + timedelta(days=1)):
                return f"ЗАВТРА ({day:02d}.{month:02d})"
            else:
                return f"{day:02d}.{month:02d}"
        except:
            return f"{day:02d}.{month:02d}"
        
    if "завтра" in text.lower(): return "ЗАВТРА"
    if "сьогодні" in text.lower(): return "сьогодні"
    return "сьогодні"

async def get_queue_data(queue: str):
    posts = await get_last_posts()
    for text in reversed(posts):
        lines = text.split('\n')
        for line in lines:
            if queue in line:
                times = re.findall(r"(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})", line)
                if times:
                    intervals = [(normalize_time(s), normalize_time(e)) for s, e in times]
                    return intervals, text # Повертаємо і графік, і текст посту
    return None, None

async def get_queue_intervals(queue: str):
    posts = await get_last_posts()
    for text in reversed(posts):
        # Шукаємо номер черги і все, що йде після нього до наступної черги або кінця
        lines = text.split('\n')
        for line in lines:
            if queue in line:
                # Шукаємо всі часові пари 00:00-00:00 у цьому рядку
                times = re.findall(r"(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})", line)
                if times:
                    return [(normalize_time(s), normalize_time(e)) for s, e in times]
    return None

async def calculate_stats(queue: str):
    intervals, full_text = await get_queue_data(queue)
    if not intervals: return None

    total_off_min = 0
    for s_str, e_str in intervals:
        try:
            # Обробка 24:00 вручну
            s_h, s_m = map(int, s_str.split(':'))
            if e_str.startswith("24"):
                e_h, e_m = 24, 0
            else:
                e_h, e_m = map(int, e_str.split(':'))
            
            duration = (e_h * 60 + e_m) - (s_h * 60 + s_m)
            if duration < 0: duration += 1440 # Якщо перехід через ніч
            
            total_off_min += duration
        except: continue

    off_h, off_m = divmod(int(total_off_min), 60)
    on_h, on_m = divmod(1440 - int(total_off_min), 60)
    
    date_label = extract_date_info(full_text)

    return {
        "total_off": f"{off_h} год {off_m} хв",
        "total_on": f"{on_h} год {on_m} хв",
        "num_outages": len(intervals),
        "date": date_label
    }