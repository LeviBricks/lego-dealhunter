# LEGO Dealhunter — Levi Bricks

Een programma dat automatisch (elke keer als er een nieuwe advertentie
binnenkomt, plus elk uur voor winkeldeals) LEGO-partijen beoordeelt volgens
jouw eigen Dealhunter-regels, en alleen de écht goede deals (score 6+) naar
je Telegram stuurt — met dealscore, winstberekening en een kant-en-klaar
onderhandelbericht.

## Hoe het in elkaar zit

```
[Marktplaats/Vinted/2dehands/Facebook]
              |
   (MarktAlert of MPAlerts: bestaande dienst die dit al
    betrouwbaar 24/7 in de gaten houdt)
              |
              v  webhook, bij elke nieuwe match
     ┌─────────────────────┐
     │   app.py (jouw server)│
     │  1. evaluator.py      │──> Claude API (jouw Dealhunter-regels)
     │  2. storage.py (log)  │
     │  3. notifier.py       │──> Telegram (jouw telefoon)
     └─────────────────────┘
              ^
              | elk uur
     store_deals_hourly.py  (nieuwe sets / winkeldeals, cron)
```

Waarom niet zelf Marktplaats/Vinted/Facebook scrapen? Die sites veranderen
regelmatig van structuur en proberen bots te blokkeren — dat zou dit systeem
constant laten breken. MarktAlert en MPAlerts doen dat zoekwerk al
betrouwbaar en sturen desgewenst een **webhook** (dus geen los abonnement op
alléén e-mail/Telegram, maar de webhook-optie). Wij bouwen alleen het
"brein" erachter: de score-logica en het doorsturen.

## Stap 1 — Account bij MarktAlert of MPAlerts

1. Ga naar marktalert.nl of mpalerts.nl en maak een account.
2. Zet alerts aan voor de zoektermen uit sectie 1 van de regels (Lego
   partij, Lego verzameling, Lego zolder, Lego Star Wars, Lego minifiguren,
   enz. — begin breed, je filtert toch al slim na via Claude).
3. Kies bij het bezorgkanaal **webhook** in plaats van e-mail/Telegram, en
   vul daar (zodra je server draait, zie stap 3) in:
   `https://JOUW-SERVER-ADRES/webhook/listing?secret=WEBHOOK_SECRET`
4. Test met hun testbericht-functie en kijk in de logs van je server welke
   veldnamen ze gebruiken (title/titel, price/prijs, etc.) — pas zo nodig
   `_normalize_payload()` in `app.py` aan op hun exacte veldnamen.

## Stap 2 — Telegram bot

1. Open Telegram, zoek `@BotFather`, stuur `/newbot`, volg de stappen.
2. Kopieer de token die je terugkrijgt naar `TELEGRAM_BOT_TOKEN` in `.env`.
3. Stuur zelf een bericht naar je nieuwe bot (anders weet Telegram niet
   waar hij berichten naartoe mag sturen).
4. Open in de browser:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   en lees je `chat_id` af, zet die in `.env`.

## Stap 3 — Server (waar het script continu draait)

Elk apparaat dat 24/7 aanstaat en een publiek bereikbaar adres kan krijgen
werkt. Twee simpele opties:

**A. Goedkope VPS** (bv. Hetzner, DigitalOcean, TransIP — vanaf ~5 euro/mnd)
```bash
git clone <of upload de map lego-dealhunter>
cd lego-dealhunter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # vul hierna je eigen sleutels in
sudo cp deploy/lego-dealhunter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lego-dealhunter
```
Zet er een gratis Let's Encrypt-certificaat + een reverse proxy (bv. Caddy,
1 regel config) voor zodat je een `https://` adres hebt — dat hebben
MarktAlert/MPAlerts nodig voor de webhook.

**B. Render.com / Railway.app** (geen eigen server nodig, gratis/goedkoop
tier beschikbaar): map uploaden, environment variables invullen zoals in
`.env.example`, start command `python app.py`. Zij geven je automatisch een
`https://` adres — makkelijker dan zelf een VPS inrichten.

## Stap 4 — Uurlijkse winkeldeal-check

`store_deals_hourly.py` heeft een lege `vind_deals()` functie — daar vul je
je eigen bron voor nieuwe-set-aanbiedingen in (zie de toelichting bovenin
dat bestand). Draai 'm via cron:
```bash
crontab -e
# voeg toe:
0 * * * * cd /pad/naar/lego-dealhunter && venv/bin/python store_deals_hourly.py >> hourly.log 2>&1
```

## Testen zonder een echte advertentie af te wachten

```bash
curl -X POST "http://localhost:8080/webhook/listing?secret=WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Grote partij Lego Star Wars, zolder opruiming",
    "description": "Doos vol Lego, weet niet precies wat erin zit, oude sets van kinderen",
    "price": "150",
    "platform": "Marktplaats",
    "location": "Zwolle",
    "url": "https://voorbeeld.nl/advertentie/123"
  }'
```
Check daarna je Telegram (als de deal score 6+ krijgt) en `dealhunter.db`
(alle evaluaties, ook afgewezen, staan daarin — handig om de score-logica
te controleren en zo nodig bij te schaven in `prompt.py`).

## Kosten

- MarktAlert/MPAlerts: gratis tier vaak beperkt, PRO meestal een paar euro/mnd.
- VPS of Render: vanaf ~0-7 euro/mnd.
- Claude API: reken op een paar cent per beoordeelde advertentie (Sonnet).
  Bij pieken (veel advertenties tegelijk) kun je in `.env` overstappen op
  een goedkoper model als kostenbesparing belangrijker is dan precisie.

## Wat later nog te verbeteren valt

- Beeldherkenning: foto's van de advertentie meesturen naar Claude (die kan
  ook afbeeldingen lezen) zodat sectie "verkeerd omschreven partijen" ook
  echt op de foto's beoordeeld wordt, niet alleen de tekst.
- Wekelijks/maandelijks overzicht van alle gelogde deals uit `dealhunter.db`
  om te zien of de scoregrenzen in `prompt.py` goed staan.
