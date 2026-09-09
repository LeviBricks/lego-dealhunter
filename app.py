"""
LEGO Dealhunter — webhook-server voor Levi Bricks.

Werking:
1. MarktAlert of MPAlerts stuurt bij elke nieuwe matchende advertentie
   (Marktplaats, 2dehands, Vinted, Facebook Marketplace) een webhook naar
   POST /webhook/listing (in ons eigen formaat, of via het Discord-
   webhookveld — beide worden herkend).
2. Wij geven die advertentie door aan Claude, met de volledige Levi Bricks
   Dealhunter-regels (zie prompt.py).
3. Alleen als het een score 6+ deal is, sturen we een opgemaakte melding
   naar jouw Telegram.
4. Alles (ook afgewezen advertenties) wordt gelogd in dealhunter.db, zodat
   je kunt controleren of de instellingen goed staan.

Daarnaast: POST /webhook/store-deal voor nieuwe winkeldeals/prijsfouten die
je los aanlevert (bv. via een eigen prijs-monitor of handmatig getest).

Start lokaal met:
    python app.py

Voor productie: zie deploy/lego-dealhunter.service (systemd, draait continu
en herstart automatisch).
"""
import logging
import os

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

# Simpele gedeelde-secret check, zodat niet iedereen op internet jouw
# webhook-endpoint kan misbruiken. Zet dezelfde waarde in MarktAlert/MPAlerts
# (als extra header of query-param) en in je .env als WEBHOOK_SECRET.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def _check_secret():
    if not WEBHOOK_SECRET:
        return True
    provided = request.args.get("secret") or request.headers.get("X-Webhook-Secret")
    return provided == WEBHOOK_SECRET


def _extract_field(fields: list, *keywords: str) -> str:
    """Zoek in een lijst Discord-embed 'fields' naar een veld waarvan de
    naam een van de keywords bevat, en geef de waarde terug."""
    for field in fields or []:
        name = str(field.get("name", "")).lower()
        if any(kw in name for kw in keywords):
            return str(field.get("value", "")).strip()
    return ""


def _normalize_discord_payload(data: dict) -> dict:
    """Zet een Discord-webhook bericht (zoals MPAlerts dat verstuurt als je
    het 'Discord'-webhookveld gebruikt) om naar ons interne format."""
    embeds = data.get("embeds") or []
    embed = embeds[0] if embeds else {}
    fields = embed.get("fields", [])

    title = embed.get("title") or data.get("content") or ""
    description = embed.get("description") or ""
    url = embed.get("url") or ""
    image = embed.get("image", {}) or {}

    price = _extract_field(fields, "prijs", "price")
    location = _extract_field(fields, "locatie", "location", "plaats")
    platform = _extract_field(fields, "platform", "bron", "source") or "Marktplaats"

    return {
        "title": title,
        "description": description,
        "price": price,
        "platform": platform,
        "location": location,
        "url": url,
        "image_description": image.get("url", ""),
    }


def _normalize_payload(data: dict) -> dict:
    """
    Zet de velden van de externe dienst om naar ons interne format.
    Herkent zowel het 'gewone' webhookformaat van MarktAlert/MPAlerts als
    het Discord-embedformaat (als je het Discord-webhookveld gebruikt).
    """
    if "embeds" in data or "content" in data:
        return _normalize_discord_payload(data)

    return {
        "title": data.get("title") or data.get("titel") or "",
        "description": data.get("description") or data.get("beschrijving") or "",
        "price": data.get("price") or data.get("prijs") or "",
        "platform": data.get("platform") or data.get("source") or "",
        "location": data.get("location") or data.get("locatie") or "",
        "url": data.get("url") or data.get("link") or "",
        "image_description": data.get("image_description", ""),
    }


def _process(listing: dict):
    url = listing.get("url", "")
    if not url:
        logger.warning("Listing zonder url overgeslagen: %s", listing)
        return None

    if already_seen(url):
        logger.info("Al eerder gezien, overslaan: %s", url)
        return None

    result = evaluate_listing(listing)
    record(url, result)

    if result.get("should_notify"):
        sent = send_deal(result)
        logger.info(
            "Deal score %s (%s) -> Telegram %s: %s",
            result.get("score"),
            result.get("category"),
            "verstuurd" if sent else "MISLUKT",
            url,
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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
