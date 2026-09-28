import os
import re
import json
import time
import html
import random
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
    ("🎥 Film.ru",        "https://www.film.ru/rss/news"),
    ("🎞 Кино-Театр.Ру",  "https://www.kino-teatr.ru/news/rss.xml"),
]

NEWS_PER_FEED = 2
DEDUP_HOURS = 12
DIVIDER = "━━━━━━━━━━━━━━━"
STATE_DIR = "state"
STATE_FILE = os.path.join(STATE_DIR, "sent.json")
META_FILE = os.path.join(STATE_DIR, "meta.json")
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
]

HOLIDAYS = {
    "01-01": "🎄 Новый год", "01-07": "🎄 Рождество Христово",
    "01-25": "🎓 День студента (Татьянин день)", "02-14": "💝 День всех влюблённых",
    "02-23": "🪖 День защитника Отечества", "03-08": "🌷 Международный женский день",
    "04-01": "😂 День смеха", "04-12": "🚀 День космонавтики",
    "05-01": "🌸 Праздник Весны и Труда", "05-09": "🎖 День Победы",
    "06-01": "🧒 День защиты детей", "06-12": "🇷🇺 День России",
    "07-08": "💑 День семьи, любви и верности", "09-01": "🎒 День знаний",
    "10-05": "👨‍🏫 День учителя", "11-04": "🤝 День народного единства",
    "12-12": "📜 День Конституции РФ", "12-31": "🥂 Канун Нового года",
}

QUOTES = [
    ("Красота спасёт мир.", "Фёдор Достоевский"),
    ("Все счастливые семьи похожи друг на друга, каждая несчастливая семья несчастлива по-своему.", "Лев Толстой"),
    ("Умом Россию не понять.", "Фёдор Тютчев"),
    ("Человек — это звучит гордо.", "Максим Горький"),
    ("Рукописи не горят.", "Михаил Булгаков"),
    ("Кто не рискует, тот не пьёт шампанского.", "Русская пословица"),
    ("Не бойтесь быть не как все.", "Антон Чехов"),
    ("Счастье не в том, чтобы делать всегда, что хочешь, а в том, чтобы всегда хотеть того, что делаешь.", "Лев Толстой"),
    ("В человеке всё должно быть прекрасно: и лицо, и одежда, и душа, и мысли.", "Антон Чехов"),
    ("Родину любят не за то, что она велика, а за то, что она своя.", "Сенека"),
    ("Жизнь дана на добрые дела.", "Русская пословица"),
    ("Хочешь быть счастливым — будь им.", "Козьма Прутков"),
    ("Знание — сила.", "Фрэнсис Бэкон"),
    ("Мы в ответе за тех, кого приручили.", "Антуан де Сент-Экзюпери"),
    ("Всё пройдёт, и это тоже пройдёт.", "Восточная мудрость"),
    ("Гений — это один процент вдохновения и девяносто девять процентов пота.", "Томас Эдисон"),
    ("Единственный способ делать великую работу — любить то, что делаешь.", "Стив Джобс"),
    ("Век живи — век учись.", "Русская пословица"),
    ("Слово не воробей, вылетит — не поймаешь.", "Русская пословица"),
    ("Чтобы дойти до цели, надо прежде всего идти.", "Оноре де Бальзак"),
    ("Быстрее всего учишься в трёх случаях: до 7 лет, на тренингах и когда жизнь бьёт.", "Народная мудрость"),
    ("Не откладывай на завтра то, что можно сделать сегодня.", "Бенджамин Франклин"),
    ("Тот, кто хочет — ищет возможности, кто не хочет — ищет причины.", "Сократ"),
    ("Успех — это способность идти от одной неудачи к другой, не теряя энтузиазма.", "Уинстон Черчилль"),
    ("Мы живём в мире, где за всё надо платить.", "Публилий Сир"),
]

TOP_KEYWORDS = ["срочно", "экстренно", "важно", "главное", "погиб", "убит",
                "трагедия", "катастрофа", "впервые", "рекорд", "путин",
                "удар", "взрыв", "война", "мир", "санкц", "переговор"]


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


# ---------- ДЕНЬ / ВРЕМЯ / ЛУНА ----------

def greeting() -> str:
    h = (datetime.now(timezone.utc) + timedelta(hours=3)).hour
    if 5 <= h < 12: return "🌅 Доброе утро!"
    if 12 <= h < 18: return "☀️ Добрый день!"
    if 18 <= h < 23: return "🌆 Добрый вечер!"
    return "🌙 Доброй ночи!"


def day_progress() -> str:
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    sec = msk.hour * 3600 + msk.minute * 60 + msk.second
    pct = sec / 86400
    filled = int(pct * 10)
    return f"{'▰' * filled}{'▱' * (10 - filled)} {int(pct * 100)}% дня"


def moon_phase() -> str:
    known_new = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - known_new).total_seconds() / 86400
    p = (days % 29.530588853) / 29.530588853
    if p < 0.0625 or p >= 0.9375: return "🌑 Новолуние"
    if p < 0.1875: return "🌒 Молодой месяц"
    if p < 0.3125: return "🌓 Первая четверть"
    if p < 0.4375: return "🌔 Растущая луна"
    if p < 0.5625: return "🌕 Полнолуние"
    if p < 0.6875: return "🌖 Убывающая луна"
    if p < 0.8125: return "🌗 Последняя четверть"
    return "🌘 Старая луна"


def today_holiday() -> str:
    key = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%m-%d")
    return HOLIDAYS.get(key, "")


# ---------- ПОГОДА ----------

def weather_from_open_meteo():
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={NALCHIK_LAT}&longitude={NALCHIK_LON}"
            f"&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            f"&daily=sunrise,sunset,weather_code,temperature_2m_max,temperature_2m_min"
            f"&timezone=Europe/Moscow&forecast_days=2"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        d = r.json()
        cur = d["current"]
        temp = round(cur["temperature_2m"])
        feels = round(cur["apparent_temperature"])
        desc = WEATHER_CODES.get(cur["weather_code"], "🌡 —")
        wind = round(cur["wind_speed_10m"])
        current_line = f"{desc} · {temp}°C (ощущается {feels}°C), ветер {wind} м/с"

        daily = d.get("daily", {})
        extra = []
        if daily.get("sunrise") and daily.get("sunset"):
            sr = daily["sunrise"][0][11:16]
            ss = daily["sunset"][0][11:16]
            extra.append(f"🌅 Восход {sr} · Закат {ss}")
        if daily.get("temperature_2m_max") and len(daily["temperature_2m_max"]) > 1:
            tmax = round(daily["temperature_2m_max"][1])
            tmin = round(daily["temperature_2m_min"][1])
            code = daily["weather_code"][1]
            tomorrow = WEATHER_CODES.get(code, "🌡").split(" ", 1)[-1]
            extra.append(f"📅 Завтра: {tomorrow}, {tmin}…{tmax}°C")

        return current_line, extra, "Open-Meteo"
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
        line = (
            f"{desc} · {cur['temp_C']}°C (ощущается {cur['FeelsLikeC']}°C), "
            f"ветер {cur['windspeedKmph']} км/ч"
        )
        return line, [], "wttr.in"
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
        return f"{desc} · {temp}°C, ветер {wind} км/ч", [], "met.no"
    except Exception as e:
        print(f"weather metno fail: {e}", flush=True)
        return None


def fetch_weather():
    for func in (weather_from_open_meteo, weather_from_wttr, weather_from_metno):
        r = func()
        if r:
            return r
    return None


def fetch_air_quality() -> str:
    try:
        url = (
            f"https://air-quality-api.open-meteo.com/v1/air-quality"
            f"?latitude={NALCHIK_LAT}&longitude={NALCHIK_LON}"
            f"&current=european_aqi&timezone=Europe/Moscow"
        )
        r = requests.get(url, timeout=15)
        aqi = r.json()["current"]["european_aqi"]
        if aqi is None:
            return ""
        if aqi <= 20: label = "Отличный"
        elif aqi <= 40: label = "Хороший"
        elif aqi <= 60: label = "Средний"
        elif aqi <= 80: label = "Плохой"
        elif aqi <= 100: label = "Очень плохой"
        else: label = "Опасный"
        return f"🍃 Воздух: {label} (AQI {aqi})"
    except Exception as e:
        print(f"air fail: {e}", flush=True)
        return ""


# ---------- КУРСЫ / КРИПТА ----------

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


# ---------- ЦИТАТА С ПОРТРЕТОМ ----------

def fetch_quote():
    return random.choice(QUOTES)


def fetch_author_photo(author: str) -> str:
    try:
        r = requests.get(
            "https://ru.wikipedia.org/w/api.php",
            params={
                "action": "query", "titles": author, "prop": "pageimages",
                "format": "json", "pithumbsize": 600, "redirects": 1,
            },
            headers={"User-Agent": "NewsDigestBot/1.0"},
            timeout=15,
        )
        pages = r.json().get("query", {}).get("pages", {})
        for p in pages.values():
            thumb = p.get("thumbnail", {}).get("source")
            if thumb:
                return thumb
    except Exception as e:
        print(f"author photo fail: {e}", flush=True)
    return ""


def send_quote():
    text, author = fetch_quote()
    caption = f"<b>💬 Цитата дня</b>\n\n<i>«{html.escape(text)}»</i>\n\n— <b>{html.escape(author)}</b>"
    photo = fetch_author_photo(author)
    if photo:
        res = tg("sendPhoto", {
            "chat_id": CHAT_ID, "photo": photo,
            "caption": caption, "parse_mode": "HTML",
        })
        if res and res.get("ok"):
            return
    tg("sendMessage", {
        "chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML",
    })


# ---------- АНЕКДОТ ----------

def fetch_joke() -> str:
    try:
        r = requests.get(
            "http://anecdotica.ru/api",
            params={
                "method": "getRandItem", "category": "all",
                "genre": 1, "format": "json", "encoding": "utf-8",
            },
            timeout=15,
        )
        data = r.json()
        text = data.get("text", "") or data.get("item", {}).get("text", "")
        if text and 20 < len(text) < 600:
            return strip_html(text)
    except Exception as e:
        print(f"joke anecdotica fail: {e}", flush=True)

    try:
        r = requests.get("http://rzhunemogu.ru/RandJSON.aspx", params={"CType": 1}, timeout=15)
        raw = r.content.decode("cp1251", errors="replace")
        m = re.search(r'"content":"(.*?)"\s*}', raw, re.DOTALL)
        if m:
            joke = m.group(1)
            joke = joke.replace("\\r\\n", "\n").replace("\\n", "\n").replace('\\"', '"')
            joke = strip_html(joke)
            if 20 < len(joke) < 600:
                return joke
    except Exception as e:
        print(f"joke rzhunemogu fail: {e}", flush=True)
    return ""


def send_joke():
    joke = fetch_joke()
    if not joke:
        return
    text = f"<b>😄 Анекдот дня</b>\n\n{joke}"
    tg("sendMessage", {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})


# ---------- 🐱 КОТ ДНЯ ----------

def fetch_cat() -> bytes:
    """Случайное фото кота из TheCatAPI (без ключа)."""
    try:
        r = requests.get(
            "https://api.thecatapi.com/v1/images/search",
            params={"mime_types": "jpg,png", "size": "med"},
            headers={"User-Agent": "NewsDigestBot/1.0"},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"cat api fail: {r.status_code}", flush=True)
            return b""
        data = r.json()
        if not data or not data[0].get("url"):
            return b""
        img_url = data[0]["url"]
        img = requests.get(
            img_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"},
            timeout=20,
        )
        if img.status_code == 200 and len(img.content) > 2000:
            return img.content
        print(f"cat img download fail: {img.status_code} size={len(img.content)}", flush=True)
    except Exception as e:
        print(f"cat exception: {e}", flush=True)
    return b""


def send_cat():
    """Фото кота дня — скачиваем и загружаем файлом."""
    content = fetch_cat()
    if not content:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("cat.jpg", content, "image/jpeg")}
    data = {
        "chat_id": CHAT_ID,
        "caption": "<b>🐱 Кот дня</b>\n\n<i>Мур-мур, хорошего дня!</i>",
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code != 200:
            print(f"sendCat fail: {r.status_code} {r.text[:150]}", flush=True)
    except Exception as e:
        print(f"sendCat exception: {e}", flush=True)


# ---------- ИСТОРИЯ ----------

def fetch_history() -> str:
    now = datetime.now(timezone.utc)
    url = (
        f"https://api.wikimedia.org/feed/v1/wikipedia/ru/onthisday/events/"
        f"{now.month}/{now.day}"
    )
    headers = {"User-Agent": "NewsDigestBot/1.0"}
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200:
                events = r.json().get("events", [])
                if not events:
                    return ""
                ev = events[0]
                text = strip_html(ev.get("text", ""))
                year = ev.get("year", "")
                return f"{year} — {text}" if year else text
            print(f"history attempt {attempt}: {r.status_code}", flush=True)
        except Exception as e:
            print(f"history attempt {attempt}: {e}", flush=True)
        time.sleep(3)
    return ""


# ---------- АЧИВКИ ----------

def track_visit() -> int:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(META_FILE) as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    now = time.time()
    if "first_seen" not in meta:
        meta["first_seen"] = now
    days = int((now - meta["first_seen"]) / 86400) + 1
    meta["last_seen"] = now
    try:
        with open(META_FILE, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        print(f"meta save fail: {e}", flush=True)
    return days


# ---------- ШАПКА ----------

def send_header(total_news: int, days_active: int) -> None:
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    lines = [
        f"<b>{greeting()}</b>",
        f"📰 <b>Дайджест новостей</b> · <i>{msk.strftime('%d.%m.%Y · %H:%M')} МСК</i>",
        day_progress(),
        DIVIDER,
    ]

    weather = fetch_weather()
    if weather:
        current, extra, source = weather
        lines += ["<b>🌤 Погода в Нальчике</b>", current]
        for line in extra:
            lines.append(line)
        air = fetch_air_quality()
        if air:
            lines.append(air)
        lines.append("")

    rates = fetch_rates()
    if rates:
        lines += ["<b>💱 Курсы ЦБ РФ</b>", rates, ""]

    crypto = fetch_crypto()
    if crypto:
        lines += ["<b>🪙 Криптовалюты</b>", crypto, ""]

    lines.append(f"<b>🌙 Луна:</b> {moon_phase()}")

    holiday = today_holiday()
    if holiday:
        lines.append(f"<b>🎉 Праздник:</b> {holiday}")

    history = fetch_history()
    if history:
        lines += ["", f"<b>📅 В этот день</b>", history]

    if total_news > 0:
        lines += [DIVIDER, f"📌 <b>Свежих новостей: {total_news}</b>"]
    else:
        lines += [DIVIDER, "📌 <i>Новых новостей пока нет</i>"]

    lines.append(f"🏆 <i>Вы с нами {days_active} {plural_days(days_active)}</i>")

    tg("sendMessage", {
        "chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "HTML",
    })


def plural_days(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11: return "день"
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14): return "дня"
    return "дней"


# ---------- ТОП-НОВОСТЬ ----------

def pick_top_news(items: list) -> list:
    scored = []
    for it in items:
        text = (it["title"] + " " + it["summary"]).lower()
        score = sum(3 for kw in TOP_KEYWORDS if kw in text)
        score += min(len(it["summary"]) // 50, 5)
        scored.append((score, it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored[:3]]


# ---------- КРАТКИЙ ОБЗОР ----------

def send_preview_list(items: list) -> None:
    if not items:
        return
    top = pick_top_news(items)
    lines = ["<b>🔥 Главное за сегодня</b>", ""]
    for it in top:
        cat = detect_category(it["title"])
        title = html.escape(it["title"])
        lines.append(f"{cat} <a href=\"{it['link']}\">{title}</a>")
    lines += ["", DIVIDER, "<b>🗂 Краткий обзор</b>", ""]
    for i, item in enumerate(items, 1):
        cat = detect_category(item["title"])
        title = html.escape(item["title"])
        lines.append(f"{i}. {cat} <a href=\"{item['link']}\">{title}</a>")
    tg("sendMessage", {
        "chat_id": CHAT_ID, "text": "\n".join(lines),
        "parse_mode": "HTML", "disable_web_page_preview": True,
    })


# ---------- КАРТОЧКА НОВОСТИ ----------

def send_item(item: dict, idx: int, total: int) -> None:
    cat = detect_category(item["title"])
    source = item["source"].split(" ", 1)[-1]
    title = html.escape(item["title"])
    summary = html.escape(item["summary"])
    time_part = f" · 🕐 {item['time']}" if item["time"] else ""

    caption = (
        f"<b>{idx}/{total}</b> · {cat} <i>{source}</i>{time_part}\n"
        f"{DIVIDER}\n<b>{title}</b>"
    )
    if summary:
        caption += f"\n\n{summary}"
    if len(caption) > 1000:
        caption = caption[:1000] + "…"

    reply_markup = {"inline_keyboard": [[
        {"text": "📖 Читать полностью", "url": item["link"]}
    ]]}

    if item["image"]:
        try:
            img = requests.get(
                item["image"],
                headers={"User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"},
                timeout=20,
            )
            if img.status_code == 200 and len(img.content) > 2000:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
                files = {"photo": ("image.jpg", img.content, "image/jpeg")}
                data = {
                    "chat_id": CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(reply_markup),
                }
                r = requests.post(url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    return
                print(f"sendPhoto upload fail: {r.status_code} {r.text[:150]}", flush=True)
            else:
                print(f"image download fail: {img.status_code} size={len(img.content)}", flush=True)
        except Exception as e:
            print(f"image exception: {e}", flush=True)

    tg("sendMessage", {
        "chat_id": CHAT_ID,
        "text": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup,
    })


# ---------- СБОР НОВОСТЕЙ ----------

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


# ---------- MAIN ----------

def main() -> None:
    print(">>> START", flush=True)
    seen = load_seen()
    days_active = track_visit()
    print(f">>> seen={len(seen)} days={days_active}", flush=True)

    items = fetch_all_news(seen)
    total = len(items)
    print(f">>> new items: {total}", flush=True)

    # 1. Шапка
    send_header(total, days_active)

    # 2. Цитата дня с портретом
    send_quote()

    # 3. Анекдот
    send_joke()

    # 4. 🐱 Кот дня
    send_cat()

    if not items:
        print(">>> nothing new", flush=True)
        return

    # 5. Топ-новости + краткий обзор
    send_preview_list(items)

    # 6. Карточки
    now = time.time()
    for i, item in enumerate(items, 1):
        print(f">>> {item['source']} | {item['title'][:60]}", flush=True)
        send_item(item, i, total)
        seen[item["id"]] = now

    save_seen(seen)
    print(">>> DONE", flush=True)


if __name__ == "__main__":
    main()
