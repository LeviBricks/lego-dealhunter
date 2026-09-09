"""
LEGO Dealhunter — webhook-server voor Levi Bricks.

Werking:
1. MPAlerts biedt een RSS-feed voor de zoekopdracht "Lego partij" aan.
   Wij checken die feed elke paar minuten via GET /check-rss (aangeroepen
   door een gratis externe "cron"-dienst, bv. cron-job.org).
2. Wij geven elke nieuwe advertentie door aan Claude, met de volledige
   Levi Bricks Dealhunter-regels (zie prompt.py).
3. Alleen als het een score 6+ deal is, sturen we een opgemaakte melding
   naar jouw Telegram.
4. Alles (ook afgewezen advertenties) wordt gelogd in dealhunter.db, zodat
   je kunt controleren of de instellingen goed staan.
5. POST /webhook/listing blijft ook bestaan, voor als je later alsnog een
   directe webhook-koppeling vindt.

Start lokaal met:
    python app.py
"""
import logging
import os
import re

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
RSS_FEED_URLS = [
    url.strip()
    for url in os.environ.get("RSS_FEED_URLS", "").split(",")
    if url.strip()
]

PRICE_PATTERN = re.compile(r"€\s?([\d.,]+)")


def _check_secret():
    if not WEBHOOK_SECRET:
        return True
    provided = request.args.get("secret") or request.headers.get("X-Webhook-Secret")
    return provided == WEBHOOK_SECRET


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
    """Haalt een RSS-feed op en zet elk item om naar ons interne format."""
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
        logger.warning("Listing zonder url overgeslagen: %s", listing)
        return None

    if already_seen(url):
        return None

    result = evaluate_listing(listing)
    record(url, result)

    if result.get("should_notify"):
        sent = send_deal(result)
        logger.info(
            "Deal score %s (%s) -> Telegram %s: %s",
            result.get("score"), result.get("category"),
            "verstuurd" if sent else "MISLUKT", url,
        )
    else:
        logger.info("Afgewezen (score %s): %s", result.get("score"), url)

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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
