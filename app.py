"""
LEGO Dealhunter — webhook-server voor Levi Bricks.
"""
import base64
import logging
import os
import re

import anthropic
import requests
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, request

from evaluator import evaluate_listing
from notifier import send_deal
from storage import already_seen, init_db, record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dealhunter.app")

app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
RSS_FEED_URLS = [
    url.strip()
    for url in os.environ.get("RSS_FEED_URLS", "").split(",")
    if url.strip()
]

PRICE_PATTERN = re.compile(r"€\s?([\d.,]+)")

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def _check_secret():
    if not WEBHOOK_SECRET:
        return True
    provided = request.args.get("secret") or request.headers.get("X-Webhook-Secret")
    return provided == WEBHOOK_SECRET


def _telegram_reply(chat_id, text):
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Geen TELEGRAM_BOT_TOKEN ingesteld, kan niet antwoorden.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        return resp.ok
    except Exception as exc:
        logger.error("Kon geen Telegram-antwoord versturen: %s", exc)
        return False


def _telegram_download_photo(file_id):
    """Haalt een foto op die de gebruiker naar de bot stuurde."""
    info = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=15,
    ).json()
    file_path = info["result"]["file_path"]
    file_resp = requests.get(
        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}",
        timeout=20,
    )
    return file_resp.content


def _identify_photo(image_bytes: bytes) -> str:
    """Laat Claude beschrijven welke LEGO-set/minifiguur op de foto staat."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    response = claude_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": (
                    "Dit is een foto van een LEGO-minifiguur, set of onderdeel. "
                    "Zeg zo specifiek mogelijk welke set of minifiguur dit is "
                    "(setnummer indien bekend, thema, naam). Antwoord in maximaal "
                    "2 zinnen, gewoon de herkenning, geen verdere uitleg."
                )},
            ],
        }],
    )
    return response.content[0].text.strip()


def _search_live_deal(query: str) -> str:
    """Laat Claude live op internet zoeken naar de beste huidige aanbiedingen."""
    system_prompt = (
        "Je bent de Levi Bricks Dealhunter-assistent. De gebruiker vraagt je om "
        "een specifieke LEGO-set of minifiguur op te zoeken. Zoek op het "
        "internet (vooral marktplaats.nl, vinted.nl, 2dehands.be) naar actuele "
        "aanbiedingen. Geef de 1-3 beste deals die je vindt: titel, prijs, link, "
        "en een korte inschatting of het een goede prijs is (vergelijk met "
        "ongeveer wat de set/minifiguur normaal waard is). Antwoord in het "
        "Nederlands, kort en praktisch, geschikt om als Telegram-bericht te "
        "versturen. Als je niks bruikbaars vindt, zeg dat gewoon eerlijk."
    )
    response = claude_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=800,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Zoek naar: {query}"}],
    )
    text_parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(text_parts).strip() or "Ik kon niks vinden, probeer het later nog eens."


def _normalize_payload(data: dict) -> dict:
    return {
        "title": data.get("title") or data.get("titel") or "",
        "description": data.get("description") or data.get("beschrijving") or "",
        "price": data.get("price") or data.get("prijs") or "",
        "platform": data.get("platform") or data.get("source") or "",
        "location": data.get("location") or data.get("locatie") or "",
        "url": data.get("url") or data.get("link") or "",
        "image_description": data.get("image_description", ""),
    }


def _extract_price(text: str) -> str:
    match = PRICE_PATTERN.search(text or "")
    return match.group(0) if match else ""


def _parse_rss_feed(feed_url: str) -> list:
    resp = requests.get(feed_url, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        combined_text = f"{title} {description}"

        items.append({
            "title": title,
            "description": description,
            "price": _extract_price(combined_text),
            "platform": "Marktplaats/MPAlerts",
            "location": "",
            "url": link,
            "image_description": "",
        })
    return items


def _process(listing: dict):
    url = listing.get("url", "")
    if not url:
        return None
    if already_seen(url):
        return None

    result = evaluate_listing(listing)
    record(url, result)

    if result.get("should_notify"):
        send_deal(result)
    return result


@app.route("/webhook/listing", methods=["POST"])
def webhook_listing():
    if not _check_secret():
        return jsonify({"error": "invalid secret"}), 403
    data = request.get_json(force=True, silent=True) or {}
    listing = _normalize_payload(data)
    result = _process(listing)
    return jsonify({"processed": result is not None, "result": result}), 200


@app.route("/check-rss", methods=["GET"])
def check_rss():
    if not _check_secret():
        return jsonify({"error": "invalid secret"}), 403
    if not RSS_FEED_URLS:
        return jsonify({"error": "no RSS_FEED_URLS configured"}), 400

    total_new = 0
    for feed_url in RSS_FEED_URLS:
        try:
            listings = _parse_rss_feed(feed_url)
        except Exception as exc:
            logger.error("Kon RSS-feed niet ophalen (%s): %s", feed_url, exc)
            continue
        for listing in listings:
            if _process(listing) is not None:
                total_new += 1

    return jsonify({"checked_feeds": len(RSS_FEED_URLS), "new_items_processed": total_new}), 200


@app.route("/telegram/webhook/<secret>", methods=["POST"])
def telegram_webhook(secret):
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "invalid secret"}), 403

    update = request.get_json(force=True, silent=True) or {}
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    photos = message.get("photo")

    if not chat_id:
        return jsonify({"ok": True}), 200

    try:
        if photos:
            _telegram_reply(chat_id, "📸 Foto ontvangen, ik ben 'm aan het bekijken...")
            biggest_photo = photos[-1]
            image_bytes = _telegram_download_photo(biggest_photo["file_id"])
            herkenning = _identify_photo(image_bytes)
            _telegram_reply(chat_id, f"🔍 Ik denk dat dit is: {herkenning}\n\nEven de beste deals opzoeken...")
            resultaat = _search_live_deal(herkenning)
            _telegram_reply(chat_id, resultaat)

        elif text.lower().startswith("zoek"):
            query = text[4:].strip()
            if not query:
                _telegram_reply(chat_id, "Typ bijvoorbeeld: zoek 75192")
            else:
                _telegram_reply(chat_id, f"🔎 Ik zoek naar '{query}', momentje...")
                resultaat = _search_live_deal(query)
                _telegram_reply(chat_id, resultaat)

        elif text:
            _telegram_reply(
                chat_id,
                "Hoi! Stuur 'zoek <setnummer of naam>' om actief te laten zoeken, "
                "of stuur een foto van een minifiguur/set.",
            )
    except Exception as exc:
        logger.error("Fout bij verwerken Telegram-bericht: %s", exc)
        _telegram_reply(chat_id, "Sorry, er ging iets mis. Probeer het nog eens.")

    return jsonify({"ok": True}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
