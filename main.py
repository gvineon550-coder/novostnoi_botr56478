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
METNO_EMAIL = os.environ.get("METNO_EMAIL", "")

# --- ИСТОЧНИКИ ---
RSS_URLS = [
    ("📰 Lenta.ru",       "https://lenta.ru/rss/news"),
    ("✍️ АиФ",            "https://aif.ru/rss/news.php"),
    ("📡 РИА Новости",    "https://ria.ru/export/rss2/archive/index.xml"),
    ("🎬 Кино и сериалы", "https://wcinema.ru/rss/feed/film"),
]

NEWS_PER_FEED = 2
DEDUP_HOURS = 12
DIVIDER = "━━━━━━━━━━━━━━━"
STATE_DIR = "state"
STATE_FILE = os.path.join(STATE_DIR, "sent.json")

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

CATEGORIES = [
    ("⚔️", ["сво", "фронт", "удар", "обстрел", "боевик", "штурм", "дрон", "бпла"]),
    ("🏛", ["путин", "кремль", "госдума", "министр", "правительств", "совет федерации",
             "закон", "указ", "депутат", "губернатор", "парламент"]),
    ("💰", ["рубл", "доллар", "евро", "цб ", "центробанк", "биржа", "акции", "курс",
             "инфляц", "налог", "бюджет", "цена", "нефть", "газ"]),
    ("⚽", ["матч", "гол ", "чемпионат", "сборная", "олимп", "футбол", "хокке",
             "тренер", "клуб", "спортсмен"]),
    ("🚨", ["пожар", "дтп", "взрыв", "погиб", "чп ", "авари", "катастроф", "теракт",
             "пострадав", "спасател"]),
    ("🎬", ["фильм", "премьер", "выставк", "концерт", "актер", "актрис", "режиссер",
             "фестивал", "театр", "музык", "певец", "звезд", "сериал"]),
    ("💻", ["ии ", "нейросет", "apple", "google", "microsoft", "смартфон", "приложен",
             "гаджет", "телефон", "chatgpt", "технолог", "интернет"]),
    ("🌍", ["сша", "украин", "европ", "нато", "китай", "трамп", "байден", "израил",
             "палестин", "сирия", "иран"]),
    ("🌦", ["погод", "циклон", "антициклон", "мороз", "жара", "снегопад", "ливн",
             "ураган", "шторм", "наводнен"]),
]


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


def detect_category(title: str) -> str:
    low = title.lower()
    for emoji, keywords in CATEGORIES:
        if any(kw in low for kw in keywords):
            return emoji
    return "📌"


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


# ---------- ПОГОДА (3 источника) ----------

def weather_from_open_meteo():
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
        desc = WEATHER_CODES.get(d["weather_code"], "🌡 —")
        wind = round(d["wind_speed_10m"])
        return f"{desc} · {temp}°C (ощущается {feels}°C), ветер {wind} м/с", "Open-Meteo"
    except Exception as e:
        print(f"weather open-meteo fail: {e}", flush=True)
        return None


def weather_from_wttr():
    try:
        url = f"https://wttr.in/{NALCHIK_LAT},{NALCHIK_LON}?format=j1"
        r = requests.get(url, headers={"User-Agent": "curl/8.0"}, timeout=20)
        r.raise_for_status()
        cur = r.json()["current_condition"][0]
        mapping = {
            "Sunny": "☀️ Ясно", "Clear": "☀️ Ясно",
            "Partly cloudy": "⛅ Переменная облачность",
            "Cloudy": "☁️ Облачно", "Overcast": "☁️ Пасмурно",
            "Mist": "🌫 Туман", "Fog": "🌫 Туман",
            "Light rain": "🌦 Небольшой дождь", "Rain": "🌧 Дождь",
            "Heavy rain": "🌧 Сильный дождь",
            "Light snow": "🌨 Небольшой снег", "Snow": "🌨 Снег",
            "Thunderstorm": "⛈ Гроза",
        }
        desc = mapping.get(cur["weatherDesc"][0]["value"], cur["weatherDesc"][0]["value"])
        return (
            f"{desc} · {cur['temp_C']}°C (ощущается {cur['FeelsLikeC']}°C), "
            f"ветер {cur['windspeedKmph']} км/ч",
            "wttr.in",
        )
    except Exception as e:
        print(f"weather wttr fail: {e}", flush=True)
        return None


def weather_from_metno():
    if not METNO_EMAIL:
        return None
    try:
        url = (
            "https://api.met.no/weatherapi/locationforecast/2.0/compact"
            f"?lat={NALCHIK_LAT}&lon={NALCHIK_LON}"
        )
        r = requests.get(url, headers={"User-Agent": f"NewsBot/1.0 {METNO_EMAIL}"}, timeout=20)
        r.raise_for_status()
        ts = r.json()["properties"]["timeseries"][0]
        d = ts["data"]["instant"]["details"]
        temp = round(d["air_temperature"])
        wind = round(d["wind_speed"] * 3.6)
        symbol = ts["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", "")
        desc = "🌡 —"
        if "clearsky" in symbol: desc = "☀️ Ясно"
        elif "fair" in symbol: desc = "🌤 Преим. ясно"
        elif "partlycloudy" in symbol: desc = "⛅ Переменная облачность"
        elif "cloudy" in symbol: desc = "☁️ Облачно"
        elif "rain" in symbol: desc = "🌧 Дождь"
        elif "snow" in symbol: desc = "🌨 Снег"
        elif "thunder" in symbol: desc = "⛈ Гроза"
        return f"{desc} · {temp}°C, ветер {wind} км/ч", "met.no"
    except Exception as e:
        print(f"weather metno fail: {e}", flush=True)
        return None


def fetch_weather():
    for func in (weather_from_open_meteo, weather_from_wttr, weather_from_metno):
        result = func()
        if result:
            return result
    return None


# ---------- КУРСЫ / КРИПТА / ЦИТАТА / ИСТОРИЯ ----------

def fetch_rates() -> str:
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=15)
        d = r.json()["Valute"]
        parts = []
        for code, flag in (("USD", "💵"), ("EUR", "💶"), ("CNY", "🇨🇳")):
            v = d[code]["Value"]
            prev = d[code]["Previous"]
            delta = v - prev
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
            parts.append(f"{flag} {round(v, 2)} ₽ {arrow}")
        return " · ".join(parts)
    except Exception as e:
        print(f"rates fail: {e}", flush=True)
        return ""


def fetch_crypto() -> str:
    try:
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
        )
        r = requests.get(url, timeout=15)
        d = r.json()
        parts = []
        for key, sym in (("bitcoin", "₿ BTC"), ("ethereum", "Ξ ETH")):
            price = d[key]["usd"]
            chg = d[key].get("usd_24h_change", 0)
            arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "=")
            parts.append(f"{sym} ${price:,.0f} {arrow}{abs(chg):.1f}%")
        return " · ".join(parts)
    except Exception as e:
        print(f"crypto fail: {e}", flush=True)
        return ""


def fetch_quote() -> str:
    """💬 Цитата дня — через Викицитатник (русский)."""
    try:
        r = requests.get(
            "https://ru.wikiquote.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "list": "random",
                "rnnamespace": 0,
                "rnlimit": 1,
            },
            headers={"User-Agent": "NewsDigestBot/1.0"},
            timeout=15,
        )
        data = r.json()
        page_title = data["query"]["random"][0]["title"]

        r2 = requests.get(
            "https://ru.wikiquote.org/w/api.php",
            params={
                "action": "parse",
                "format": "json",
                "page": page_title,
                "prop": "wikitext",
                "section": 0,
            },
            headers={"User-Agent": "NewsDigestBot/1.0"},
            timeout=15,
        )
        wikitext = r2.json()["parse"]["wikitext"]["*"]
        quotes = re.findall(r"\*(.*)", wikitext)
        if quotes:
            quote_text = strip_html(quotes[0]).strip()
            if len(quote_text) > 10:
                return f"«{quote_text}»"
        return ""
    except Exception as e:
        print(f"quote fail: {e}", flush=True)
        return ""


def fetch_history() -> str:
    try:
        now = datetime.now(timezone.utc)
        url = (
            f"https://api.wikimedia.org/feed/v1/wikipedia/ru/onthisday/events/"
            f"{now.month}/{now.day}"
        )
        headers = {"User-Agent": "NewsDigestBot/1.0"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"history fail: {r.status_code} {r.text[:200]}", flush=True)
            return ""
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


# ---------- ОТПРАВКА В TELEGRAM ----------

def send_header(total_news: int) -> None:
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    lines = [
        "<b>📰 Дайджест новостей</b>",
        f"<i>{msk.strftime('%d.%m.%Y · %H:%M')} МСК</i>",
        DIVIDER,
    ]

    weather = fetch_weather()
    if weather:
        text, source = weather
        lines += ["<b>🌤 Погода в Нальчике</b>", f"{text} <i>({source})</i>", ""]

    rates = fetch_rates()
    if rates:
        lines += ["<b>💱 Курсы ЦБ РФ</b>", rates, ""]

    crypto = fetch_crypto()
    if crypto:
        lines += ["<b>🪙 Криптовалюты</b>", crypto, ""]

    quote = fetch_quote()
    if quote:
        lines += ["<b>💬 Цитата дня</b>", f"<i>{quote}</i>", ""]

    history = fetch_history()
    if history:
        lines += ["<b>📅 В этот день</b>", history, ""]

    if total_news > 0:
        lines += [DIVIDER, f"📌 <b>Свежих новостей: {total_news}</b>"]
    else:
        lines += [DIVIDER, "📌 <i>Новых новостей пока нет</i>"]

    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
    })


def send_preview_list(items: list) -> None:
    if not items:
        return
    lines = ["<b>🗂 Краткий обзор</b>", ""]
    for i, item in enumerate(items, 1):
        cat = detect_category(item["title"])
        title = html.escape(item["title"])
        lines.append(f"{i}. {cat} <a href=\"{item['link']}\">{title}</a>")
    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def send_item(item: dict, idx: int, total: int) -> None:
    cat = detect_category(item["title"])
    source = item["source"].split(" ", 1)[-1]
    title = html.escape(item["title"])
    summary = html.escape(item["summary"])
    time_part = f" · 🕐 {item['time']}" if item["time"] else ""

    caption = (
        f"<b>{idx}/{total}</b> · {cat} <i>{source}</i>{time_part}\n"
        f"{DIVIDER}\n"
        f"<b>{title}</b>"
    )
    if summary:
        caption += f"\n\n{summary}"
    if len(caption) > 1000:
        caption = caption[:1000] + "…"

    reply_markup = {
        "inline_keyboard": [[
            {"text": "📖 Читать полностью", "url": item["link"]}
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
        "disable_web_page_preview": True,
        "reply_markup": reply_markup,
    })


def fetch_all_news(seen: dict) -> list:
    items = []
    for source_name, url in RSS_URLS:
        feed = feedparser.parse(url)
        count = 0
        for entry in feed.entries:
            if count >= NEWS_PER_FEED:
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
            count += 1
    return items


def main() -> None:
    print(">>> START", flush=True)
    seen = load_seen()
    print(f">>> seen={len(seen)}", flush=True)

    items = fetch_all_news(seen)
    total = len(items)
    print(f">>> new items: {total}", flush=True)

    send_header(total)

    if not items:
        print(">>> nothing new, header sent", flush=True)
        return

    send_preview_list(items)

    now = time.time()
    for i, item in enumerate(items, 1):
        print(f">>> {item['source']} | {item['title'][:60]}", flush=True)
        send_item(item, i, total)
        seen[item["id"]] = now

    save_seen(seen)
    print(">>> DONE", flush=True)


if __name__ == "__main__":
    main()
