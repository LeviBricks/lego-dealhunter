"""
Stuurt één advertentie naar Claude, met de volledige Levi Bricks
Dealhunter-regels als systeemprompt, en parsed het JSON-antwoord.
"""
import json
import logging
import os

import anthropic

from prompt import SYSTEM_PROMPT

logger = logging.getLogger("dealhunter.evaluator")

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ["ANTHROPIC_API_KEY"]
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def evaluate_listing(listing: dict) -> dict:
    """
    listing verwacht keys als: title, description, price, platform,
    location, url, image_description (optioneel).
    Geeft een dict terug volgens het JSON-schema uit prompt.py.
    Bij een fout wordt should_notify=False teruggegeven zodat er nooit
    per ongeluk een kapotte melding naar de telefoon gaat.
    """
    user_content = (
        "Beoordeel deze advertentie volgens de Dealhunter-regels en geef "
        "ALLEEN het JSON-object terug:\n\n"
        f"Titel: {listing.get('title', '')}\n"
        f"Beschrijving: {listing.get('description', '')}\n"
        f"Prijs: {listing.get('price', '')}\n"
        f"Platform: {listing.get('platform', '')}\n"
        f"Locatie: {listing.get('location', '')}\n"
        f"URL: {listing.get('url', '')}\n"
        f"Beeldomschrijving: {listing.get('image_description', 'onbekend')}\n"
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        # Extra robuust: als het model per ongeluk toch een codeblok gebruikt.
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:].strip()

        result = json.loads(raw_text)
        result.setdefault("link", listing.get("url", ""))
        return result

    except Exception:
        logger.exception("Evaluatie mislukt voor listing: %s", listing.get("url"))
        return {
            "should_notify": False,
            "score": 0,
            "category": "geen",
            "urgent": False,
            "waarom": "Evaluatie mislukt (zie server-log).",
            "link": listing.get("url", ""),
        }
