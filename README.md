# PV Labeling Tool

Webbasierte Anwendung zum Labeln multispektraler Solarzellen-Bilder.
Implementiert nach [specification/specification.md](specification/specification.md) (Python / Flask).

## Setup

Voraussetzungen:

- **Python ≥ 3.10**: muss installiert und über die Kommandozeile erreichbar sein (Prüfung: `python --version`). Download: <https://www.python.org/downloads/> — bei der Windows-Installation das Häkchen „Add python.exe to PATH“ setzen.
- **uv**: der Paketmanager des Projekts; er installiert alle Abhängigkeiten und führt Skripte und Tests aus (Prüfung: `uv --version`). Installation: <https://docs.astral.sh/uv/getting-started/installation/>.

```bash
# installiert alle Dependencies
uv sync

# App starten (http://127.0.0.1:5000)
uv run python app.py
```

Demo-Bilder erzeugen (optional — 8-Bit, Defekte als Text eingeblendet, nur auf den Modalitäten sichtbar, auf denen sie laut Sichtbarkeitstabelle erkennbar sind):

```bash
uv run python scripts/create_sample_images.py
```

## Bedienung

1. Login mit Namen (kein Passwort, Feld ist Pflichtfeld).
2. Bildmodalität im Dropdown wählen; der gewählte Tab-Filter bleibt beim Wechsel erhalten. Über das `Cell type`-Dropdown lässt sich zusätzlich auf einzelne Solarzellentypen filtern (bleibt ebenfalls beim Modalitätswechsel erhalten). Über `Preview-Window` in der Kopfzeile lassen sich die Min/Max-Werte des Vorschau-Fensters der gewählten Modalität live einstellen — per Regler oder durch direkte Zahleneingabe (Enter übernimmt). Daneben invertiert die Checkbox `Invertieren` die gerenderten Vorschauen der Modalität. Das Panel zeigt die Bittiefe der Bilder der Modalität (`8-Bit`/`16-Bit`/`Float`) an; Änderungen werden in die `config.json` zurückgeschrieben (`Reset` entfernt die Einträge).
3. Über das Suchfeld in der Kopfzeile lässt sich die Galerie nach Dateinamen filtern (Eingabe mit `Enter` oder `Suchen` bestätigen; `✕` entfernt nur die Suche). Groß-/Kleinschreibung ist egal. Ohne Wildcards gilt die Eingabe als Teiltextsuche (`Cell045` findet z. B. `C14_A6_EL_Cell045_normalized.tif`); mit Wildcards als Glob-Muster mit implizitem `*` am Ende — `*` steht für beliebig viele Zeichen, `?` für genau eines. Beispiel: `C14_A6*Cell045` findet `C14-A/EL/C14_A6_EL_Cell045_normalized.tif`. Gesucht wird in Dateiname und Pfad, daher funktionieren auch Ordner wie `C14-A/*`. Die Suche kombiniert sich mit Modalität, Tab und Zelltyp-Filter und bleibt beim Filterwechsel und nach dem Speichern erhalten.
4. Labels direkt auf der Bildkarte setzen (`Good` schließt Defekte aus und umgekehrt). Änderungen werden erst per `Save` gespeichert (Button oben rechts, zeigt die Anzahl geänderter Bilder) — alternativ über die Tastenkombination `Strg+S` (wirkt wie ein Klick auf `Save`, auch mit offenem Pop-up); bei ungespeicherten Änderungen fragt der Browser beim Verlassen der Seite nach.
5. Der letzte Tab `All` zeigt alle Bilder der gewählten Modalität unabhängig vom Labelstatus. Die Galerie lädt Karten in Schüben (zunächst 100; beim Scrollen ans Ende kommen automatisch weitere dazu), damit auch sehr große Bildmengen flüssig bedienbar bleiben.
6. Klick auf Vorschaubild oder Dateinamen öffnet das Pop-up mit allen Modalitäten der Bildgruppe.
7. Im Pop-up wird standardmäßig das Original-TIFF direkt im Browser angezeigt (Dekodierung per UTIF, mit Min/Max-Reglern für den Dynamikbereich). Mausrad zoomt in alle Bilder synchron (Ziehen verschiebt, Doppelklick setzt zurück). Über `Vorschau` wechselt man zur JPEG-Vorschau, über `Download` lädt man die Originaldatei herunter. `Invertieren` invertiert jeweils ein Bild, `Alle invertieren` im Kopfbereich alle Bilder auf einmal (bzw. setzt alle zurück, wenn bereits alle invertiert sind); die Invertierung ist flüchtig und wirkt in Vorschau- und Originalansicht.
8. Über `Vergleich` in der Kopfzeile lassen sich die gespeicherten Labels mit bis zu zwei weiteren CSV-Dateien vergleichen, z. B. mit den Ergebnissen einer KI (siehe [Vergleichsmodus](#vergleichsmodus)).

### Min/Max-Regler der Original-Ansicht

Die zwei Regler unter jedem Original-Bild legen fest, welcher Ausschnitt des Roh-Wertebereichs auf die 8-Bit-Anzeige abgebildet wird:

- `Min` – **Schwarzpunkt**: alle Rohwerte darunter werden schwarz (0) angezeigt.
- `Max` – **Weißpunkt**: alle Rohwerte darüber werden weiß (255) angezeigt; Werte dazwischen werden linear auf 0–255 gespreizt.
- `Reset` – zurück zum vollen Datenbereich des Bildes.

Die Regler zeigen ihren aktuellen Wert direkt am Label an; daneben steht die **Bittiefe** des geöffneten Bildes (`8-Bit`/`16-Bit`/`32-Bit`). Der Startzustand ist der volle Datenbereich (Min = kleinster, Max = größter Messwert) — die neutrale Darstellung, die auch die JPEG-Vorschau zeigt. Einstellbar ist der gesamte native Wertebereich des Bildes (8-Bit: 0–255, 16-Bit: 0–65535, Float: 0–1) — z. B. Min=0/Max=255 für die rohe 1:1-Darstellung, wie sie die Windows-Fotoanzeige zeigt. Das **Fenster verengen erhöht den Kontrast**: Kleine Helligkeitsunterschiede innerhalb des gewählten Bereichs werden sichtbar. Das **Fenster verschieben** hellt dunkle Bereiche gezielt auf bzw. dunkelt helle ab — z. B. um in dunkle EL-Aufnahmen „hineinzuleuchten". Die Regler verändern ausschließlich die Anzeige; die Bilddaten und die gespeicherten Dateien bleiben unangetastet. Gefundene Werte lassen sich über das `Preview-Window`-Panel im Hauptmenü in die `config.json` übernehmen.

### Vergleichsmodus

Der Vergleichsmodus stellt die Labels aus `labels.csv` (in der Oberfläche „Labeler“) den Ergebnissen einer oder zweier weiterer CSV-Dateien gegenüber – typischerweise KI-Ergebnissen wie `data/results_taxonomy gpt-6.1-sol.csv`.

- **Quellen wählen:** Das Panel `Vergleich` listet alle `*.csv`-Dateien direkt in `data/` (ohne Unterordner); `labels.csv` selbst wird nie angeboten. Bis zu zwei Dateien ankreuzen und `Übernehmen` – der Vergleich ist aktiv, solange mindestens eine Quelle gewählt ist, `Vergleich beenden` schaltet zurück. Dateien ohne passende Spalten erscheinen ausgegraut mit Begründung. Die Auswahl steht wie die übrigen Filter in der URL und bleibt beim Speichern sowie beim Wechsel von Modalität, Zelltyp und Suche erhalten.
- **Legende:** Die Quellen heißen in der Oberfläche `A` und `B`. Unter den Tabs stehen Dateiname, Modell bzw. Labeler und die Zahl der zugeordneten Bilder, ggf. mit Warnung bei Zeilen ohne passendes Bild oder doppelten Zeilen.
- **Tabs:** `Abweichungen` (mindestens ein bewertetes Label weicht ab) · `<Label> ≠` je Label (genau dieses Label weicht ab; `–`, wenn die Quelle es in der aktuellen Auswahl nicht bewertet hat) · `Übereinstimmung` (alle bewerteten Labels stimmen überein) · `Unsicher` (die Quelle hat ihr Ergebnis als unsicher markiert; nur bei vorhandener Spalte `uncertain`) · `Nicht vergleichbar` (Bild in `labels.csv` noch ohne Label oder ohne gültiges Ergebnis der Quelle) · `All`.
- **Richtung:** In einem Label-Tab trennt `Richtung` die Abweichungen nach Seite: `Labeler ✓ · A ✗` (nur der Labeler hat das Label gesetzt) bzw. `Labeler ✗ · A ✓` (nur die Quelle).
- **Zwei Quellen:** `Abweichung zu` beschränkt die Tabs auf eine Quelle; `A oder B` (Standard) zeigt Abweichungen zu mindestens einer der beiden.
- **Karten:** Neben jeder Checkbox des Labelers steht pro Quelle deren Wert (`✓` gesetzt, leeres Kästchen nicht gesetzt, `–` nicht bewertet). Abweichende Zeilen sind rot hinterlegt, Karten mit Abweichung rot umrandet. Die Checkboxen bleiben bearbeitbar: Die Markierung folgt ungespeicherten Änderungen sofort, gespeichert wird wie gewohnt mit `Save` (die Vergleichs-CSV bleibt unverändert). Unter den Labels stehen ggf. `kein Ergebnis`, `ungültiges Ergebnis`, `unsicher` und die aufklappbare `Begründung` der Quelle.
- **Statistik:** Das aufklappbare Panel `Statistik` zeigt je Quelle die Zahl der verglichenen, übereinstimmenden und abweichenden Bilder sowie pro Label die Konfusionswerte (`beide ✓`, `Labeler ✓ · A ✗`, `Labeler ✗ · A ✓`, `beide ✗`), die Übereinstimmung, Cohens κ und Precision, Recall und F1 mit dem Labeler als Referenz. Grundlage ist die aktuelle Auswahl (Modalität, Cell type, Suche) unabhängig vom Tab; ein Klick auf eine Abweichungszahl öffnet genau diese Bilder.

**Vergleichslogik:** Pro Label gilt der Wert einer Quelle als `1` (gesetzt), `0` (nicht gesetzt) oder – bei leerer Zelle – als *nicht bewertet*. Nicht bewertete Labels zählen nie als Abweichung (die KI bewertet z. B. auf VI nur `good` und `discoloration`). Bilder, die in `labels.csv` noch kein Label haben, werden nicht verglichen.

**Aufbau einer Vergleichs-CSV:** Eine Zeile pro Bild, Spaltennamen ohne Beachtung der Groß-/Kleinschreibung; komma- oder (wie bei Excel) semikolongetrennt, UTF-8 mit oder ohne BOM.

| Spalte                            | Bedeutung                                                                                                                                                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `image_path` oder `file_name`     | Bild der Zeile (Pflicht). Absolute Pfade eines anderen Rechners werden über ihr Ende dem relativen Bildpfad zugeordnet (`…/normalized_images/23-P09-A/VI/x.tif` → `23-P09-A/VI/x.tif`), sonst über einen eindeutigen Dateinamen.                  |
| Labelspalten (`good`, `crack`, …) | Label-Keys aus `config.json`, mindestens eine (Pflicht). `1`/`0` (auch `1.0`/`0.0`, `true`/`false`); leer = nicht bewertet. Fehlende Labelspalten gelten als nicht bewertet; eine Zeile ohne ein einziges bewertetes Label gilt als ungültig. |
| `valid_result`                    | optional; `0` markiert das Ergebnis als ungültig – es wird nicht verglichen.                                                                                                                                                                      |
| `uncertain`                       | optional; `1` markiert das Ergebnis als unsicher (Tab `Unsicher`).                                                                                                                                                                                |
| `visual_status`                   | optional; Begründung der Quelle, aufklappbar auf der Karte (alternativ `reasoning`, `explanation`, `comment` oder `note`).                                                                                                                         |
| `model` bzw. `labeler`            | optional; Anzeige in der Legende.                                                                                                                                                                                                                 |

Weitere Spalten werden ignoriert. Kommt ein Bild mehrfach vor, gilt die letzte Zeile. Auch Dateien im `labels.csv`-Schema (z. B. ein zweiter Labeler oder die `ground_truth.csv` des Sample-Generators) sind gültige Vergleichsquellen.

### Aufbau von `labels.csv`

Eine Zeile pro Bilddatei (maximal); bei erneutem Speichern wird die bestehende Zeile aktualisiert. Geschrieben wird erst beim Klick auf `Save`. Die Spalten stehen in fester Reihenfolge:

| Spalte                 | Bedeutung                                                                      |
| ---------------------- | ------------------------------------------------------------------------------ |
| `date`                 | Datum der letzten Änderung (`YYYY-MM-DD`)                                      |
| `time`                 | Uhrzeit der letzten Änderung (`HH:MM:SS`)                                      |
| `labeler`              | Name des angemeldeten Benutzers                                                |
| `image_path`           | Dateiname der gelabelten Bilddatei                                             |
| `uv`, `vi`, `el`       | Modalitätsspalten (binär, genau eine ist `1`; `UVF` wird als `uv` gespeichert) |
| `good` + Defektspalten | Labelzustand (`0`/`1`); die Defektspalten werden aus `config.json` erzeugt     |

Beispielzeile:

```csv
date,time,labeler,image_path,uv,vi,el,good,crack,cross,dark,corrosion,discoloration,delamination
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
- Optional: `modal_max_width` / `modal_max_height` – maximale Breite bzw. Höhe des Bildgruppen-Pop-up-Fensters in Pixeln (Breiten-Standard 1100, Höhen-Standard 90 % der Fensterhöhe; Minimum jeweils 200). Die Höhe übersteigt nie die Fensterhöhe.
- Optional pro Modalität: `preview_min` / `preview_max` – lineares Vorschau-Fenster in Rohwerten (außerhalb wird geklemmt) für die JPEG-Vorschau von Ganzzahl-Daten; ohne Angabe bleibt das High-Byte- bzw. 1:1-Verhalten. Das Fenster wird pro Bild auf dessen nativen Wertebereich geklemmt — ein 16-Bit-Fenster kann 8-Bit-Bilder also nicht „zerdrücken" (und umgekehrt).
- Optional pro Modalität: `preview_invert` – boolescher Schalter, der die Vorschau invertiert (Komplement der gemappten 8-Bit-Werte, `255 − Wert`); unabhängig vom Fenster und auch allein setzbar.
- Optional: `images_dir` – absoluter Pfad zum Ordner mit den Quellbildern (statt `data/images/`); der Ordner muss existieren und wird nicht automatisch angelegt. Die `image_path`-Werte in `labels.csv` bleiben relativ zu diesem Ordner.
- Reserviert: der Modalitäts-Code `all` sowie die Label-Keys `all` und `unclassified` (Kollision mit Tab-Keys).

## Daten

- `data/images/` – Quellbilder, Muster `<Solarzellentyp>_<Modalität>[_<Variante>...]_<Zelle>[_<Zusatz>...].<ext>` (`.tif`, `.tiff`, `.jpg`, `.jpeg`, `.png`). Die Modalität darf ein Ziffernsuffix tragen (`EL01` → EL), die Zelle wird am Muster `Cell<Zahl>` erkannt, alles dazwischen/dahinter ist Variante: z. B. `23-P09-B1_EL_Cell001.tif`, `23_089_A1_EL_LR_Cell001.jpg`, `23-P09-A2_EL_Cell114_normalized.tif`. Bilder dürfen in Unterordnern liegen; der Identifikator ist dann der relative Pfad (z. B. `nested/TEST_23-P09-B1_EL_Cell004.tif`). Alternativ zeigt der optionale Config-Eintrag `images_dir` auf einen anderen Ordner.
- `data/labels.csv` – aktueller Labelstatus (max. eine Zeile pro Bilddatei; Aufbau siehe [Bedienung](#aufbau-von-labelscsv))
- `data/change_log.txt` – Änderungslog (wird ausschließlich ergänzt; Aufbau siehe [Bedienung](#aufbau-von-change_logtxt))
- `data/*.csv` (außer `labels.csv`) – werden im Panel `Vergleich` als Vergleichsquellen angeboten, z. B. KI-Ergebnisse (Aufbau siehe [Vergleichsmodus](#vergleichsmodus))
- `config.json` – Modalitäten und Labels (Aufbau siehe [Bedienung](#aufbau-von-configjson))
- `static/previews/` – automatisch erzeugte JPEG-Vorschauen der TIFF-Quellen ohne Normalisierung: 8-Bit wird unverändert übernommen, 16-Bit auf das High-Byte reduziert (oder per `preview_min`/`preview_max` auf ein Fenster gemappt), Float mit 255 skaliert; per `preview_invert` werden die gemappten Werte komplementiert (Cache, Originale bleiben unverändert). Vorschauen sind maximal 2048 px groß; im Gruppierungs-Modal lässt sich per Mausrad in jedes Bild zoomen (Ziehen zum Verschieben, Doppelklick setzt zurück)

## Entwicklung

### Labeldaten konvertieren (`approved_OLLM…` → `labels.csv`)

`scripts/convert_approved_labels.py` übernimmt Labeldaten aus einem OLLM-Export (Spalten `filename,labels`, Labels leerzeichengetrennt, z. B. `dark discoloration`) in das `labels.csv`-Schema:

```bash
uv run python scripts/convert_approved_labels.py [approved.csv] --labeler "Max Muster"
```

- **`--labeler`** – Pflichtargument, wird in die Spalte `labeler` geschrieben.
- **Bildpfad-Auflösung**: Für jede Zeile wird das Bilder-Verzeichnis (Config-Eintrag `images_dir`, Standard `data/images/`, per `--images-dir` übersteuerbar) rekursiv durchsucht und der tatsächliche relative Pfad des Bildes als `image_path` übernommen — die Labels passen damit immer zu dem, was die App anzeigt. Ein im Export enthaltener Ordnerpfad zählt nur, wenn er exakt existiert.
- **Modalität**: Das Modalitätssegment im Dateinamen (`_VI_`/`_EL_`/`_UV_`) füllt die Spalten `uv`/`vi`/`el`; Mehrfachzeilen für dasselbe Bild werden gemerged (Vereinigung der Labels).
- **Ausgaben**: Der Default-Zielpfad ist `<name>_converted.csv` neben der Quelldatei — `data/labels.csv` wird nur angefasst, wenn `--output` explizit darauf zeigt. Bestehende Zeilen des Ziels werden per `image_path` aktualisiert, andere bleiben unangetastet.
- **Fehler-Report**: Einträge, die nicht korrekt verarbeitet werden können (Bild fehlt oder Pfad mehrdeutig, Label nicht in `config.json` definiert, Modalität fehlt im Dateinamen, Labels leer), landen in `<output stem>_failed.csv` (Spalten `filename,labels,reason`) und werden zusätzlich auf der Konsole ausgegeben; der Exit-Code ist dann `1`.
- `--dry-run` zeigt Zeilen und Report an, ohne zu schreiben.

### CSV-Dateien zusammenführen (`merge_csv.py`)

`scripts/merge_csv.py` fasst alle `*.csv`-Dateien eines Ordners (in sortierter Reihenfolge) zeilenweise zu einer einzigen CSV zusammen; doppelte Zeilen bleiben erhalten. Neben der Ausgabedatei wird ein Protokoll `<output stem>_report.txt` geschrieben:

```bash
uv run python scripts/merge_csv.py [ordner] -o merged.csv
```

- **`ordner`** – Ordner mit den CSV-Dateien (Standard: `./csv_ordner`); enthält er keine `*.csv`-Dateien, bricht das Skript mit Fehlermeldung und Exit-Code `1` ab.
- **`-o`/`--output`** – Ausgabedatei (Standard: `merged.csv`); die Ausgabe wird mit UTF-8 geschrieben, fehlende Unterordner des Zielpfads werden angelegt.
- **Protokoll**: `<output stem>_report.txt` enthält Zeitpunkt, Quelle, pro Datei die Zeilen- und Spaltenanzahl, von der ersten Datei abweichende Spaltensätze, doppelte Zeilen samt Quelldatei und Zeilennummern (max. 20 Gruppen aufgelistet) sowie die Gesamtzahlen.
- **Hinweis**: Dateien mit einer Spalte `_quelle` führen zum Abbruch — diese Spalte ist intern für die Protokollierung reserviert und darf in den Eingabedaten nicht vorkommen.

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

Die UI-Suite startet die App mit frisch generierten Testbildern in Temp-Verzeichnissen und prüft u. a. den kompletten Round-Trip: Der Generator schreibt dabei eine `ground_truth.csv` (im `labels.csv`-Schema) als Referenz; die Bilder werden über die Checkboxen gemäß dieser Datei gelabelt und per `Save` gespeichert, danach wird `labels.csv` Spalte für Spalte gegen `ground_truth.csv` verglichen, und das Change-Log wird geprüft.

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

## Lizenz

© 2026 Kevin Fuhrer · Dieses Projekt ist unter der GNU General Public License v3.0 lizenziert — der vollständige Lizenztext steht in [LICENSE](LICENSE).
