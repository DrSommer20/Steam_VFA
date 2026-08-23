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
| `ADMIN_TOKEN` | wenn gesetzt: `POST /api/collect?token=…` stößt einen Lauf an |
| `HOST`, `PORT` | Bind-Adresse des Webservers |

## Wartung

```bash
python -m app.cli verify-seed          # appids der Vorschlagsliste gegen den Store prüfen
python -m app.cli verify-seed --fix    # Namen und Genres automatisch korrigieren
python -m app.cli remove <steamid> --purge
python -m app.collect --no-achievements
```

Backup: die Datei `data/steamhub.db` sichern, das ist alles.

## Ideen für später

- Discord-Webhook: „Timmi hat gerade ein seltenes Achievement geholt"
- Sale-Watcher für die *Fast komplett*-Liste (Preisabfrage läuft schon mit)
- Termin-Poll neben der Spiel-Abstimmung
- Achievement-Rennen: wer knackt Spiel X zuerst zu 100 %
