# Steam Group Hub

Ein kleiner, selbstgehosteter Hub für eine feste Zocker-Runde: Wer besitzt was,
wer spielt gerade was, welche Errungenschaften sind wirklich selten – und vor
allem: **was können wir als Nächstes zusammen spielen?**

Läuft auf jeder Linux-Kiste mit Python 3.11+ (getestet auch unter Windows),
braucht keine Datenbank außer SQLite und keinen Build-Schritt fürs Frontend.

---

## Was der Hub kann

**Übersicht**
- Kennzahlen der Runde: Spielzeit gesamt, gemeinsame Multiplayer-Titel, nie gestartete Spiele, Bibliothekswert
- Chart der täglichen Spielzeit pro Person (letzte 30 Tage)
- Auszeichnungen mit Augenzwinkern: *Pile of Shame*, *Die Nachteule*, *Der Perfektionist*, *Der Monogame* …
- Aktivitäts-Feed: „Ben spielte 2 h Lethal Company, vor 20 h"

**Bibliothek**
- Alle Spiele der Runde mit Besitzer-Chips, gefiltert nach Multiplayer, Mindest-Besitzerzahl, ungespielt
- Zeigt bei knappen Fällen direkt, **wem** ein Titel noch fehlt

**Spielideen** – der eigentliche Zweck
- *Sofort spielbar*: Multiplayer-Titel, die alle besitzen, sortiert nach „am längsten nicht angefasst"
- *Fast komplett*: nur eine Person muss noch kaufen (inkl. Preis)
- *Backlog-Perlen*: gekauft, nie gestartet
- *Gerade angesagt*: was in den letzten 14 Tagen tatsächlich lief
- *Neu entdecken*: kuratierte Koop-Liste, abgeglichen mit dem Geschmack der Runde (Genre-Gewichtung aus echter Spielzeit) – zeigt nur, was ihr noch nicht habt

**Errungenschaften**
- Seltene Unlocks (weltweit unter 10 %), neueste Unlocks, Fortschrittsbalken pro Spiel

**Ranglisten**
- Acht Leaderboards, Overlap-Matrix (wie viele Titel jedes Paar gemeinsam hat)
- Heatmap „wann wird gespielt" nach Uhrzeit

**Abstimmung**
- „Was zocken wir Freitag?" – Daumen hoch/runter pro Spiel, ohne Login, auf Vertrauensbasis

**Discord**
- Meldungen im Channel: seltene Errungenschaften, 100-%-Spiele, Neuzugänge, die die Runde
  komplettieren, sonntags ein Rückblick
- Slash-Befehle: `/zocken` postet Vorschläge **mit Abstimmungs-Buttons**, dazu `/abstimmung`,
  `/spiel`, `/rangliste`, `/selten`, `/wasgeht`
- Sitzen genug Leute im Sprachkanal, schlägt der Bot von selbst vor, was **genau diese**
  Leute alle besitzen und ewig nicht gestartet haben

---

## Schnellstart (lokal ausprobieren)

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.cli demo        # Demo-Daten, kein API-Key nötig
python -m app.cli serve       # http://127.0.0.1:8077
```

## Mit echten Daten

1. **API-Key holen:** <https://steamcommunity.com/dev/apikey> (kostenlos, braucht nur einen Steam-Account)
   und in `.env` unter `STEAM_API_KEY` eintragen.
2. **Spieler eintragen** – SteamID64, Profil-URL oder Vanity-Name funktionieren alle:
   ```bash
   python -m app.cli add https://steamcommunity.com/id/beispiel --nick "Timmi"
   python -m app.cli add 76561198000000000 --nick "Jonas"
   python -m app.cli list
   ```
3. **Erster Sammellauf** (dauert je nach Bibliotheksgröße ein paar Minuten):
   ```bash
   python -m app.cli collect --full
   ```
4. **Starten:** `python -m app.cli serve`

> **Wichtig:** Steam liefert Spielzeiten und Errungenschaften nur für Profile, bei denen
> unter *Profil → Privatsphäre-Einstellungen* die **Spieldetails auf „Öffentlich"** stehen.
> Ist das nicht der Fall, taucht die Person zwar auf, bleibt aber leer. `app.cli add` warnt
> beim Hinzufügen, wenn ein Profil nicht öffentlich ist.

---

## Als Docker-Container (empfohlen, wenn schon andere Container laufen)

```bash
cp .env.example .env          # STEAM_API_KEY eintragen
docker compose up -d --build
```

Das startet zwei Container aus **einem** Image:

| Container | Aufgabe |
|---|---|
| `steamhub` | uvicorn, gebunden auf `127.0.0.1:8077` |
| `steamhub-collect` | Sammler im Dauerlauf, alle 30 Min (`--interval 1800`) – ersetzt cron/systemd |
| `steamhub-bot` | Discord-Bot, **nur mit** `--profile bot` (siehe unten) |

Die SQLite-Datei und `players.json` liegen im Named Volume `steamhub-data` unter `/data`,
beide Container teilen es sich (SQLite läuft im WAL-Modus, parallele Zugriffe sind
abgedeckt).

**Spieler eintragen** läuft im Container:

```bash
docker compose exec steamhub python -m app.cli add https://steamcommunity.com/id/beispiel --nick "Timmi"
docker compose exec steamhub python -m app.cli list
docker compose exec steamhub python -m app.cli collect --full     # erster Volllauf
docker compose logs -f steamhub-collect
```

**Anbindung an deinen nginx** – zwei Varianten:

- *nginx läuft auf dem Host:* nichts weiter zu tun, das Port-Mapping
  `127.0.0.1:8077:8077` steht schon. `deploy/nginx-steamhub.conf` übernehmen,
  `proxy_pass http://127.0.0.1:8077;` passt.
- *nginx läuft selbst als Container:* in `docker-compose.yml` unten das
  `networks:`-Beispiel auf dein bestehendes Proxy-Netzwerk setzen, bei `steamhub`
  `networks: [web]` aktivieren und die `ports:`-Zeile löschen. Der Proxy erreicht
  den Dienst dann als `http://steamhub:8077`.

Basic-Auth nicht vergessen – der Hub zeigt Klarnamen und Spielzeiten eurer Runde.

Backup: `docker run --rm -v steam_vfa_steamhub-data:/data -v "$PWD:/out" alpine tar czf /out/steamhub-backup.tgz -C /data .`

> Die Werte `DB_PATH`, `PLAYERS_FILE`, `HOST` und `PORT` setzt Compose bewusst selbst –
> sie überschreiben, was in der `.env` steht, damit die Daten garantiert im Volume landen.

---

## Alternativ nativ auf dem Server (IONOS, Debian/Ubuntu, nginx)

```bash
git clone <dein-repo> steamhub && cd steamhub
sudo bash deploy/install.sh
```

Das Skript legt Benutzer, Virtualenv und die systemd-Units an:

| Unit | Zweck |
|---|---|
| `steamhub.service` | uvicorn auf `127.0.0.1:8077` |
| `steamhub-collect.timer` | Sammellauf alle 30 Minuten |

Danach `deploy/nginx-steamhub.conf` auf deine Domain anpassen, verlinken und
`certbot --nginx` laufen lassen. Die Config enthält bereits **HTTP-Basic-Auth** –
bitte drin lassen: Der Hub zeigt Klarnamen, Spielzeiten und Profile eurer Runde.

Nützliches:
```bash
systemctl status steamhub
journalctl -u steamhub-collect -n 50 --no-pager
sudo -u steamhub /opt/steamhub/.venv/bin/python -m app.cli list
```

---

## Discord anbinden

Zwei Stufen, unabhängig voneinander. Stufe 1 kostet fünf Minuten und braucht keinen Bot.

### Stufe 1: Meldungen per Webhook

In Discord: **Kanal → Bearbeiten → Integrationen → Webhooks → Neuer Webhook**, URL kopieren
und in die `.env`:

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/…
PUBLIC_URL=https://steam.example.de     # optional, erscheint als Fußzeile
```

Der Sammler postet danach am Ende jedes Laufs, was neu ist:

| Meldung | Wann |
|---|---|
| 💎 Seltene Errungenschaft | weltweit unter `NOTIFY_RARE_PCT` % (Standard 5) |
| 🏆 Spiel auf 100 % | alle Errungenschaften eines Titels freigeschaltet |
| 🆕 Neuzugang im Regal | Multiplayer-Titel, den mindestens einer aus der Runde schon hat – inklusive „nur **Timmi** fehlt noch (9,99 €)" |
| 📊 Wochenrückblick | sonntags ab 18 Uhr: Spielzeit-Podium, meistgespielt, Staubfänger der Woche |

**Beim ersten Mal wird nichts nachgeholt.** Der aktuelle Bestand gilt als Ausgangslage und
landet stumm in der Tabelle `discord_sent` – sonst prasseln beim Einschalten Hunderte alter
Errungenschaften in den Channel. Danach ist jedes Ereignis über seinen Schlüssel gemerkt,
Doppelmeldungen kann es auch nach einem Neustart nicht geben. Pro Lauf gehen höchstens
20 Meldungen raus, der Rest folgt beim nächsten.

Eine kaputte Webhook-URL bricht den Sammellauf nicht ab – die Daten sind zu dem Zeitpunkt
längst geschrieben.

### Stufe 2: der Bot

1. <https://discord.com/developers/applications> → **New Application** → links **Bot**
   → *Reset Token* → Token in die `.env` unter `DISCORD_TOKEN`
2. Beim Bot **Server Members Intent** einschalten (sonst sieht er nicht, wer im Sprachkanal sitzt)
3. Unter **OAuth2 → URL Generator**: Scopes `bot` + `applications.commands`,
   Rechte *Send Messages*, *Embed Links*, *Read Message History*. Mit der erzeugten URL
   den Bot auf euren Server einladen.
4. `.env` vervollständigen und starten:

```bash
ADMIN_TOKEN=…            # Pflicht: damit schreibt der Bot in den Hub
DISCORD_TOKEN=…
DISCORD_GUILD_ID=…       # Server-ID: Befehle sind sofort da statt nach einer Stunde
DISCORD_CHANNEL_ID=…     # optional, Kanal für die Voice-Vorschläge
```

```bash
docker compose --profile bot up -d --build
docker compose logs -f steamhub-bot
```

| Befehl | Was er tut |
|---|---|
| `/zocken` | Vorschläge mit 👍/👎-Buttons – eine Reihe pro Spiel |
| `/abstimmung` | aktueller Stand, wer wofür gestimmt hat |
| `/wasgeht` | was die Leute in *deinem* Sprachkanal gerade zusammen spielen könnten |
| `/spiel <name>` | wer hat's, wer spielt's, wie weit sind die Achievements |
| `/rangliste` | die Leaderboards aus dem Web, als Embed |
| `/selten` | die seltensten Errungenschaften der Runde |
| `/verbinden` | Discord-Konto mit dem eigenen Spieler verknüpfen |

**Warum `/verbinden`?** Die Abstimmung im Web läuft auf Vertrauensbasis. In Discord weiß der
Bot dagegen, wer klickt – er löst die Discord-ID über `discord_links` zu einer SteamID auf
und schreibt die Stimme über `POST /api/discord/vote` in dieselbe Tabelle wie das Web.
Beide Seiten zeigen also immer denselben Stand. Ohne Verknüpfung ist ein Klick wirkungslos
und der Bot sagt das (nur dem Klickenden).

Der Bot hat **keinen** eigenen Datenbankzugriff, er spricht ausschließlich HTTP mit
`steamhub`. Im Compose-Netz erreicht er ihn als `http://steamhub:8077`; läuft er woanders,
setzt `HUB_URL` die Adresse. Die schreibenden Routen (`/api/discord/*`) verlangen den
`ADMIN_TOKEN` als `?token=`.

Die Buttons überleben einen Neustart des Bots: welches Spiel und welche Richtung gemeint
ist, steckt vollständig in der `custom_id` der Schaltfläche, nicht in einem Objekt im
Speicher.

---

## Wie es funktioniert

```
Steam Web API ──► app/collect.py ──► SQLite ──► app/stats.py ──► FastAPI ──► frontend/
   (+ Store-API)     alle 30 min      data/       reines SQL      /api/*      Vanilla JS
```

**Der Trick mit der Zeitreihe:** Steam liefert nur *Gesamtspielzeit*, keine Historie.
Der Sammler schreibt bei jedem Lauf einen Snapshot, wenn sich die Spielzeit geändert hat –
daraus entstehen Sessions, Feed, Chart und „gerade angesagt". Heißt aber auch: **Die
interessanten Statistiken wachsen erst mit der Zeit.** Direkt nach der Installation sind
Bibliothek, Vorschläge und Ranglisten voll, der Aktivitäts-Feed ist noch leer.

**Schonender Umgang mit den APIs:** Bibliotheken kosten einen Call pro Person und Lauf.
Achievements werden nur für relevante Paare (Spiel besitzen mehrere / meistgespielte Titel)
geholt, nur bei Spielzeitänderung erneut, und sind pro Lauf gedeckelt (`ACH_CALLS_PER_RUN`).
Die inoffizielle Store-API wird auf ca. einen Request pro 1,6 s gedrosselt.

### Dateien

| Pfad | Inhalt |
|---|---|
| `app/steam.py` | API-Client, Retry/Backoff, Kategorien-Klassifikation |
| `app/collect.py` | Sammellauf (Bibliotheken, Store-Metadaten, Achievements) |
| `app/db.py` | komplettes SQLite-Schema |
| `app/stats.py` | **alle Auswertungen** – hier neue Statistiken ergänzen |
| `app/main.py` | FastAPI-Routen (`/api/docs` zeigt sie alle) |
| `app/notify.py` | Discord-Meldungen aus dem Sammellauf (Webhook, kein Bot nötig) |
| `app/embeds.py` | Embed-Bau – von Webhook **und** Bot genutzt |
| `bot/` | der Discord-Bot: `bot.py` (Befehle, Buttons, Voice), `api.py` (HTTP zum Hub) |
| `app/cli.py` | Spieler verwalten, Demo-Daten, Seed prüfen |
| `frontend/` | Single-Page-Frontend, kein Build, keine CDN-Abhängigkeit |
| `data/coop_seed.json` | kuratierte Vorschlagsliste für „Neu entdecken" |

### Eigene Statistik ergänzen

1. Funktion in `app/stats.py` schreiben, die ein Dict/eine Liste zurückgibt
2. Route in `app/main.py` dranhängen (drei Zeilen)
3. Im Frontend in `loadDashboard()` o. ä. abholen und rendern

---

## Konfiguration (`.env`)

| Variable | Bedeutung |
|---|---|
| `STEAM_API_KEY` | Pflicht für echte Daten |
| `DB_PATH`, `PLAYERS_FILE` | Speicherorte, Standard unter `data/` |
| `STORE_LANG`, `STORE_CC` | Sprache/Land für Store-Metadaten und Preise |
| `ACH_TOP_GAMES` | wie viele Top-Spiele pro Person auf Achievements geprüft werden (Standard 40) |
| `ACH_REFRESH_HOURS` | Mindestabstand für erneute Achievement-Abfrage (Standard 168 h) |
| `ADMIN_TOKEN` | Pflicht für schreibende Zugriffe: `POST /api/collect?token=…` und alle `/api/discord/*`-Routen |
| `HOST`, `PORT` | Bind-Adresse des Webservers |
| `DISCORD_WEBHOOK_URL` | gesetzt = der Sammler meldet im Channel (Stufe 1) |
| `NOTIFY_RARE_PCT` | ab welcher Weltweit-Quote eine Errungenschaft als selten gilt (Standard 5) |
| `NOTIFY_WEEKLY_DAY`, `NOTIFY_WEEKLY_HOUR` | Wochenrückblick, Standard Sonntag 18 Uhr (0 = Montag) |
| `NOTIFY_DORMANT_DAYS` | ab wann ein Spiel als Staubfänger gilt (Standard 90 Tage) |
| `DISCORD_TOKEN` | Bot-Token (Stufe 2) |
| `DISCORD_GUILD_ID` | Server-ID – Slash-Befehle sind damit sofort verfügbar |
| `DISCORD_CHANNEL_ID` | Kanal für die Voice-Vorschläge, leer = der Sprachkanal selbst |
| `HUB_URL` | wie der Bot den Hub erreicht (Compose setzt das selbst) |
| `PUBLIC_URL` | öffentliche Adresse, erscheint als Fußzeile unter den Meldungen |
| `VOICE_MIN_PLAYERS`, `VOICE_COOLDOWN_MIN` | ab wie vielen Leuten im Sprachkanal vorgeschlagen wird und wie lange danach Ruhe ist |

## Wartung

```bash
python -m app.cli verify-seed          # appids der Vorschlagsliste gegen den Store prüfen
python -m app.cli verify-seed --fix    # Namen und Genres automatisch korrigieren
python -m app.cli remove <steamid> --purge
python -m app.collect --no-achievements
```

Backup: die Datei `data/steamhub.db` sichern, das ist alles.

## Ideen für später

- Discord-OAuth statt `/verbinden`: dann sind auch die Stimmen aus dem Web echt
- Sale-Watcher für die *Fast komplett*-Liste (Preisabfrage läuft schon mit) – als
  Discord-Meldung „das fehlende Exemplar ist gerade 70 % günstiger"
- Termin-Poll neben der Spiel-Abstimmung
- Achievement-Rennen: wer knackt Spiel X zuerst zu 100 %
