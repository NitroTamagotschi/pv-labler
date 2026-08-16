# Spezifikation: Multispektrales Labeling-Tool für Solarzellen-Bilder

## 1. Zweck und Überblick

Es soll eine webbasierte Anwendung entwickelt werden, mit der multispektrale Bilder von Solarzellen gelabelt werden können. Das Tool dient der manuellen Klassifikation von Bildern in die Kategorie **Good** oder in eine bzw. mehrere Defektkategorien.

Die Anwendung wird in **Python** entwickelt und mit dem Webframework **Flask** umgesetzt.

### 1.1 Ziele

- Benutzer melden sich mit ihrem Namen an.
- Bilder können je Bildmodalität separat gelabelt werden.
- Mehrere Defekte können pro Bild gleichzeitig gesetzt werden.
- Ein Bild mit dem Label `Good` darf keine Defektlabels enthalten.
- Bilder lassen sich nach Modalität und Labelstatus filtern.
- Alle Änderungen werden protokolliert.
- Der aktuelle Labelstatus wird in einer CSV-Datei gespeichert.
- Defektkategorien und Bildmodalitäten werden über eine JSON-Konfigurationsdatei definiert.

## 2. Begriffe

| Begriff | Bedeutung |
|---|---|
| Solarzellentyp | Der erste Teil eines Dateinamens, z. B. `23-P09-B1`. |
| Bildidentifikator | Kennzeichnet eine einzelne Zelle, z. B. `Cell001`. |
| Bildmodalität | Spektrale Aufnahmeart eines Bildes: `VI`, `EL` oder `UVF`. |
| Bildgruppe | Die drei zu derselben Solarzelle gehörenden Aufnahmen in den Modalitäten VI, EL und UVF. |
| Label | Ein Klassifikationswert: `Good` oder eine Defektkategorie. |
| Unclassified | Ansichtsstatus für Bilder, für die noch kein Label gesetzt wurde; kein in der CSV gespeichertes Label. |
| Alle-Tab | Ansicht, die alle Bilder der gewählten Modalität unabhängig vom Labelstatus anzeigt. |
| Ungespeicherte Änderung | Eine Labeländerung, die über Checkboxen vorgenommen, aber noch nicht über den `Save`-Button gespeichert wurde. |

## 3. Label- und Modalitätskonfiguration

### 3.1 Standard-Bildmodalitäten

- `VI`: Visual Image / sichtbares Spektrum
- `EL`: Elektrolumineszenz
- `UVF`: Ultraviolett-Fluoreszenz

> Hinweis: In der bestehenden Dateinamensbeschreibung wird die UV-Modalität als `UV` genannt, während die fachliche Bezeichnung `UVF` lautet. Der tatsächlich verwendete Dateinamen-Code muss in der JSON-Konfiguration festgelegt werden. Die Anwendung darf keine Modalitätscodes fest im Quellcode voraussetzen.

### 3.2 Standard-Labels

- `Good`
- `Crack`
- `Cross`
- `Dark`
- `Corrosion`
- `Discoloration`
- `Delamination`

### 3.3 JSON-Konfigurationsdatei

Dateiname: `config.json`

```json
{
  "modal_max_width": 1100,
  "modal_max_height": 800,
  "modalities": [
    { "code": "VI", "display_name": "VI" },
    { "code": "EL", "display_name": "EL" },
    { "code": "UVF", "display_name": "UVF" }
  ],
  "labels": {
    "good": { "key": "good", "display_name": "Good" },
    "defects": [
      { "key": "crack", "display_name": "Crack" },
      { "key": "cross", "display_name": "Cross" },
      { "key": "dark", "display_name": "Dark" },
      { "key": "corrosion", "display_name": "Corrosion" },
      { "key": "discoloration", "display_name": "Discoloration" },
      { "key": "delamination", "display_name": "Delamination" }
    ]
  }
}
```

Die Benutzeroberfläche, die Filter-Tabs, die Checkboxen und die CSV-Labelspalten sollen aus dieser Konfiguration erzeugt werden, soweit dies technisch sinnvoll möglich ist.

Optional können `modal_max_width` und `modal_max_height` gesetzt werden: maximale Breite bzw. Höhe des Bildgruppen-Pop-ups in Pixeln (Breiten-Standard: 1100, Höhen-Standard: 90 % der Fensterhöhe; Minimum jeweils 200). Die Höhe übersteigt nie die Fensterhöhe.

Optional können pro Modalität `preview_min` und `preview_max` gesetzt werden (gemeinsam, `min < max`): ein lineares Anzeigefenster in Rohwerten für die JPEG-Vorschau von Ganzzahl-Daten, außerhalb des Fensters wird geklemmt. Das Fenster wird pro Bild auf dessen nativen Wertebereich geklemmt. Ohne Angabe werden 8-Bit-Werte unverändert übernommen und bei 16-Bit das High-Byte verwendet. Die Werte können zur Laufzeit über das Preview-Window-Panel der Oberfläche geändert werden; die Anwendung schreibt Änderungen in die `config.json` zurück.

## 4. Bilddateien und Zuordnung

### 4.1 Dateinamensformat

Die Bilddateien folgen dem Muster:

```text
<Solarzellentyp>_<Modalität>_<Bildidentifikator>.tif
```

Beispiel:

```text
23-P09-B1_EL_Cell001.tif
```

| Bestandteil | Beispiel | Bedeutung |
|---|---|---|
| `<Solarzellentyp>` | `23-P09-B1` | Kennzeichnung des Solarzellentyps |
| `<Modalität>` | `EL` | Bildmodalität, z. B. VI, EL oder UVF/UV |
| `<Bildidentifikator>` | `Cell001` | Eindeutige Kennzeichnung einer Solarzelle |

Die Bilddateien dürfen in Unterordnern von `data/images/` organisiert sein. Der Identifikator einer Bilddatei ist dann ihr Pfad relativ zu `data/images/` mit `/` als Trenner, z. B. `nested/23-P09-B1_EL_Cell004.tif`; die Regeln dieses Abschnitts gelten für den Dateinamen ohne Ordnername.

### 4.2 Bildgruppe

Bilder mit identischem Solarzellentyp und identischem Bildidentifikator gehören zusammen. Pro Bildgruppe wird jeweils eine Aufnahme je Bildmodalität erwartet.

Beispiel einer Bildgruppe:

```text
23-P09-B1_VI_Cell001.tif
23-P09-B1_EL_Cell001.tif
23-P09-B1_UVF_Cell001.tif
```

Die Labels gelten immer für **eine konkrete Bilddatei bzw. Bildmodalität**, nicht automatisch für die gesamte Bildgruppe.

## 5. Benutzerrollen und Anmeldung

Es ist keine Passwort-Authentifizierung erforderlich.

### 5.1 Login-Fenster

Beim Aufruf der Anwendung wird zuerst ein Login-Fenster angezeigt.

**Elemente:**

- Textfeld: `Name`
- Button: `Login`

**Verhalten:**

1. Der Benutzer gibt seinen Namen ein.
2. Das Feld `Name` ist ein Pflichtfeld.
3. Nach Klick auf `Login` wird der Name in der Session gespeichert.
4. Der Benutzer wird zum Main Window weitergeleitet.
5. Der gespeicherte Name wird beim Speichern von Labeländerungen als Labeler in CSV und Änderungslog erfasst.

## 6. Benutzeroberfläche

### 6.1 Main Window

Das Main Window enthält die folgenden Bereiche:

1. Dropdown zur Auswahl der Bildmodalität.
2. Tabs zum Filtern nach Labelstatus bzw. Labelkategorie.
3. Bildgalerie mit Bildkarten.
4. Pop-up-Fenster zur Anzeige aller Modalitäten einer Bildgruppe.
5. `Save`-Button oben rechts zum Speichern aller ungespeicherten Änderungen.

### 6.2 Dropdown: Bildmodalität

Das Dropdown zeigt die in `config.json` definierten Modalitäten an, standardmäßig `VI`, `EL` und `UVF`.

**Verhalten:**

- Die ausgewählte Modalität bestimmt, welche Bilddateien in der Galerie sichtbar sind.
- Ein Wechsel der Modalität übernimmt den aktuell ausgewählten Tab-Filter.

### 6.3 Tabs: Label-Filter

Es gibt folgende Tabs (in dieser Reihenfolge):

- `Unclassified`
- `Good`
- Je einen Tab für jeden konfigurierten Defekttyp
- `All` (letzter Tab)

**Filterlogik:**

| Tab | Angezeigte Bilder |
|---|---|
| `Unclassified` | Bilder der ausgewählten Modalität ohne gesetztes Label. |
| `Good` | Bilder der ausgewählten Modalität, bei denen `good = 1` gesetzt ist. |
| Defekt-Tab, z. B. `Crack` | Bilder der ausgewählten Modalität, bei denen das entsprechende Defektlabel gesetzt ist. |
| `All` | Alle Bilder der ausgewählten Modalität, unabhängig vom Labelstatus. |

Wenn ein Bild mehrere Defektlabels besitzt, erscheint es in jedem passenden Defekt-Tab.

Die Filterlogik bezieht sich ausschließlich auf den gespeicherten Labelstatus; ungespeicherte Änderungen beeinflussen die Tab-Zuordnung nicht.

### 6.4 Bildgalerie und Bildkarte

Die Galerie zeigt alle Bilder, die dem gewählten Modalitäts- und Tab-Filter entsprechen.

Jede Bildkarte enthält:

- Den Bildnamen ohne oder mit Dateiendung.
- Eine Vorschau/Thumbnail des Bildes.
- Checkboxen für `Good` und alle Defektkategorien.

**Interaktion:**

- Klick auf die Bildvorschau oder den Bildnamen öffnet das Image-View-Pop-up.
- Klick auf eine Checkbox ändert das Label ausschließlich in der aktuellen Anzeige; es wird noch nicht gespeichert.
- Die Bildkarte bleibt im aktuellen Tab sichtbar, auch wenn sie nach der Änderung nicht mehr zum Tab-Filter passt.
- Erst nach dem Speichern (siehe 6.6) wird die Ansicht neu geladen, sodass Tab-Filter und Checkboxzustände dem gespeicherten Stand entsprechen.

### 6.5 Image-View-Pop-up

Beim Öffnen eines Bildes wird ein Pop-up-Fenster angezeigt.

**Inhalt:**

- Schließen-Schaltfläche `X`.
- Die Bilder aller Modalitäten derselben Bildgruppe, nebeneinander oder responsiv untereinander.
- Pro Bild die Kennzeichnung der Modalität, z. B. `VI`, `EL`, `UVF`.

**Beispiel:** Beim Klick auf `23-P09-B1_EL_Cell001.tif` zeigt das Pop-up die zugehörigen Bilder `VI`, `EL` und `UVF` derselben Solarzelle.

Falls eine Modalität einer Bildgruppe nicht vorhanden ist, muss dies sichtbar als fehlendes Bild angezeigt werden; die Anwendung darf dabei nicht fehlschlagen.

### 6.6 Speichern von Labeländerungen

- Checkbox-Klicks ändern zunächst nur die Anzeige; gespeichert wird ausschließlich über den `Save`-Button.
- Der `Save`-Button befindet sich oben rechts in der Kopfzeile neben dem Anmeldebereich und zeigt die Anzahl der geänderten Bilder an; ohne ungespeicherte Änderungen ist er deaktiviert.
- Beim Klick auf `Save` werden alle ungespeicherten Änderungen in `labels.csv` und im Änderungslog persistiert. Danach wird die Ansicht neu geladen; Bilder, die nicht mehr zum aktuellen Tab-Filter passen, verschwinden aus der Galerie. Tab-Filter, Modalität und Zelltyp-Filter bleiben dabei erhalten.
- Solange ungespeicherte Änderungen vorliegen, fragt der Browser beim Verlassen der Seite (Tab-Wechsel, Modalitätswechsel, Logout, Schließen oder Aktualisieren der Seite) über einen Bestätigungsdialog nach. Nicht gespeicherte Änderungen gehen beim Verlassen verloren.
- Die Tab-Zählungen aktualisieren sich erst nach dem Speichern.

## 7. Labelregeln

### 7.1 Mehrfachauswahl von Defekten

Mehrere Defekttypen können gleichzeitig für dieselbe Bilddatei gesetzt werden.

Beispiel: `Crack = 1` und `Corrosion = 1` ist zulässig.

### 7.2 Exklusivität von Good

`Good` ist exklusiv gegenüber sämtlichen Defektlabels.

| Aktion | Erwartetes Verhalten |
|---|---|
| Benutzer setzt `Good` | Alle Defektlabels desselben Bildes werden auf `0` gesetzt. |
| Benutzer setzt ein Defektlabel, während `Good` aktiv ist | `Good` wird auf `0` gesetzt; das gewählte Defektlabel wird auf `1` gesetzt. |
| Benutzer entfernt `Good` | Es werden keine Defekte automatisch gesetzt. Das Bild wird unklassifiziert, sofern kein Defektlabel gesetzt ist. |
| Benutzer entfernt das letzte aktive Defektlabel | Das Bild wird unklassifiziert, sofern `Good` nicht gesetzt ist. |

### 7.3 Definition von Unclassified

Ein Bild gilt als `Unclassified`, wenn `good = 0` und alle Defektlabel den Wert `0` haben.

## 8. Persistenz der Labeldaten

### 8.1 CSV-Datei

Dateiname: `labels.csv`

Für jede Bilddatei existiert maximal eine aktuelle Zeile. Wird ein bereits gelabeltes Bild erneut geändert, wird seine bestehende Zeile aktualisiert und nicht als Duplikat angelegt. Die Zeile wird ausschließlich beim Klick auf den `Save`-Button aktualisiert.

### 8.2 CSV-Spalten

Die CSV-Datei enthält mindestens folgende Spalten in genau dieser Reihenfolge:

```csv
Datum,Zeit,Name of labeler,datename,uv,vi,el,good,crack,cross,dark,corrosion,discoloration,delamination
```

Bedeutung:

| Spalte | Beschreibung |
|---|---|
| `Datum` | Datum der letzten Änderung. |
| `Zeit` | Uhrzeit der letzten Änderung. |
| `Name of labeler` | Name des aktuell angemeldeten Benutzers. |
| `datename` | Pfad der gelabelten Bilddatei relativ zu `data/images/` (mit `/` als Trenner; für Dateien im Hauptordner nur der Dateiname). |
| `uv` | `1`, falls die Bilddatei zur UV/UVF-Modalität gehört, sonst `0`. |
| `vi` | `1`, falls die Bilddatei zur VI-Modalität gehört, sonst `0`. |
| `el` | `1`, falls die Bilddatei zur EL-Modalität gehört, sonst `0`. |
| `good` | `1` bei Good, sonst `0`. |
| Defektspalten | `1`, wenn der jeweilige Defekt gesetzt ist, sonst `0`. |

Die Modalitätsspalten `uv`, `vi` und `el` sind binär. Für einen gültigen Datensatz darf genau eine dieser Modalitätsspalten den Wert `1` haben.

> Wenn der konfigurierte Modalitätscode `UVF` lautet, wird dieser für die Speicherung in die geforderte CSV-Spalte `uv` abgebildet.

### 8.3 Beispiel

```csv
Datum,Zeit,Name of labeler,datename,uv,vi,el,good,crack,cross,dark,corrosion,discoloration,delamination
2026-08-14,10:32:05,Max Muster,23-P09-B1_EL_Cell001.tif,0,0,1,0,1,0,0,0,0,0
```

## 9. Änderungsprotokoll

Beim Speichern muss jede Änderung an einer Bilddatei im Änderungslog festgehalten werden. Pro geändertem Bild wird genau ein Eintrag angehängt, der den Zustand vor und nach der gesamten Speicherung enthält.

Dateiname: `change_log.csv` oder `change_log.txt`.

Jeder Logeintrag enthält mindestens:

- Datum und Zeit
- Name des Labelers
- Bilddateiname
- Zustand vor der Änderung
- Zustand nach der Änderung

Beispiel:

```text
2026-08-14 10:32:05 | Max Muster | 23-P09-B1_EL_Cell001.tif | before: good=0, crack=0 | after: good=0, crack=1
```

Das Änderungslog wird ausschließlich ergänzt; bestehende Einträge dürfen nicht überschrieben werden.

## 10. Technische Anforderungen

### 10.1 Backend

- Python
- Flask
- Session-Verwaltung für den Namen des angemeldeten Benutzers
- Lesen der JSON-Konfiguration beim Start der Anwendung
- Parsen der Bilddateinamen und Gruppieren der Modalitäten
- Lesen und Schreiben der CSV-Labeldatei
- Schreiben des Änderungslogs
- Validierung der Labelregeln serverseitig

### 10.2 Frontend

- HTML mit Jinja2-Templates
- CSS für responsives Layout
- JavaScript für unmittelbare UI-Aktualisierungen und das Speichern über den `Save`-Button (AJAX) sowie den Bestätigungsdialog beim Verlassen
- Modal/Pop-up für die Bildgruppenansicht

### 10.3 Bildanzeige

Die Quelldateien liegen als `.tif` vor. Da TIFF-Dateien nicht in allen Browsern direkt dargestellt werden können, muss die Anwendung für die Webanzeige Vorschaubilder in einem browserkompatiblen Format erzeugen oder bereitstellen, z. B. PNG oder JPEG.

Die Originaldateien dürfen durch die Vorschau-Erzeugung nicht verändert werden.

Ergänzend wird die Originaldatei in der Bildgruppenansicht standardmäßig direkt im Browser angezeigt (Dekodierung per JavaScript, Anzeige mit Min/Max-Window-Reglern über den Datenbereich; Umschalten auf die JPEG-Vorschau ist möglich) und kann als Datei heruntergeladen werden.

Die Window-Regler legen Schwarz- und Weißpunkt der Anzeige fest: Werte unterhalb von `Min` werden schwarz, oberhalb von `Max` weiß dargestellt, Werte dazwischen linear gespreizt. Startzustand ist der volle Datenbereich des Bildes. Die Regler zeigen ihren aktuellen Wert und die Bittiefe des angezeigten Bildes an. Die Regler verändern ausschließlich die Anzeige, nicht die Bilddaten; gefundene Werte können über das Preview-Window-Panel des Hauptfensters in die `config.json` übernommen werden.

### 10.4 Konsistenz und Fehlerbehandlung

- Ungültige oder nicht parsebare Dateinamen werden protokolliert und nicht in der Galerie angezeigt, sofern sie keiner Bildgruppe zugeordnet werden können.
- Fehlende Modalitäten innerhalb einer Bildgruppe dürfen das Pop-up nicht blockieren.
- Ungültige Labelkombinationen (`Good` plus Defekt) müssen serverseitig verhindert werden.
- CSV- und Log-Schreibzugriffe müssen so umgesetzt werden, dass Daten nicht durch parallele Schreibvorgänge beschädigt werden.

## 11. Projektstruktur (Vorschlag)

```text
labeling_tool/
├── app.py
├── config.json
├── requirements.txt
├── data/
│   ├── images/
│   ├── labels.csv
│   └── change_log.csv
├── templates/
│   ├── login.html
│   └── main.html
└── static/
    ├── css/
    ├── js/
    └── previews/
```

## 12. Akzeptanzkriterien

Die Implementierung gilt als funktionsfähig, wenn alle folgenden Kriterien erfüllt sind:

1. Beim Öffnen der Anwendung erscheint ein Login-Fenster mit Namenseingabe und Login-Button.
2. Ohne Namenseingabe ist kein Wechsel zum Main Window möglich.
3. Nach erfolgreichem Login erscheint das Main Window mit Modalitäts-Dropdown, Label-Tabs und Bildgalerie.
4. Die verfügbaren Modalitäten und Defektkategorien werden aus `config.json` gelesen.
5. Der Tab `Unclassified` zeigt ausschließlich ungelabelte Bilder der gewählten Modalität.
6. Die übrigen Tabs filtern Bilder nach dem jeweiligen gesetzten Label. Der letzte Tab `All` zeigt alle Bilder der gewählten Modalität unabhängig vom Labelstatus.
7. Die Checkboxen erlauben mehrere Defektlabels gleichzeitig.
8. `Good` und Defektlabels können niemals gleichzeitig für dieselbe Bilddatei aktiv sein.
9. Ein Klick auf ein Bild öffnet ein Pop-up mit allen verfügbaren Modalitäten derselben Bildgruppe.
10. Beim Klick auf `Save` wird für jede geänderte Bilddatei der aktuelle Datensatz in `labels.csv` erzeugt oder aktualisiert.
11. Die CSV-Datei enthält die spezifizierten Spalten und binäre Labelwerte.
12. Beim Klick auf `Save` wird pro geänderter Bilddatei genau ein nachvollziehbarer Eintrag im Änderungslog erzeugt.
13. Der `Save`-Button zeigt die Anzahl der geänderten Bilder und ist ohne ungespeicherte Änderungen deaktiviert.
14. Bilder, deren Label im aktuellen Tab geändert wurde, bleiben bis zum Speichern sichtbar.
15. Bei ungespeicherten Änderungen fragt der Browser beim Verlassen der Seite über einen Bestätigungsdialog nach.
