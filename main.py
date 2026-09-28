import os
import feedparser
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Список RSS-лент российских новостей
RSS_URLS = [
    ("Lenta.ru", "https://lenta.ru/rss/top7"),
    ("АиФ", "https://aif.ru/rss/news.php"),
    ("RT", "https://rt.com/rss/news/"),
]

# Сколько новостей брать с каждой ленты
NEWS_PER_FEED = 3

def fetch_news():
    blocks = []
    for source_name, url in RSS_URLS:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:NEWS_PER_FEED]:
            title = entry.get("title", "Без заголовка").strip()
            link = entry.get("link", "#")
            items.append(f'• <a href="{link}">{title}</a>')
        if items:
            blocks.append(f"<b>{source_name}</b>\n" + "\n".join(items))
    return blocks

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code != 200:
        print(f"Ошибка отправки: {r.status_code} {r.text}")
    else:
        print("OK")

def main():
    blocks = fetch_news()
    if not blocks:
        print("Новости не найдены.")
        return

    # Время по Москве
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    header = f"<b>📰 Сводка новостей · {msk.strftime('%d.%m.%Y %H:%M')} МСК</b>"

    message = header + "\n\n" + "\n\n".join(blocks)

    # Лимит Telegram — 4096 символов
    if len(message) > 4000:
        message = message[:4000] + "\n\n<i>…обрезано</i>"

    send_to_telegram(message)

if __name__ == "__main__":
    main()
