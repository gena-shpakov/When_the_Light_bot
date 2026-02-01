import httpx
import asyncio
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from config import CHANNEL_URL

async def get_last_posts(limit=10):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        try:
            r = await client.get(CHANNEL_URL, timeout=10.0)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            posts = soup.find_all("div", class_="tgme_widget_message_text")
            return [p.get_text("\n").strip() for p in posts[-limit:]]
        except Exception as e:
            print(f"[Parser Error] {e}")
            return []

async def get_queue_schedule(queue: str):
    posts = await get_last_posts()
    # Шукаємо в постах, починаючи з найновішого
    for text in reversed(posts):
        pattern = rf"(?:^|[\s\.])({re.escape(queue)})\s*[:\-–—\s]+(.*?)(?=\n|$|\d+\.\d+\s*[:\-–])"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

        if match:
            content = match.group(2)
            # Знаходимо всі часові інтервали типу 08:00-12:00 або 8:00-12:00
            times = re.findall(r"\d{1,2}:\d{2}\s*[-–—]\s*\d{1,2}:\d{2}", content)
            if times:
                return [t.replace(" ", "") for t in times]
    return None

async def get_queue_intervals(queue: str):
    times = await get_queue_schedule(queue)
    if not times: return None
    
    intervals = []
    for t in times:
        # Обробка різних видів тире
        parts = re.split(r"[-–—]", t)
        if len(parts) == 2:
            intervals.append((parts[0].strip(), parts[1].strip()))
    return intervals

async def calculate_stats(queue: str):
    intervals = await get_queue_intervals(queue)
    if not intervals: return None

    total_off_min = 0
    now = datetime.now()

    for s_str, e_str in intervals:
        try:
            # Використовуємо уніфіковану логіку парсингу часу
            start = datetime.strptime(s_str, "%H:%M")
            end = datetime.strptime(e_str, "%H:%M")
            if e_str == "24:00" or end <= start:
                duration = (timedelta(hours=24) - timedelta(hours=start.hour, minutes=start.minute))
                if e_str != "24:00":
                    duration += timedelta(hours=end.hour, minutes=end.minute)
            else:
                duration = end - start
            total_off_min += duration.total_seconds() / 60
        except: continue

    off_h, off_m = divmod(int(total_off_min), 60)
    on_h, on_m = divmod(24*60 - int(total_off_min), 60)

    return {
        "total_off": f"{off_h} год {off_m} хв",
        "total_on": f"{on_h} год {on_m} хв",
        "num_outages": len(intervals)
    }