import os
import sys
import feedparser
import requests
from datetime import datetime, timezone, timedelta

print(">>> SCRIPT STARTED", flush=True)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

print(f">>> TOKEN len={len(TELEGRAM_TOKEN or '')} prefix={str(TELEGRAM_TOKEN)[:12]}", flush=True)
print(f">>> CHAT_ID = {CHAT_ID}", flush=True)

RSS_URLS = [
    ("Lenta.ru", "https://lenta.ru/rss/top7"),
    ("АиФ", "https://aif.ru/rss/news.php"),
    ("RT", "https://www.rt.com/rss/news/"),
]

NEWS_PER_FEED = 3

def fetch_news():
    blocks = []
    for source_name, url in RSS_URLS:
        print(f">>> FETCH {source_name} {url}", flush=True)
        try:
            feed = feedparser.parse(url)
            print(f">>>   entries={len(feed.entries)} status={feed.get('status')}", flush=True)
        except Exception as e:
            print(f">>>   EXCEPTION: {e}", flush=True)
            continue
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
    print(f">>> SEND url_prefix={url[:60]}", flush=True)
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        print(f">>> RESPONSE {r.status_code} {r.text[:200]}", flush=True)
    except Exception as e:
        print(f">>> SEND EXCEPTION: {e}", flush=True)

def main():
    print(">>> MAIN START", flush=True)
    blocks = fetch_news()
    print(f">>> BLOCKS collected = {len(blocks)}", flush=True)
    if not blocks:
        print(">>> Новости не найдены, отправляю тестовое сообщение", flush=True)
        send_to_telegram("Тест: RSS пустой, но связь есть.")
        return

    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    header = f"<b>📰 Сводка новостей · {msk.strftime('%d.%m.%Y %H:%M')} МСК</b>"
    message = header + "\n\n" + "\n\n".join(blocks)
    if len(message) > 4000:
        message = message[:4000] + "\n\n<i>…обрезано</i>"

    send_to_telegram(message)
    print(">>> DONE", flush=True)

if __name__ == "__main__":
    main()
