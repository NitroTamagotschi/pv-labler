"""Merge all CSV files of a folder into a single CSV.

All *.csv files of the input folder (in sorted order) are read into one
DataFrame each and concatenated row-wise. Duplicate rows are kept. The
result is written to the output CSV with UTF-8 encoding.

Next to the output a protocol file `<output stem>_report.txt` is
written. It contains the date/time, the per-file row and column counts,
differing column sets, duplicate rows with their source files and row
numbers, and the totals.

Usage:

    python scripts/merge_csv.py ./csv_ordner -o zusammengefuehrt.csv
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

# Temporary column that tracks the origin file of each row. Only used
# for the report, never written to the output CSV.
SOURCE_COLUMN = "_quelle"
MAX_REPORTED_DUPLICATES = 20


def merge_csv(input_folder: Path, output: Path) -> None:
    """Concatenate all *.csv files of input_folder and write them to output."""
    all_files = sorted(input_folder.glob("*.csv"))
    if not all_files:
        print(f"Keine CSV-Dateien gefunden in: {input_folder}", file=sys.stderr)
        sys.exit(1)

    frames = []
    for file in all_files:
        df = pd.read_csv(file)
        if SOURCE_COLUMN in df.columns:
            print(f"Fehler: {file.name} enthaelt bereits eine Spalte "
                  f"'{SOURCE_COLUMN}'; bitte Spalte umbenennen.",
                  file=sys.stderr)
            sys.exit(1)
        df[SOURCE_COLUMN] = file.name
        frames.append(df)
    merged_df = pd.concat(frames, ignore_index=True)
    data_columns = [c for c in merged_df.columns if c != SOURCE_COLUMN]

    output.parent.mkdir(parents=True, exist_ok=True)
    merged_df[data_columns].to_csv(output, index=False, encoding="utf-8")

    report_path = output.with_name(f"{output.stem}_report.txt")
    report = build_report(input_folder, all_files, frames, merged_df,
                          data_columns, output)
    report_path.write_text(report, encoding="utf-8")

    dup_rows = int(merged_df.duplicated(subset=data_columns, keep=False).sum())
    print(f"{len(all_files)} Dateien zusammengefuehrt -> {output}")
    print(f"{len(merged_df)} Zeilen, {len(data_columns)} Spalten, "
          f"davon {dup_rows} doppelt")
    print(f"Protokoll: {report_path}")


def build_report(input_folder: Path, files: list[Path],
                 frames: list[pd.DataFrame], merged_df: pd.DataFrame,
                 data_columns: list[str], output: Path) -> str:
    """Return the merge protocol as text."""
    lines = [
        "Merge-Protokoll",
        f"Erstellt: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Quellordner: {input_folder}",
        f"Ausgabedatei: {output}",
        "",
        f"Dateien ({len(files)}):",
    ]
    for file, df in zip(files, frames):
        lines.append(f"  - {file.name}: {len(df)} Zeile(n), "
                     f"{len(df.columns) - 1} Spalten")

    # Column sets that differ from the first file.
    first_columns = set(frames[0].columns) - {SOURCE_COLUMN}
    differing = [
        (file.name, set(df.columns) - {SOURCE_COLUMN})
        for file, df in zip(files, frames)
        if set(df.columns) - {SOURCE_COLUMN} != first_columns
    ]
    lines.append("")
    if differing:
        lines.append("Abweichende Spalten:")
        for name, columns in differing:
            notes = []
            missing = sorted(first_columns - columns)
            extra = sorted(columns - first_columns)
            if missing:
                notes.append("fehlt: " + ", ".join(missing))
            if extra:
                notes.append("zusätzlich: " + ", ".join(extra))
            lines.append(f"  - {name}: {'; '.join(notes)}")
    else:
        lines.append("Spalten: in allen Dateien identisch")

    # Duplicate rows across all data columns (origin file ignored).
    dup_mask = merged_df.duplicated(subset=data_columns, keep=False)
    lines.append("")
    lines.append("Duplikate:")
    if not dup_mask.any():
        lines.append("  Keine doppelten Zeilen gefunden.")
    else:
        groups = merged_df[dup_mask].groupby(data_columns, dropna=False,
                                             sort=False)
        lines.append(f"  {int(dup_mask.sum())} Zeilen kommen mehrfach vor "
                     f"({len(groups)} Gruppen). Doppelt = identische Werte "
                     f"in allen Datenspalten (ohne Quelldatei).")
        lines.append("")
        for key, group in list(groups)[:MAX_REPORTED_DUPLICATES]:
            sources = []
            for source, rows in group.groupby(SOURCE_COLUMN, sort=False):
                numbers = ", ".join(str(i + 1) for i in rows.index)
                sources.append(f"{source}: Zeile(n) {numbers}")
            lines.append(f"  * {len(group)}x: {format_row(key, data_columns)}")
            lines.append(f"      ({'; '.join(sources)})")
        rest = len(groups) - MAX_REPORTED_DUPLICATES
        if rest > 0:
            lines.append(f"  ... und {rest} weitere Gruppen.")

    lines.append("")
    lines.append("Ergebnis:")
    lines.append(f"  {len(merged_df)} Zeilen, {len(data_columns)} Spalten")
    lines.append(f"  {int(dup_mask.sum())} doppelte Zeilen (werden "
                 f"beibehalten)")
    return "\n".join(lines) + "\n"


def format_row(key: object, columns: list[str]) -> str:
    """Format a group key as 'col=value, ...' for the report."""
    if not isinstance(key, tuple):
        key = (key,)
    return ", ".join(f"{col}={val}" for col, val in zip(columns, key))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_folder",
        nargs="?",
        default="./csv_ordner",
        help="Ordner mit den CSV-Dateien (Standard: ./csv_ordner)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="zusammengefuehrt.csv",
        help="Ausgabedatei (Standard: zusammengefuehrt.csv)",
    )
    args = parser.parse_args()

    merge_csv(Path(args.input_folder), Path(args.output))


if __name__ == "__main__":
    main()
