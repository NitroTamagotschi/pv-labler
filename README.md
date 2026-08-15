# PV Labeling Tool

Webbasierte Anwendung zum Labeln multispektraler Solarzellen-Bilder.
Implementiert nach [specification/specification.md](specification/specification.md) (Python / Flask).

## Setup

Voraussetzungen: [uv](https://docs.astral.sh/uv/) und Python ≥ 3.10.

```bash
uv sync                                           # installiert alle Dependencies
uv run python scripts/create_sample_images.py     # optional: Demo-Bilder erzeugen (Defekte als Text, nur auf den Modalitäten sichtbar, auf denen sie laut Sichtbarkeitstabelle erkennbar sind)
uv run python app.py                              # startet auf http://127.0.0.1:5000
```

## Bedienung

1. Login mit Namen (kein Passwort, Feld ist Pflichtfeld).
2. Bildmodalität im Dropdown wählen; der gewählte Tab-Filter bleibt beim Wechsel erhalten. Über das `Cell type`-Dropdown lässt sich zusätzlich auf einzelne Solarzellentypen filtern (bleibt ebenfalls beim Modalitätswechsel erhalten).
3. Labels direkt auf der Bildkarte setzen (`Good` schließt Defekte aus und umgekehrt). Änderungen werden erst per `Save` gespeichert (Button oben rechts, zeigt die Anzahl geänderter Bilder); bei ungespeicherten Änderungen fragt der Browser beim Verlassen der Seite nach.
4. Der letzte Tab `All` zeigt alle Bilder der gewählten Modalität unabhängig vom Labelstatus.
5. Klick auf Vorschaubild oder Dateinamen öffnet das Pop-up mit allen Modalitäten der Bildgruppe.

## Daten

- `data/images/` – Quellbilder, Muster `<Solarzellentyp>_<Modalität>[_<Variante>...]_<Zelle>[_<Zusatz>...].<ext>` (`.tif`, `.tiff`, `.jpg`, `.jpeg`, `.png`). Die Modalität darf ein Ziffernsuffix tragen (`EL01` → EL), die Zelle wird am Muster `Cell<Zahl>` erkannt, alles dazwischen/dahinter ist Variante: z. B. `23-P09-B1_EL_Cell001.tif`, `23_089_A1_EL_LR_Cell001.jpg`, `23-P09-A2_EL_Cell114_normalized.tif`
- `data/labels.csv` – aktueller Labelstatus (max. eine Zeile pro Bilddatei)
- `data/change_log.txt` – Änderungslog (wird ausschließlich ergänzt)
- `config.json` – Modalitäten und Labels; steuert UI, Tabs, Checkboxen und CSV-Labelspalten. Pro Modalität legt das optionale Feld `filename_code` den im Dateinamen verwendeten String fest (Standard: `code`), z. B. `"filename_code": "UV"` für Dateien mit `..._UV_...`
- `static/previews/` – automatisch erzeugte JPEG-Vorschauen der TIFF-Quellen (Cache, Originale bleiben unverändert)

## Tests

```bash
uv run pytest              # Unit- und Integrationstests (ohne UI)
uv run pytest -m ui        # UI-Tests (Playwright, headless)
```

### UI-Tests (Playwright)

Einmalig den Browser installieren:

```bash
uv run playwright install chromium
```

Die UI-Suite startet die App mit frisch generierten Testbildern in Temp-Verzeichnissen und prüft u. a. den kompletten Round-Trip: Bilder werden über die Checkboxen gemäß dem Generator-Zeitplan gelabelt und per `Save` gespeichert, danach wird `labels.csv` gegen die Ground Truth verglichen, und das Change-Log wird geprüft.

Die erzeugten `labels.csv`/`change_log.txt` landen dabei in den Temp-Verzeichnissen von pytest (nicht in `data/`) und entstehen erst beim ersten Klick auf `Save`. Zum Inspizieren während des Debuggens können die Temp-Dateien über `--basetemp` im Projekt abgelegt werden:

```bash
uv run pytest -m ui --basetemp=.pytest-tmp   # Dateien danach unter .pytest-tmp/.../data/ einsehbar
```

Zum **Zuschauen** (sichtbares Fenster, Aktionen verlangsamt):

```bash
uv run pytest -m ui --headed --slowmo 500
```

Bei Fehlschlägen Video/Trace aufzeichnen:

```bash
uv run pytest -m ui --video on --tracing retain-on-failure
# Trace interaktiv ansehen:
uv run playwright show-trace test-results/.../trace.zip
```
