"""
Los, elk-uur-draaiend taakje voor NIEUWE sets / winkeldeals (sectie 2-3 van
de regels): Intertoys, Kruidvat, bol, Amazon NL/DE, LEGO.com, Smyths, etc.
geven geen webhook af zoals MarktAlert dat doet voor tweedehands — die moet
je zelf periodiek checken.

Hier is bewust GEEN kant-en-klare scraper voor elke winkel ingebouwd: de
paginastructuur van elke winkel verandert regelmatig en zou dit script
steeds laten breken. In plaats daarvan is dit een duidelijk insteekpunt:

  1. Vul найди_deals() met jouw eigen bron — bijvoorbeeld:
     - een prijsvergelijker met een export/RSS/API (bv. Idealo, Tweakers
       Pricewatch of vergelijkbaar) die kortingen op LEGO-sets doorgeeft;
     - een kant-en-klare "prijsdaling"-tool/RSS-feed van een van de winkels;
     - of, als je een winkel toch zelf wilt volgen, een simpele
       requests+BeautifulSoup check op één specifieke aanbiedingspagina
       (technisch prima te doen, maar per winkel maatwerk).
  2. Elke gevonden aanbieding gaat door dezelfde evaluate_listing() /
     send_deal() als de tweedehands-flow, dus de score-logica en het
     Telegram-bericht zijn identiek.

Draai dit via cron elk uur, bv.:
    0 * * * * cd /pad/naar/lego-dealhunter && /pad/naar/venv/bin/python store_deals_hourly.py
"""
import logging

from evaluator import evaluate_listing
from notifier import send_deal
from storage import already_seen, init_db, record

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dealhunter.store_deals")


def vind_deals() -> list[dict]:
    """
    TODO: vul dit met jouw eigen bron voor nieuwe winkeldeals.
    Moet een lijst van dicts teruggeven met dezelfde velden als de
    webhook-flow: title, description, price, platform, location, url.
    """
    return []


def main():
    init_db()
    deals = vind_deals()
    logger.info("Gevonden winkeldeals deze ronde: %d", len(deals))

    for listing in deals:
        url = listing.get("url", "")
        if not url or already_seen(url):
            continue
        result = evaluate_listing(listing)
        record(url, result)
        if result.get("should_notify"):
            send_deal(result)
            logger.info("Winkeldeal verstuurd (score %s): %s", result.get("score"), url)


if __name__ == "__main__":
    main()
