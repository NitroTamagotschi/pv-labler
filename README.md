# PV Labeling Tool

Webbasierte Anwendung zum Labeln multispektraler Solarzellen-Bilder.
Implementiert nach [specification/specification.md](specification/specification.md) (Python / Flask).

## Setup

Voraussetzungen: [uv](https://docs.astral.sh/uv/) und Python ≥ 3.10.

```bash
uv sync                                           # installiert alle Dependencies
uv run python scripts/create_sample_images.py     # optional: Demo-Bilder erzeugen
uv run python app.py                              # startet auf http://127.0.0.1:5000
```

## Bedienung

1. Login mit Namen (kein Passwort, Feld ist Pflichtfeld).
2. Bildmodalität im Dropdown wählen; der gewählte Tab-Filter bleibt beim Wechsel erhalten. Über das `Cell type`-Dropdown lässt sich zusätzlich auf einzelne Solarzellentypen filtern (bleibt ebenfalls beim Modalitätswechsel erhalten).
3. Labels direkt auf der Bildkarte setzen (`Good` schließt Defekte aus und umgekehrt).
4. Klick auf Vorschaubild oder Dateinamen öffnet das Pop-up mit allen Modalitäten der Bildgruppe.

## Daten

- `data/images/` – Quellbilder, Muster `<Solarzellentyp>_<Modalität>[_<Variante>...]_<Zelle>[_<Zusatz>...].<ext>` (`.tif`, `.tiff`, `.jpg`, `.jpeg`, `.png`). Die Modalität darf ein Ziffernsuffix tragen (`EL01` → EL), die Zelle wird am Muster `Cell<Zahl>` erkannt, alles dazwischen/dahinter ist Variante: z. B. `23-P09-B1_EL_Cell001.tif`, `23_089_A1_EL_LR_Cell001.jpg`, `23-P09-A2_EL_Cell114_normalized.tif`
- `data/labels.csv` – aktueller Labelstatus (max. eine Zeile pro Bilddatei)
- `data/change_log.txt` – Änderungslog (wird ausschließlich ergänzt)
- `config.json` – Modalitäten und Labels; steuert UI, Tabs, Checkboxen und CSV-Labelspalten. Pro Modalität legt das optionale Feld `filename_code` den im Dateinamen verwendeten String fest (Standard: `code`), z. B. `"filename_code": "UV"` für Dateien mit `..._UV_...`
- `static/previews/` – automatisch erzeugte JPEG-Vorschauen der TIFF-Quellen (Cache, Originale bleiben unverändert)

## Tests

```bash
uv run pytest
```
