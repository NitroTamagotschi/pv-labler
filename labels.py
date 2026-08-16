"""Persistence of label data (labels.csv) and the append-only change log.

The CSV layout is defined in specification.md §8.2: one current row per image
file, updated in place instead of duplicated. All writes are serialized with a
lock and done atomically (temp file + os.replace).
"""

import csv
import datetime as dt
import os
import tempfile
import threading

# Fixed column prefix, exactly as required by the specification (§8.2).
FIXED_COLUMNS = ["Datum", "Zeit", "Name of labeler", "datename"]
# Required order of the modality columns for the standard configuration (§8.2).
SPEC_MODALITY_COLUMNS = ["uv", "vi", "el"]


def modality_to_column(code):
    """Map a configured modality code to its CSV column name (§8.2: UVF -> uv)."""
    normalized = code.lower()
    if normalized == "uvf":
        normalized = "uv"
    return normalized


def modality_columns(modality_codes):
    """CSV column names for the configured modalities.

    Uses the fixed order uv,vi,el from the specification whenever the
    configured set matches it, otherwise the configuration order.
    """
    mapped = [modality_to_column(code) for code in modality_codes]
    if set(mapped) == set(SPEC_MODALITY_COLUMNS):
        return SPEC_MODALITY_COLUMNS
    return mapped


def apply_label_change(labels, good_key, defect_keys, key, value):
    """Return a new label dict with the exclusivity rules of §7.2 applied.

    The returned dict always contains every label key (missing keys count as
    unset). Raises ValueError for unknown keys or invalid combinations.
    """
    if key != good_key and key not in defect_keys:
        raise ValueError(f"Unknown label key: {key}")
    new = {k: int(labels.get(k, 0)) for k in [good_key] + list(defect_keys)}
    new[key] = 1 if value else 0
    if key == good_key and new[key]:
        for defect in defect_keys:
            new[defect] = 0
    if key in defect_keys and new[key]:
        new[good_key] = 0
    if new.get(good_key) and any(new.get(d) for d in defect_keys):
        raise ValueError("Good cannot be combined with a defect label")
    return new


class LabelStore:
    """Reads and writes labels.csv and appends change-log entries."""

    def __init__(self, csv_path, log_path, config):
        """Store paths, column layout and label keys; create the write lock."""
        self.csv_path = csv_path
        self.log_path = log_path
        self.modality_cols = modality_columns([m["code"] for m in config["modalities"]])
        self.good_key = config["labels"]["good"]["key"]
        self.defect_keys = [d["key"] for d in config["labels"]["defects"]]
        self.label_keys = [self.good_key] + self.defect_keys
        self.columns = FIXED_COLUMNS + self.modality_cols + self.label_keys
        self._lock = threading.Lock()

    # -- reading -----------------------------------------------------------

    def _read_rows(self):
        """Return {filename: raw csv row dict} (one row per image file)."""
        rows = {}
        if not os.path.isfile(self.csv_path):
            return rows
        with open(self.csv_path, encoding="utf-8", newline="") as f:
            for raw in csv.DictReader(f):
                filename = (raw.get("datename") or "").strip()
                if not filename:
                    continue
                rows[filename] = raw
        return rows

    def _parse_labels(self, raw):
        """Return {label_key: 0|1} parsed from one raw CSV row."""
        return {key: 1 if str(raw.get(key, "")).strip() == "1" else 0 for key in self.label_keys}

    def get_states(self):
        """Return {filename: {label_key: 0|1}} for all stored rows."""
        with self._lock:
            return {
                filename: self._parse_labels(raw) for filename, raw in self._read_rows().items()
            }

    def get_state(self, filename):
        """Return the stored label state of one file (all zeros if unlabeled)."""
        with self._lock:
            raw = self._read_rows().get(filename)
        if raw is None:
            return {key: 0 for key in self.label_keys}
        return self._parse_labels(raw)

    # -- writing ------------------------------------------------------------

    def set_label(self, filename, modality_code, key, value, labeler):
        """Apply one checkbox change, persist it and append a log entry.

        Returns the new label state {key: 0|1}. The whole read-modify-write
        cycle runs under the lock so concurrent requests cannot corrupt data.
        """
        now = dt.datetime.now()
        with self._lock:
            rows = self._read_rows()
            before = self._parse_labels(rows.get(filename, {}))
            after = apply_label_change(before, self.good_key, self.defect_keys, key, value)
            rows[filename] = self._build_row(filename, modality_code, after, labeler, now)
            self._write_csv(rows.values())
            self._append_log(now, labeler, filename, before, after)
        return after

    def set_states(self, updates, labeler):
        """Persist a batch of full label states in one CSV rewrite.

        updates maps filename -> (modality_code, {key: 0|1}). Each input state
        is validated strictly (unknown keys and Good+defect combinations raise
        ValueError); every key is then folded through apply_label_change so
        exclusivity cascades against the stored state. One change-log entry is
        appended per changed file; files whose state does not change are
        skipped entirely. All changes are written under a single lock hold.
        """
        now = dt.datetime.now()
        label_key_set = set(self.label_keys)
        with self._lock:
            rows = self._read_rows()
            results = {}
            log_entries = []
            for filename, (modality_code, new_state) in updates.items():
                unknown = set(new_state) - label_key_set
                if unknown:
                    raise ValueError(f"Unknown label key(s): {sorted(unknown)}")
                if new_state.get(self.good_key) and any(new_state.get(d) for d in self.defect_keys):
                    raise ValueError("Good cannot be combined with a defect label")
                before = self._parse_labels(rows.get(filename, {}))
                after = before  # apply_label_change always builds a fresh dict
                for key, value in new_state.items():
                    after = apply_label_change(
                        after, self.good_key, self.defect_keys, key, 1 if value else 0
                    )
                if after == before:
                    continue
                rows[filename] = self._build_row(filename, modality_code, after, labeler, now)
                results[filename] = after
                log_entries.append((now, labeler, filename, before, after))
            if log_entries:
                self._write_csv(rows.values())
                self._append_logs(log_entries)
        return results

    def _build_row(self, filename, modality_code, labels, labeler, now):
        row = {
            "Datum": now.strftime("%Y-%m-%d"),
            "Zeit": now.strftime("%H:%M:%S"),
            "Name of labeler": labeler,
            "datename": filename,
        }
        modality_col = modality_to_column(modality_code)
        for col in self.modality_cols:
            row[col] = 1 if col == modality_col else 0
        for key in self.label_keys:
            row[key] = int(labels.get(key, 0))
        return row

    def _write_csv(self, rows):
        """Atomically rewrite labels.csv (temp file + os.replace)."""
        directory = os.path.dirname(os.path.abspath(self.csv_path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.columns)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(tmp_path, self.csv_path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _log_line(self, now, labeler, filename, before, after):
        """Format one change-log entry (timestamp | labeler | file | before | after)."""

        def fmt(state):
            return ", ".join(f"{key}={state.get(key, 0)}" for key in self.label_keys)

        return (
            f"{now.strftime('%Y-%m-%d %H:%M:%S')} | {labeler} | {filename} | "
            f"before: {fmt(before)} | after: {fmt(after)}"
        )

    def _append_log(self, now, labeler, filename, before, after):
        """Append one entry to the change log (existing entries are never rewritten)."""
        self._append_logs([(now, labeler, filename, before, after)])

    def _append_logs(self, entries):
        """Append several change-log entries in a single file open."""
        directory = os.path.dirname(os.path.abspath(self.log_path))
        os.makedirs(directory, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
            for entry in entries:
                f.write(self._log_line(*entry) + "\n")
