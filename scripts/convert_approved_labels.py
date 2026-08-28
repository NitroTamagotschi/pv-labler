"""Convert an approved OLLM label export into the labels.csv schema (§8.2).

The input is a CSV with the columns `filename,labels`, where labels are
space-separated defect keys, e.g.:

    23-P09-C4_VI_Cell001_normalized.tif,dark discoloration

Multiple rows for the same image are merged into one (union of labels).
The modality segment in the file name (VI/EL/UV) fills the uv/vi/el
columns; each label token must match a label key from config.json.

For every image the script searches the images directory (config.json
`images_dir`, default data/images/) and stores the actual relative path
of the image as datename, so the labels always match what the app
displays. An explicit directory part in the input file name is kept only
when it matches an existing image.

Entries that cannot be processed correctly -- the image is missing or
ambiguous, a label token is not defined in config.json, the modality is
missing from the file name, or the labels are empty -- are written to a
failure report `<output stem>_failed.csv` with the columns
filename, labels, reason. The script exits with status 1 when the
report is non-empty.

The output uses the labels.csv schema of labels.py: Datum, Zeit, Name of
labeler, datename, uv, vi, el, then the label columns. By default the
output is written next to the input file as `<name>_converted.csv`;
data/labels.csv is only touched when --output points at it, so the
result can be reviewed and merged manually. Rows are upserted into the
target CSV by datename: rows for other images are left untouched, rows
present in the input are (re)written with the current date/time and
labeler. The write is atomic (temp file + replace).
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
CONFIG_PATH = os.path.join(REPO_ROOT, "config.json")
DEFAULT_IMAGES_DIR = os.path.join(REPO_ROOT, "data", "images")

# Same extensions the app scans for (images.py IMAGE_EXTENSIONS).
IMAGE_EXTENSIONS = (".tif", ".tiff", ".jpg", ".jpeg", ".png")

FIXED_COLUMNS = ["Datum", "Zeit", "Name of labeler", "datename"]
# Required order of the modality columns for the standard configuration (§8.2).
MODALITY_COLUMNS = ["uv", "vi", "el"]

FAILURE_COLUMNS = ["filename", "labels", "reason"]

# Matches the file name convention the app itself uses, e.g. `_VI_`, `_UV2_`.
FILENAME_CODE_SEGMENT = re.compile(r"^([a-z]+)(\d*)$", re.IGNORECASE)


def load_config(path: str = CONFIG_PATH) -> dict:
    """Read config.json (label keys, modality file name codes, images_dir)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_images_dir(config: dict, override: str | None) -> str:
    """Return the images dir: --images-dir wins, then config, then data/images."""
    if override:
        return override
    configured = config.get("images_dir")
    if configured:
        return configured
    return DEFAULT_IMAGES_DIR


def modality_info(filename: str, modalities: list[dict]) -> tuple[str, str] | None:
    """Return (csv column, file name code) for a file name, or None.

    Mirrors images.parse_filename: the rightmost underscore segment
    matching a filename code (with optional digit suffix) is the modality.
    The canonical code is mapped through the same normalization as
    labels.modality_to_column (UVF -> uv).
    """
    filename_codes = {
        (m.get("filename_code") or m["code"]).lower(): (
            m["code"].lower(),
            m.get("filename_code") or m["code"],
        )
        for m in modalities
    }
    stem = os.path.splitext(os.path.basename(filename))[0]
    for part in reversed(stem.split("_")):
        match = FILENAME_CODE_SEGMENT.match(part)
        if match and match.group(1).lower() in filename_codes:
            code, filename_code = filename_codes[match.group(1).lower()]
            column = "uv" if code == "uvf" else code
            return column, filename_code
    return None


def read_approved_rows(
    path: str, modalities: list[dict], failures: list[tuple[str, str, str]]
) -> dict[str, tuple[str, str, set[str], list[str]]]:
    """Return {filename: (modality column, file name code, tokens, raw labels)}.

    Repeated rows for the same file name are merged into one set of label
    tokens. Rows with a missing file name, no recognizable modality or no
    labels are appended to failures instead of being converted.
    """
    merged: dict[str, tuple[str, str, set[str], list[str]]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "filename" not in (reader.fieldnames or []):
            raise SystemExit(f"{path}: expected a 'filename' column (approved OLLM format)")
        for raw in reader:
            filename = (raw.get("filename") or "").strip()
            labels_raw = (raw.get("labels") or "").strip()
            tokens = {token.strip(" \t,;|") for token in labels_raw.split()} - {""}
            if not filename:
                failures.append(("", labels_raw, "row without filename"))
                continue
            if not tokens:
                failures.append((filename, labels_raw, "empty labels"))
                continue
            info = merged.get(filename)
            if info is None:
                info = modality_info(filename, modalities)
                if info is None:
                    failures.append(
                        (filename, labels_raw, "no modality segment in file name")
                    )
                    continue
                merged[filename] = info + (set(), [])
            merged[filename][2].update(tokens)
            if labels_raw not in merged[filename][3]:
                merged[filename][3].append(labels_raw)
    return merged


def build_images_index(images_dir: str) -> dict[str, list[str]]:
    """Return {basename: [relative paths]} for every image under images_dir."""
    index: dict[str, list[str]] = {}
    if not os.path.isdir(images_dir):
        return index
    for root, _dirnames, names in os.walk(images_dir):
        for name in names:
            if name.lower().endswith(IMAGE_EXTENSIONS):
                relative = os.path.relpath(os.path.join(root, name), images_dir)
                index.setdefault(name, []).append(relative.replace(os.sep, "/"))
    return index


def resolve_image_path(
    filename: str, index: dict[str, list[str]]
) -> tuple[str | None, str | None]:
    """Return (relative path, error) for a file name from the approved CSV.

    The path is the actual location under images_dir. An explicit
    directory part in the input is kept only when it matches an existing
    image; otherwise the bare file name is looked up and must be unique.
    """
    normalized = filename.replace("\\", "/")
    basename = os.path.basename(normalized)
    matches = index.get(basename, [])
    if "/" in normalized and normalized in matches:
        return normalized, None
    if len(matches) == 1:
        return matches[0], None
    if matches:
        return None, (
            f"ambiguous path: {len(matches)} images named {basename!r}: "
            + ", ".join(sorted(matches))
        )
    return None, f"image not found under images_dir: {basename!r}"


def build_label_state(
    tokens: set[str], good_key: str, defect_keys: list[str]
) -> dict[str, int]:
    """Return {label_key: 0|1} for a set of label tokens.

    A 'good' token combined with defect tokens is a conflict: the defects
    win (same precedence as the app's exclusivity rules, §7.2).
    """
    label_keys = [good_key] + defect_keys
    if good_key in tokens and tokens & set(defect_keys):
        tokens = tokens - {good_key}
    return {key: 1 if key in tokens else 0 for key in label_keys}


def build_row(
    datename: str,
    modality_column: str,
    labels: dict[str, int],
    labeler: str,
    now: dt.datetime,
) -> dict[str, object]:
    """One labels.csv row with modality one-hot and label columns filled."""
    row = {
        "Datum": now.strftime("%Y-%m-%d"),
        "Zeit": now.strftime("%H:%M:%S"),
        "Name of labeler": labeler,
        "datename": datename,
    }
    for column in MODALITY_COLUMNS:
        row[column] = 1 if column == modality_column else 0
    row.update(labels)
    return row


def read_existing(path: str) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Return (datename order, {datename: raw row}) of an existing CSV."""
    order: list[str] = []
    rows: dict[str, dict[str, str]] = {}
    if not os.path.isfile(path):
        return order, rows
    with open(path, encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            datename = (raw.get("datename") or "").strip()
            if datename and datename not in rows:
                order.append(datename)
            if datename:
                rows[datename] = raw
    return order, rows


def write_csv(path: str, columns: list[str], rows: list[dict[str, object]]) -> None:
    """Atomically write rows to path (temp file + os.replace, like labels.py)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


def write_failure_report(path: str, failures: list[tuple[str, str, str]]) -> None:
    """Write the entries that could not be processed to path."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FAILURE_COLUMNS)
        writer.writerows(failures)


def default_input_path() -> str:
    """Return the approved_OLLM_*.csv in the repo root if there is exactly one."""
    candidates = [
        path
        for path in glob.glob(os.path.join(REPO_ROOT, "approved_OLLM_*.csv"))
        if "_converted" not in os.path.basename(path)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SystemExit("no approved_OLLM_*.csv found in the repo root, pass the input path")
    raise SystemExit(
        "multiple approved_OLLM_*.csv files found, pass one: " + ", ".join(candidates)
    )


def default_output_path(input_path: str) -> str:
    """Return the default target '<input stem>_converted.csv' next to the input."""
    return os.path.splitext(input_path)[0] + "_converted.csv"


def default_failure_path(output_path: str) -> str:
    """Return the failure report '<output stem>_failed.csv' next to the output."""
    return os.path.splitext(output_path)[0] + "_failed.csv"


def parse_args() -> argparse.Namespace:
    """Parse the command line (input file, labeler, output and images-dir options)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="approved OLLM CSV (default: the approved_OLLM_*.csv in the repo root)",
    )
    parser.add_argument(
        "--labeler",
        required=True,
        help="name written into the 'Name of labeler' column of every converted row",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="target CSV (default: '<input stem>_converted.csv' next to the input)",
    )
    parser.add_argument(
        "--images-dir",
        default=None,
        help="directory the file paths are resolved against "
        "(default: config.json 'images_dir' or data/images/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the resulting rows without writing"
    )
    return parser.parse_args()


def main() -> None:
    """Convert the approved rows, resolve their image paths and report failures."""
    args = parse_args()
    input_path = args.input or default_input_path()
    output_path = args.output or default_output_path(input_path)
    failure_path = default_failure_path(output_path)
    config = load_config()
    good_key = config["labels"]["good"]["key"]
    defect_keys = [d["key"] for d in config["labels"]["defects"]]
    label_keys = [good_key] + defect_keys
    columns = FIXED_COLUMNS + MODALITY_COLUMNS + label_keys

    images_dir = resolve_images_dir(config, args.images_dir)
    if not os.path.isdir(images_dir):
        print(f"warning: images_dir {images_dir!r} does not exist")

    failures: list[tuple[str, str, str]] = []
    approved = read_approved_rows(input_path, config["modalities"], failures)
    if not approved and not failures:
        print("nothing to convert")
        raise SystemExit(1)

    index = build_images_index(images_dir)
    now = dt.datetime.now()
    label_key_set = set(label_keys)
    defect_key_set = set(defect_keys)
    converted: dict[str, dict[str, object]] = {}
    for filename, (modality_column, _filename_code, tokens, raws) in approved.items():
        labels_raw = "; ".join(raws)
        unknown = tokens - label_key_set
        if unknown:
            failures.append(
                (filename, labels_raw, f"unknown label token(s): {', '.join(sorted(unknown))}")
            )
            continue
        image_path, error = resolve_image_path(filename, index)
        if error:
            failures.append((filename, labels_raw, error))
            continue
        if good_key in tokens and tokens & defect_key_set:
            print(f"warning: {image_path}: 'good' combined with a defect label, defects win")
        state = build_label_state(tokens, good_key, defect_keys)
        converted[image_path] = build_row(image_path, modality_column, state, args.labeler, now)

    order, existing = read_existing(output_path)
    updated = [d for d in order if d in converted]
    added = [d for d in converted if d not in existing]
    rows: list[dict[str, object]] = []
    for datename in order:
        rows.append(converted.get(datename, {k: v for k, v in existing[datename].items()}))
    rows.extend(converted[d] for d in added)

    print(
        f"{len(approved)} image(s) read -> {len(converted)} converted "
        f"({len(updated)} updated, {len(added)} added, "
        f"{len(existing) - len(updated)} untouched)"
    )
    for filename, labels_raw, reason in failures:
        name = filename or "<no filename>"
        labels = labels_raw or "<no labels>"
        print(f"  failed: {name} ({labels}) - {reason}")
    if args.dry_run:
        print(f"dry run, {output_path} not written")
        if failures:
            print(f"failure report would be written to {failure_path}")
        raise SystemExit(1 if failures else 0)

    write_csv(output_path, columns, rows)
    print(f"wrote {output_path}")
    if failures:
        write_failure_report(failure_path, failures)
        print(f"wrote {failure_path} ({len(failures)} entries)")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
