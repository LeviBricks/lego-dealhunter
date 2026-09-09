"""
Stuurt een geëvalueerde, goedgekeurde deal als opgemaakt bericht naar
Telegram (jouw telefoon).
"""
import logging
import os

import requests

logger = logging.getLogger("dealhunter.notifier")

EMOJI = {
    "direct_kopen": "🔥",
    "goede_deal": "🟢",
    "interessant_eol": "🟡",
    "onderhandeldeal": "🟡",
    "nieuwe_set": "🟢",
    "geen": "⚪",
}


def _format_message(evalresult: dict) -> str:
    emoji = EMOJI.get(evalresult.get("category", "geen"), "🟢")
    lines = []
    if evalresult.get("urgent"):
        lines.append("🚨 *SNEL HANDELEN*")

    lines.append(f"{emoji} *{evalresult.get('product', 'LEGO deal')}*")
    lines.append(f"Platform: {evalresult.get('platform', '-')}")
    lines.append(f"Vraagprijs: {evalresult.get('vraagprijs', '-')}")
    lines.append(f"Geschatte normale waarde: {evalresult.get('geschatte_normale_waarde', '-')}")
    lines.append(f"Geschatte verkoopwaarde: {evalresult.get('geschatte_verkoopwaarde', '-')}")
    lines.append(f"Verwachte winst: {evalresult.get('verwachte_winst', '-')}")
    lines.append(f"ROI: {evalresult.get('roi_percent', '-')}")
    lines.append(f"Max. aankoopprijs: {evalresult.get('max_aankoopprijs', '-')}")
    lines.append(f"Deal-score: {evalresult.get('score', '-')}/10")

    if evalresult.get("aanbevolen_aantal"):
        lines.append(f"Aanbevolen aantal: {evalresult['aanbevolen_aantal']}")

    if evalresult.get("waarom"):
        lines.append("\n*Waarom interessant:*")
        lines.append(evalresult["waarom"])

    if evalresult.get("risico"):
        lines.append(f"\n*Risico:* {evalresult['risico']}")

    lines.append(f"\n*ACTIE:* {evalresult.get('actie', '-')}")

    if evalresult.get("onderhandelbericht"):
        lines.append("\n*Bericht voor verkoper:*")
        lines.append(f"_{evalresult['onderhandelbericht']}_")

    if evalresult.get("link"):
        lines.append(f"\n{evalresult['link']}")

    return "\n".join(lines)


def send_deal(evalresult: dict) -> bool:
    """Stuurt één deal-melding naar Telegram. Geeft True/False terug."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    text = _format_message(evalresult)

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        logger.error("Telegram-fout: %s %s", resp.status_code, resp.text)
        return False
    return True
