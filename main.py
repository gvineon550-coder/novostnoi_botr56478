import os
import re
import json
import time
import html
import feedparser
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
METNO_EMAIL = os.environ.get("METNO_EMAIL", "")  # для met.no (опционально)

RSS_URLS = [
    ("📰 Lenta.ru", "https://lenta.ru/rss/top7"),
    ("✍️ АиФ",     "https://aif.ru/rss/news.php"),
    ("🌐 RT",      "https://www.rt.com/rss/news/"),
]

NEWS_PER_FEED = 2
DEDUP_HOURS = 12
DIVIDER = "━━━━━━━━━━━━━━━"
STATE_DIR = "state"
STATE_FILE = os.path.join(STATE_DIR, "sent.json")

# Нальчик
NALCHIK_LAT = 43.4949918
NALCHIK_LON = 43.6045133

WEATHER_CODES = {
    0: "☀️ Ясно", 1: "🌤 Преим. ясно", 2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно", 45: "🌫 Туман", 48: "🌫 Туман с изморозью",
    51: "🌦 Морось", 53: "🌦 Морось", 55: "🌦 Морось",
    61: "🌧 Небольшой дождь", 63: "🌧 Дождь", 65: "🌧 Сильный дождь",
    71: "🌨 Небольшой снег", 73: "🌨 Снег", 75: "🌨 Сильный снег",
    80: "🌦 Ливни", 81: "🌦 Ливни", 82: "⛈ Сильные ливни",
    95: "⛈ Гроза", 96: "⛈ Гроза с градом", 99: "⛈ Гроза с градом",
}


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_image(entry):
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media and isinstance(media, list):
            for m in media:
                if m.get("url"):
                    return m["url"]
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image") and enc.get("href"):
            return enc["href"]
    for key in ("summary", "description"):
        raw = entry.get(key, "")
        m = re.search(r'<img[^>]+src="([^"]+)"', raw or "")
        if m:
            return m.group(1)
    return None


def shorten(text: str, limit: int = 280) -> str:
    text = strip_html(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def format_time(entry) -> str:
    pp = entry.get("published_parsed")
    if not pp:
        return ""
    try:
        dt = datetime(*pp[:6], tzinfo=timezone.utc) + timedelta(hours=3)
        return dt.strftime("%H:%M")
    except Exception:
        return ""


def entry_id(entry) -> str:
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def load_seen() -> dict:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            now = time.time()
            return {k: now for k in data}
        return data
    except Exception:
        return {}


def save_seen(seen: dict) -> None:
    now = time.time()
    pruned = {k: v for k, v in seen.items() if now - v < 24 * 3600}
    if len(pruned) > 2000:
        pruned = dict(sorted(pruned.items(), key=lambda x: -x[1])[:2000])
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(pruned, f)


def is_seen(seen: dict, eid: str) -> bool:
    ts = seen.get(eid)
    return bool(ts) and (time.time() - ts) < DEDUP_HOURS * 3600


def tg(method: str, payload: dict):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"{method} fail: {r.status_code} {r.text[:200]}", flush=True)
            return None
        return r.json()
    except Exception as e:
        print(f"{method} exception: {e}", flush=True)
        return None


# ---------- ПОГОДА: НЕСКОЛЬКО ИСТОЧНИКОВ ----------

def weather_from_open_meteo():
    """Источник 1: Open-Meteo (без ключа)."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={NALCHIK_LAT}&longitude={NALCHIK_LON}"
            f"&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            f"&timezone=Europe/Moscow"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        d = r.json()["current"]
        temp = round(d["temperature_2m"])
        feels = round(d["apparent_temperature"])
        code = d["weather_code"]
        wind = round(d["wind_speed_10m"])
        desc = WEATHER_CODES.get(code, "🌡 —")
        return f"{desc} · {temp}°C (ощущается {feels}°C), ветер {wind} м/с", "Open-Meteo"
    except Exception as e:
        print(f"weather open-meteo fail: {e}", flush=True)
        return None


def weather_from_wttr():
    """Источник 2: wttr.in (без ключа, JSON-формат)."""
    try:
        url = f"https://wttr.in/{NALCHIK_LAT},{NALCHIK_LON}?format=j1"
        headers = {"User-Agent": "curl/8.0"}  # wttr.in любит curl
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        current = data["current_condition"][0]
        temp = current["temp_C"]
        feels = current["FeelsLikeC"]
        wind = current["windspeedKmph"]
        desc_en = current["weatherDesc"][0]["value"]
        # простой перевод основных фраз
        mapping = {
            "Sunny": "☀️ Ясно",
            "Clear": "☀️ Ясно",
            "Partly cloudy": "⛅ Переменная облачность",
            "Cloudy": "☁️ Облачно",
            "Overcast": "☁️ Пасмурно",
            "Mist": "🌫 Туман",
            "Fog": "🌫 Туман",
            "Light rain": "🌦 Небольшой дождь",
            "Rain": "🌧 Дождь",
            "Heavy rain": "🌧 Сильный дождь",
            "Light snow": "🌨 Небольшой снег",
            "Snow": "🌨 Снег",
            "Thunderstorm": "⛈ Гроза",
        }
        desc = mapping.get(desc_en, desc_en)
        return f"{desc} · {temp}°C (ощущается {feels}°C), ветер {wind} км/ч", "wttr.in"
    except Exception as e:
        print(f"weather wttr fail: {e}", flush=True)
        return None


def weather_from_metno():
    """Источник 3: met.no (нужен email в User-Agent)."""
    if not METNO_EMAIL:
        return None
    try:
        url = (
            "https://api.met.no/weatherapi/locationforecast/2.0/compact"
            f"?lat={NALCHIK_LAT}&lon={NALCHIK_LON}"
        )
        headers = {"User-Agent": f"NewsBot/1.0 {METNO_EMAIL}"}
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        ts = data["properties"]["timeseries"][0]
        details = ts["data"]["instant"]["details"]
        temp = round(details["air_temperature"])
        wind = round(details["wind_speed"] * 3.6)  # м/с → км/ч
        # символ погоды из next_1_hours
        symbol = ""
        next1 = ts["data"].get("next_1_hours", {})
        if next1:
            symbol = next1.get("summary", {}).get("symbol_code", "")
        # простая интерпретация symbol_code
        desc = "🌡 —"
        if "clearsky" in symbol:
            desc = "☀️ Ясно"
        elif "fair" in symbol:
            desc = "🌤 Преим. ясно"
        elif "partlycloudy" in symbol:
            desc = "⛅ Переменная облачность"
        elif "cloudy" in symbol:
            desc = "☁️ Облачно"
        elif "rain" in symbol:
            desc = "🌧 Дождь"
        elif "snow" in symbol:
            desc = "🌨 Снег"
        elif "thunder" in symbol:
            desc = "⛈ Гроза"
        return f"{desc} · {temp}°C, ветер {wind} км/ч", "met.no"
    except Exception as e:
        print(f"weather metno fail: {e}", flush=True)
        return None


def fetch_weather():
    """Пробует источники по очереди. Возвращает (текст, источник) или None."""
    for func in (weather_from_open_meteo, weather_from_wttr, weather_from_metno):
        result = func()
        if result:
            return result
    return None


# ---------- ОСТАЛЬНЫЕ БЛОКИ ----------

def fetch_rates() -> str:
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=15)
        d = r.json()["Valute"]
        usd = round(d["USD"]["Value"], 2)
        eur = round(d["EUR"]["Value"], 2)
        cny = round(d["CNY"]["Value"], 2)
        return f"💵 USD {usd} ₽ · 💶 EUR {eur} ₽ · 🇨🇳 CNY {cny} ₽"
    except Exception as e:
        print(f"rates fail: {e}", flush=True)
        return ""


def fetch_crypto() -> str:
    try:
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum&vs_currencies=usd"
        )
        r = requests.get(url, timeout=15)
        d = r.json()
        btc = d["bitcoin"]["usd"]
        eth = d["ethereum"]["usd"]
        return f"₿ BTC ${btc:,.0f} · Ξ ETH ${eth:,.0f}"
    except Exception as e:
        print(f"crypto fail: {e}", flush=True)
        return ""


def fetch_quote() -> str:
    try:
        r = requests.get(
            "https://api.forismatic.com/api/1.0/",
            params={"method": "getQuote", "format": "json", "lang": "ru"},
            timeout=15,
        )
        d = r.json()
        text = d.get("quoteText", "").strip()
        author = d.get("quoteAuthor", "").strip()
        if text:
            return f"«{text}» — {author}" if author else f"«{text}»"
        return ""
    except Exception as e:
        print(f"quote fail: {e}", flush=True)
        return ""


def fetch_history() -> str:
    try:
        now = datetime.now(timezone.utc)
        url = f"https://api.wikimedia.org/feed/v1/wikipedia/ru/onthisday/events/{now.month}/{now.day}"
        r = requests.get(url, timeout=15)
        events = r.json().get("events", [])
        if not events:
            return ""
        ev = events[0]
        text = strip_html(ev.get("text", ""))
        year = ev.get("year", "")
        return f"{year} — {text}" if year else text
    except Exception as e:
        print(f"history fail: {e}", flush=True)
        return ""


def send_header() -> None:
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    lines = [
        f"<b>📰 Главные новости</b>",
        f"<i>{msk.strftime('%d.%m.%Y · %H:%M')} МСК</i>",
        "",
    ]

    weather = fetch_weather()
    if weather:
        text, source = weather
        lines.append(f"<b>🌤 Погода в Нальчике</b> <i>({source})</i>")
        lines.append(text)
        lines.append("")

    rates = fetch_rates()
    if rates:
        lines.append(f"<b>💱 Курсы ЦБ РФ</b>")
        lines.append(rates)
        lines.append("")

    crypto = fetch_crypto()
    if crypto:
        lines.append(f"<b>🪙 Криптовалюты</b>")
        lines.append(crypto)
        lines.append("")

    quote = fetch_quote()
    if quote:
        lines.append(f"<b>💬 Цитата дня</b>")
        lines.append(f"<i>{quote}</i>")
        lines.append("")

    history = fetch_history()
    if history:
        lines.append(f"<b>📅 В этот день</b>")
        lines.append(history)

    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
    })


def send_source_divider(source_name: str) -> None:
    text = f"{DIVIDER}\n<b>{source_name}</b>\n{DIVIDER}"
    tg("sendMessage", {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})


def send_item(item: dict) -> None:
    title = html.escape(item["title"])
    summary = html.escape(item["summary"])
    time_part = f"  🕐 <i>{item['time']}</i>" if item["time"] else ""
    caption = f"<b>{title}</b>{time_part}"
    if summary:
        caption += f"\n\n{summary}"
    if len(caption) > 1000:
        caption = caption[:1000] + "…"

    reply_markup = {
        "inline_keyboard": [[
            {"text": "Читать полностью →", "url": item["link"]}
        ]]
    }

    if item["image"]:
        res = tg("sendPhoto", {
            "chat_id": CHAT_ID,
            "photo": item["image"],
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        })
        if res and res.get("ok"):
            return

    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": reply_markup,
    })


def fetch_groups(seen: dict):
    groups = []
    for source_name, url in RSS_URLS:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries:
            if len(items) >= NEWS_PER_FEED:
                break
            eid = entry_id(entry)
            if not eid or is_seen(seen, eid):
                continue
            items.append({
                "id": eid,
                "source": source_name,
                "title": strip_html(entry.get("title", "Без заголовка")),
                "link": entry.get("link", "#"),
                "image": extract_image(entry),
                "summary": shorten(entry.get("summary") or entry.get("description") or ""),
                "time": format_time(entry),
            })
        if items:
            groups.append((source_name, items))
    return groups


def main() -> None:
    print(">>> START", flush=True)
    seen = load_seen()
    print(f">>> seen={len(seen)}", flush=True)

    groups = fetch_groups(seen)
    total = sum(len(items) for _, items in groups)
    print(f">>> new items: {total}", flush=True)

    send_header()

    if not groups:
        print(">>> nothing new, header sent", flush=True)
        return

    now = time.time()
    for source_name, items in groups:
        send_source_divider(source_name)
        for item in items:
            print(f">>> {item['source']} | {item['title'][:60]}", flush=True)
            send_item(item)
            seen[item["id"]] = now

    save_seen(seen)
    print(">>> DONE", flush=True)


if __name__ == "__main__":
    main()
