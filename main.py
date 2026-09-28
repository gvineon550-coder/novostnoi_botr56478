def send_to_telegram(text):
    print(f"DEBUG token_len={len(TELEGRAM_TOKEN or '')} "
          f"starts={str(TELEGRAM_TOKEN)[:10]} "
          f"chat={CHAT_ID}")
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
