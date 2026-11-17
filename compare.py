"""Comparison of the stored labels (labels.csv) with external label sources.

A comparison source is a CSV file in the data directory (next to labels.csv)
with one row per image, typically the results of an AI labeling run. A file
is usable when it has an image column (image_path or file_name) and at least
one column named like a configured label key. The labels.csv schema itself
qualifies, so a second labeler or a ground-truth file can be compared too.

Per label, a source cell holds 1 (set), 0 (not set) or stays empty (not
assessed, e.g. a defect the source never evaluates in that modality). Empty
cells never count as a difference. Optional columns refine a result:
valid_result (0 marks the row as unusable), uncertain (1 flags the result)
and a free-text note such as visual_status.

Image paths are matched against the scanned image index, so absolute paths
from another machine resolve as long as they end with the image's relative
path (".../normalized_images/23-P09-A/VI/x.tif" -> "23-P09-A/VI/x.tif"); a
unique basename is the fallback.
"""

import csv
import os
import threading
from collections.abc import Iterable

# tab keys of the comparison mode; label keys cannot contain "-" (see
# app.LABEL_KEY_PATTERN), so these can never collide with configured labels
TAB_DIFF = "cmp-diff"
TAB_AGREE = "cmp-agree"
TAB_UNCERTAIN = "cmp-uncertain"
TAB_NONE = "cmp-none"
TAB_ALL = "all"  # shared with the normal mode

# direction filter of a label tab: which side set the label
ONLY_LABELER = "labeler"  # labels.csv set it, the source did not
ONLY_SOURCE = "source"  # the source set it, labels.csv did not

# result status of one source for one image
STATUS_OK = "ok"
STATUS_MISSING = "missing"  # the source has no row for the image
STATUS_INVALID = "invalid"  # valid_result=0 or no label assessed at all

# recognized columns (matched case-insensitively), in priority order
PATH_COLUMNS = ("image_path", "file_name", "filename", "file", "path")
NOTE_COLUMNS = ("visual_status", "reasoning", "explanation", "comment", "note")
NAME_COLUMNS = ("model", "labeler")
VALID_COLUMN = "valid_result"
UNCERTAIN_COLUMN = "uncertain"

_TRUE = frozenset({"1", "1.0", "true", "yes"})
_FALSE = frozenset({"0", "0.0", "false", "no"})

# unmatched source rows kept for the diagnostics tooltip
MAX_UNMATCHED_SAMPLES = 10


def parse_flag(value: str | None) -> int | None:
    """Parse one cell into 1, 0 or None (empty, not assessed or unknown)."""
    text = (value or "").strip().lower()
    if text in _TRUE:
        return 1
    if text in _FALSE:
        return 0
    return None


def _delimiter(header_line: str) -> str:
    """Return ";" for semicolon-separated files (German Excel exports), else ","."""
    return ";" if header_line.count(";") > header_line.count(",") else ","


def read_header(path: str) -> tuple[list[str], str]:
    """Return the normalized (stripped, lowercase) column names and the delimiter.

    The file is read as UTF-8 with an optional byte-order mark, as written
    by Excel.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        first = f.readline()
    delimiter = _delimiter(first)
    row = next(csv.reader([first], delimiter=delimiter), [])
    return [column.strip().lower() for column in row], delimiter


def header_error(columns: list[str], label_keys: list[str]) -> str | None:
    """Return why a CSV header cannot serve as a comparison source, or None."""
    if not any(column in columns for column in PATH_COLUMNS):
        return "keine Bildspalte (image_path oder file_name)"
    if not any(key in columns for key in label_keys):
        return "keine Labelspalten aus config.json"
    return None


class SourceFile:
    """A CSV file offered as comparison source, with its header check result."""

    __slots__ = ("id", "path", "error")

    def __init__(self, source_id: str, path: str, error: str | None) -> None:
        """Store the file name (the source id), its path and the header error."""
        self.id = source_id
        self.path = path
        self.error = error


def discover_sources(
    directory: str, label_keys: list[str], exclude: Iterable[str] = ()
) -> list[SourceFile]:
    """List the CSV files directly inside directory, sorted by name.

    Paths in exclude (labels.csv itself) are never offered. Only the header
    of each file is read, so listing stays cheap; the result tells the UI
    why a file cannot be selected.
    """
    excluded = {os.path.normcase(os.path.abspath(path)) for path in exclude}
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    files = []
    for name in names:
        path = os.path.join(directory, name)
        if not name.lower().endswith(".csv") or not os.path.isfile(path):
            continue
        if os.path.normcase(os.path.abspath(path)) in excluded:
            continue
        try:
            columns, _ = read_header(path)
            error = header_error(columns, label_keys)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            error = f"nicht lesbar ({exc.__class__.__name__})"
        files.append(SourceFile(name, path, error))
    return files


def basename_index(filenames: Iterable[str]) -> dict[str, list[str]]:
    """Return {basename: [relative image paths]} for the basename fallback."""
    index: dict[str, list[str]] = {}
    for filename in filenames:
        index.setdefault(filename.rsplit("/", 1)[-1], []).append(filename)
    return index


def resolve_image(raw: str, images: dict, basenames: dict[str, list[str]]) -> str | None:
    """Map a path from a source CSV to the relative path of a scanned image.

    Tries the path itself, then ever shorter suffixes on "/" boundaries (the
    longest existing suffix wins, so absolute paths from another machine
    resolve), and finally a unique basename. Backslashes count as "/".
    """
    path = raw.strip().replace("\\", "/")
    if not path:
        return None
    if path in images:
        return path
    parts = [part for part in path.split("/") if part]
    for start in range(len(parts)):
        candidate = "/".join(parts[start:])
        if candidate in images:
            return candidate
    matches = basenames.get(parts[-1], []) if parts else []
    return matches[0] if len(matches) == 1 else None


class SourceResult:
    """One image's result in a comparison source."""

    __slots__ = ("values", "valid", "uncertain", "note")

    def __init__(
        self, values: dict[str, int | None], valid: bool, uncertain: bool, note: str | None
    ) -> None:
        """Store the label values {key: 1|0|None} and the result metadata."""
        self.values = values
        self.valid = valid
        self.uncertain = uncertain
        self.note = note


class Source:
    """A parsed comparison source: per-image results plus load diagnostics."""

    def __init__(self, source_id: str, path: str) -> None:
        """Start an empty source; load_source fills it."""
        self.id = source_id
        self.path = path
        self.name = os.path.splitext(source_id)[0]
        self.detail: str | None = None  # model / labeler name(s) from the file
        self.label_keys: list[str] = []  # configured labels present as columns
        self.has_uncertain = False
        self.results: dict[str, SourceResult] = {}
        self.rows = 0
        self.unmatched = 0
        self.unmatched_samples: list[str] = []
        self.duplicates = 0
        self.error: str | None = None


def _cell(row: list[str], index: int | None) -> str:
    """Return the stripped cell at index, or "" for missing columns and short rows."""
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def load_source(path: str, source_id: str, label_keys: list[str], images: dict) -> Source:
    """Parse one source CSV and map its rows onto the scanned images.

    Rows whose image cannot be resolved are counted as unmatched. When an
    image appears in several rows the last row wins (later runs override
    earlier ones). Read and format problems end up in Source.error instead
    of raising.
    """
    source = Source(source_id, path)
    try:
        columns, delimiter = read_header(path)
        source.error = header_error(columns, label_keys)
        if source.error:
            return source
        position: dict[str, int] = {}
        for i, column in enumerate(columns):
            position.setdefault(column, i)
        path_cols = [position[c] for c in PATH_COLUMNS if c in position]
        note_cols = [position[c] for c in NOTE_COLUMNS if c in position]
        name_col = next((position[c] for c in NAME_COLUMNS if c in position), None)
        label_cols = {key: position.get(key) for key in label_keys}
        valid_col = position.get(VALID_COLUMN)
        uncertain_col = position.get(UNCERTAIN_COLUMN)
        source.label_keys = [key for key in label_keys if key in position]
        source.has_uncertain = uncertain_col is not None
        basenames = basename_index(images)
        names = set()
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None)  # header, already parsed above
            for row in reader:
                if not any(cell.strip() for cell in row):
                    continue  # blank line
                source.rows += 1
                raw_paths = [_cell(row, i) for i in path_cols]
                filename = None
                for raw in raw_paths:
                    filename = resolve_image(raw, images, basenames) if raw else None
                    if filename:
                        break
                if filename is None:
                    source.unmatched += 1
                    if len(source.unmatched_samples) < MAX_UNMATCHED_SAMPLES:
                        sample = next((raw for raw in raw_paths if raw), "")
                        source.unmatched_samples.append(sample or f"Zeile {reader.line_num}")
                    continue
                values = {key: parse_flag(_cell(row, col)) for key, col in label_cols.items()}
                valid = parse_flag(_cell(row, valid_col)) != 0 and any(
                    value is not None for value in values.values()
                )
                uncertain = parse_flag(_cell(row, uncertain_col)) == 1
                note = next((text for i in note_cols if (text := _cell(row, i))), None)
                if filename in source.results:
                    source.duplicates += 1
                source.results[filename] = SourceResult(values, valid, uncertain, note)
                if name_col is not None and (name := _cell(row, name_col)):
                    names.add(name)
        if names:
            ordered = sorted(names)
            source.detail = ", ".join(ordered[:3]) + (" …" if len(ordered) > 3 else "")
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        source.error = f"nicht lesbar ({exc.__class__.__name__})"
        source.results = {}
    return source


class SourceCache:
    """Parses each source once per file change and image-index rebuild."""

    def __init__(self) -> None:
        """Create an empty cache and its lock."""
        self._lock = threading.Lock()
        self._entries: dict[str, tuple] = {}

    def get(self, path: str, source_id: str, label_keys: list[str], images: dict) -> Source:
        """Return the parsed source, reloading it when the file or the images change.

        The images dict comes from images.ImageIndex.get(), which returns the
        same object until the directory changes, so an identity check detects
        a rescan (the cache entry keeps the dict alive, so the check is safe).
        """
        try:
            stat = os.stat(path)
            signature = (stat.st_mtime_ns, stat.st_size, tuple(label_keys))
        except OSError:
            signature = None
        with self._lock:
            entry = self._entries.get(source_id)
            if entry is not None and entry[0] == signature and entry[1] is images:
                return entry[2]
            source = load_source(path, source_id, label_keys, images)
            self._entries[source_id] = (signature, images, source)
            return source


# -- comparing one image ---------------------------------------------------


class SourceComparison:
    """One source's result for one image, compared with the stored labels."""

    __slots__ = ("status", "values", "diffs", "uncertain", "note")

    def __init__(
        self,
        status: str,
        values: dict[str, int | None],
        diffs: frozenset[str],
        uncertain: bool,
        note: str | None,
    ) -> None:
        """Store the result status, the values and the differing label keys."""
        self.status = status
        self.values = values
        self.diffs = diffs
        self.uncertain = uncertain
        self.note = note


class ImageComparison:
    """The stored labels of one image next to the result of every source."""

    __slots__ = ("labeled", "human", "sources")

    def __init__(
        self, labeled: bool, human: dict[str, int], sources: list[SourceComparison]
    ) -> None:
        """Store whether labels.csv labels the image, its state and the sources."""
        self.labeled = labeled
        self.human = human
        self.sources = sources


def compare_image(
    human: dict[str, int], results: list[SourceResult | None], label_keys: list[str]
) -> ImageComparison:
    """Compare the stored label state of one image with each source result.

    A label differs when the source assessed it (value not None) and the
    value deviates from labels.csv. Unlabeled images (no label set in
    labels.csv) are never compared: an unset label there means "not looked
    at yet", not "absent".
    """
    labeled = any(human.get(key, 0) for key in label_keys)
    compared = []
    for result in results:
        if result is None or not result.valid:
            status = STATUS_MISSING if result is None else STATUS_INVALID
            note = result.note if result is not None else None
            empty = {key: None for key in label_keys}
            compared.append(SourceComparison(status, empty, frozenset(), False, note))
            continue
        diffs = frozenset()
        if labeled:
            diffs = frozenset(
                key
                for key in label_keys
                if result.values[key] is not None and result.values[key] != human.get(key, 0)
            )
        compared.append(
            SourceComparison(STATUS_OK, result.values, diffs, result.uncertain, result.note)
        )
    return ImageComparison(labeled, human, compared)


def tab_keys(cmp: ImageComparison, scope: int | None) -> list[str]:
    """Return every comparison tab one image belongs to, including "all".

    scope restricts the evaluation to one source (its index); None means
    any selected source. An image is comparable when labels.csv labels it
    and at least one in-scope source has a valid result; comparable images
    land in "differences" (plus one tab per differing label) or "agreement",
    all others in "not comparable".
    """
    sources = cmp.sources if scope is None else cmp.sources[scope : scope + 1]
    usable = [s for s in sources if s.status == STATUS_OK]
    keys = [TAB_ALL]
    if cmp.labeled and usable:
        diffs = frozenset().union(*(s.diffs for s in usable))
        keys.append(TAB_DIFF if diffs else TAB_AGREE)
        keys.extend(sorted(diffs))
    else:
        keys.append(TAB_NONE)
    if any(s.uncertain for s in usable):
        keys.append(TAB_UNCERTAIN)
    return keys


def in_direction(cmp: ImageComparison, label_key: str, only: str) -> bool:
    """Apply the direction filter of a label tab (empty only = both directions).

    Within a label tab the label differs, so the stored value alone tells
    the direction: set in labels.csv means the source did not set it.
    """
    if only == ONLY_LABELER:
        return bool(cmp.human.get(label_key, 0))
    if only == ONLY_SOURCE:
        return not cmp.human.get(label_key, 0)
    return True


def matches_tab(cmp: ImageComparison, tab: str, scope: int | None, only: str = "") -> bool:
    """Return whether an image belongs to a comparison tab (and direction)."""
    return tab in tab_keys(cmp, scope) and in_direction(cmp, tab, only)


# -- agreement statistics --------------------------------------------------


class LabelStats:
    """Confusion counts of one label, with labels.csv as the reference."""

    __slots__ = ("tp", "fn", "fp", "tn")

    def __init__(self) -> None:
        """Start all counts at zero."""
        self.tp = self.fn = self.fp = self.tn = 0

    @property
    def n(self) -> int:
        """Number of images where both sides assessed the label."""
        return self.tp + self.fn + self.fp + self.tn

    @property
    def agreement(self) -> float | None:
        """Share of images with the same value on both sides."""
        return (self.tp + self.tn) / self.n if self.n else None

    @property
    def kappa(self) -> float | None:
        """Cohen's kappa; None when it is undefined (one class only on both sides)."""
        n = self.n
        if not n:
            return None
        observed = (self.tp + self.tn) / n
        expected = (
            (self.tp + self.fn) * (self.tp + self.fp) + (self.fp + self.tn) * (self.fn + self.tn)
        ) / (n * n)
        if expected >= 1:
            return None
        return (observed - expected) / (1 - expected)

    @property
    def precision(self) -> float | None:
        """Share of the source's positives that labels.csv confirms."""
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        """Share of the positives in labels.csv that the source found."""
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        """Harmonic mean of precision and recall."""
        denominator = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / denominator if denominator else None


class SourceStats:
    """Agreement counters of one source over a set of images."""

    def __init__(self, label_keys: list[str]) -> None:
        """Start all counters at zero."""
        self.compared = 0  # images compared (labeled + valid result)
        self.agree = 0  # compared images without any difference
        self.missing = 0
        self.invalid = 0
        self.unlabeled = 0  # valid result, but labels.csv has no label yet
        self.uncertain = 0
        self.labels = {key: LabelStats() for key in label_keys}

    @property
    def agreement(self) -> float | None:
        """Share of compared images that agree on every assessed label."""
        return self.agree / self.compared if self.compared else None


class CompareStats:
    """Accumulates per-source statistics over the images of one view."""

    def __init__(self, source_count: int, label_keys: list[str]) -> None:
        """Create one SourceStats per selected source."""
        self.label_keys = label_keys
        self.sources = [SourceStats(label_keys) for _ in range(source_count)]

    def add(self, cmp: ImageComparison) -> None:
        """Count one image comparison into every source's statistics."""
        for stats, result in zip(self.sources, cmp.sources, strict=True):
            if result.status == STATUS_MISSING:
                stats.missing += 1
                continue
            if result.status == STATUS_INVALID:
                stats.invalid += 1
                continue
            if result.uncertain:
                stats.uncertain += 1
            if not cmp.labeled:
                stats.unlabeled += 1
                continue
            stats.compared += 1
            if not result.diffs:
                stats.agree += 1
            for key in self.label_keys:
                value = result.values[key]
                if value is None:
                    continue
                counts = stats.labels[key]
                if cmp.human.get(key, 0):
                    if value:
                        counts.tp += 1
                    else:
                        counts.fn += 1
                elif value:
                    counts.fp += 1
                else:
                    counts.tn += 1
