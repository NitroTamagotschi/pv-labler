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

### Aufbau von `labels.csv`

Eine Zeile pro Bilddatei (maximal); bei erneutem Speichern wird die bestehende Zeile aktualisiert. Geschrieben wird erst beim Klick auf `Save`. Die Spalten stehen in fester Reihenfolge:

| Spalte | Bedeutung |
|---|---|
| `Datum` | Datum der letzten Änderung (`YYYY-MM-DD`) |
| `Zeit` | Uhrzeit der letzten Änderung (`HH:MM:SS`) |
| `Name of labeler` | Name des angemeldeten Benutzers |
| `datename` | Dateiname der gelabelten Bilddatei |
| `uv`, `vi`, `el` | Modalitätsspalten (binär, genau eine ist `1`; `UVF` wird als `uv` gespeichert) |
| `good` + Defektspalten | Labelzustand (`0`/`1`); die Defektspalten werden aus `config.json` erzeugt |

Beispielzeile:

```csv
Datum,Zeit,Name of labeler,datename,uv,vi,el,good,crack,cross,dark,corrosion,discoloration,delamination
2026-08-16,14:32:05,Max Muster,23-P09-B1_EL_Cell001.tif,0,0,1,0,1,0,0,0,0,0
```

### Aufbau von `change_log.txt`

Append-only-Protokoll; pro gespeichertem Bild wird genau ein Eintrag angehängt. Format: Zeitstempel, Labeler, Dateiname sowie der vollständige Labelzustand vor und nach der Speicherung (in der Reihenfolge der konfigurierten Labels):

```text
2026-08-16 14:32:05 | Max Muster | 23-P09-B1_EL_Cell001.tif | before: good=0, crack=0, cross=0, dark=0, corrosion=0, discoloration=0, delamination=0 | after: good=0, crack=1, cross=0, dark=0, corrosion=0, discoloration=0, delamination=0
```

### Aufbau von `config.json`

Die Konfiguration definiert Modalitäten und Labels; sie steuert Modalitäts-Dropdown, Tabs, Checkboxen und CSV-Labelspalten. Sie wird beim Start geladen — Änderungen erfordern einen Neustart:

```json
{
  "modal_max_width": 1200,
  "modal_max_height": 800,
  "modalities": [
    { "code": "VI", "display_name": "VI", "filename_code": "VI" },
    { "code": "EL", "display_name": "EL", "filename_code": "EL" },
    { "code": "UVF", "display_name": "UVF", "filename_code": "UV" }
  ],
  "labels": {
    "good": { "key": "good", "display_name": "Good" },
    "defects": [
      { "key": "crack", "display_name": "Crack" },
      { "key": "cross", "display_name": "Cross" }
    ]
  }
}
```

- `modalities[].code` – Code für UI und CSV-Spalte (`UVF` wird als `uv` gespeichert); `display_name` – Anzeige im Dropdown und auf den Karten.
- `modalities[].filename_code` – optional, der im Dateinamen verwendete String (Standard: `code`), z. B. `"filename_code": "UV"` für Dateien mit `..._UV_...`.
- `labels.good` / `labels.defects[]` – jeweils `key` und `display_name`; jedes Defektlabel erzeugt einen Tab und eine CSV-Spalte.
- Optional: `modal_max_width` / `modal_max_height` – maximale Breite bzw. Höhe des Gruppierungs-Modals in Pixeln (Breiten-Standard 1100, Höhen-Standard 90 % der Fensterhöhe; Minimum jeweils 200). Die Höhe übersteigt nie die Fensterhöhe.
- Reserviert: der Modalitäts-Code `all` sowie die Label-Keys `all` und `unclassified` (Kollision mit Tab-Keys).

## Daten

- `data/images/` – Quellbilder, Muster `<Solarzellentyp>_<Modalität>[_<Variante>...]_<Zelle>[_<Zusatz>...].<ext>` (`.tif`, `.tiff`, `.jpg`, `.jpeg`, `.png`). Die Modalität darf ein Ziffernsuffix tragen (`EL01` → EL), die Zelle wird am Muster `Cell<Zahl>` erkannt, alles dazwischen/dahinter ist Variante: z. B. `23-P09-B1_EL_Cell001.tif`, `23_089_A1_EL_LR_Cell001.jpg`, `23-P09-A2_EL_Cell114_normalized.tif`. Bilder dürfen in Unterordnern liegen; der Identifikator ist dann der relative Pfad (z. B. `nested/23-P09-B1_EL_Cell004.tif`)
- `data/labels.csv` – aktueller Labelstatus (max. eine Zeile pro Bilddatei; Aufbau siehe [Bedienung](#aufbau-von-labelscsv))
- `data/change_log.txt` – Änderungslog (wird ausschließlich ergänzt; Aufbau siehe [Bedienung](#aufbau-von-change_logtxt))
- `config.json` – Modalitäten und Labels (Aufbau siehe [Bedienung](#aufbau-von-configjson))
- `static/previews/` – automatisch erzeugte JPEG-Vorschauen der TIFF-Quellen ohne Normalisierung: 8-Bit wird unverändert übernommen, 16-Bit auf das High-Byte reduziert, Float mit 255 skaliert (Cache, Originale bleiben unverändert). Vorschauen sind maximal 2048 px groß; im Gruppierungs-Modal lässt sich per Mausrad in jedes Bild zoomen (Ziehen zum Verschieben, Doppelklick setzt zurück)

## Entwicklung

### Tests (pytest)

Die UI-Tests sind mit `@pytest.mark.ui` markiert und standardmäßig ausgeschlossen (siehe `[tool.pytest.ini_options]` in `pyproject.toml`):

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

### Code-Qualität (ruff)

Ruff prüft Lint und formatiert das Projekt. Die Regeln stehen in `[tool.ruff]` in `pyproject.toml` (E, W, F, I, B, UP, D, ANN) und gelten automatisch für jeden Lauf:

```bash
uv run ruff check .            # Lint-Check
uv run ruff check . --fix      # sichere Autofixes anwenden
uv run ruff format .           # Formatierung anwenden
uv run ruff format --check .   # Formatierung nur prüfen (z. B. für CI)
```

Die Docstring- (D) und Typannotation-Regeln (ANN) gelten für den Produktionscode; Testdateien sind über per-file-ignores davon ausgenommen.
