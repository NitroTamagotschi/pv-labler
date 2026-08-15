"""Tests for the label rules, CSV persistence and change log (labels.py)."""
import csv
import re
from pathlib import Path

import pytest

from labels import LabelStore, apply_label_change, modality_columns

CONFIG = {
    "modalities": [
        {"code": "VI", "display_name": "VI"},
        {"code": "EL", "display_name": "EL"},
        {"code": "UVF", "display_name": "UVF"},
    ],
    "labels": {
        "good": {"key": "good", "display_name": "Good"},
        "defects": [
            {"key": "crack", "display_name": "Crack"},
            {"key": "cross", "display_name": "Cross"},
            {"key": "dark", "display_name": "Dark"},
            {"key": "corrosion", "display_name": "Corrosion"},
            {"key": "discoloration", "display_name": "Discoloration"},
            {"key": "delamination", "display_name": "Delamination"},
        ],
    },
}

GOOD = "good"
DEFECTS = [d["key"] for d in CONFIG["labels"]["defects"]]

EXPECTED_COLUMNS = [
    "Datum", "Zeit", "Name of labeler", "datename",
    "uv", "vi", "el", "good",
    "crack", "cross", "dark", "corrosion", "discoloration", "delamination",
]


def make_store(tmp_path):
    return LabelStore(
        str(tmp_path / "labels.csv"), str(tmp_path / "change_log.txt"), CONFIG
    )


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# -- modality columns ------------------------------------------------------


def test_modality_columns_spec_order():
    # config order is VI, EL, UVF but the CSV order is fixed to uv, vi, el (§8.2)
    assert modality_columns(["VI", "EL", "UVF"]) == ["uv", "vi", "el"]


def test_modality_columns_custom_config():
    assert modality_columns(["UVF"]) == ["uv"]
    assert modality_columns(["X1", "Y2"]) == ["x1", "y2"]


# -- label rules ------------------------------------------------------------


def test_good_set_clears_defects():
    state = {"good": 0, "crack": 1, "cross": 0}
    new = apply_label_change(state, GOOD, DEFECTS, "good", 1)
    assert new["good"] == 1
    assert all(new[d] == 0 for d in DEFECTS)
    assert set(new) == {GOOD, *DEFECTS}


def test_defect_set_clears_good():
    state = {"good": 1, "crack": 0}
    new = apply_label_change(state, GOOD, DEFECTS, "crack", 1)
    assert new["good"] == 0 and new["crack"] == 1


def test_multiple_defects_allowed():
    state = {"good": 0, "crack": 1, "corrosion": 0}
    new = apply_label_change(state, GOOD, DEFECTS, "corrosion", 1)
    assert new["crack"] == 1 and new["corrosion"] == 1 and new["good"] == 0


def test_unset_last_defect_leaves_unclassified():
    state = {"good": 0, "crack": 1}
    new = apply_label_change(state, GOOD, DEFECTS, "crack", 0)
    assert not new["good"] and not any(new[d] for d in DEFECTS)


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        apply_label_change({"good": 0}, GOOD, DEFECTS, "nope", 1)


# -- CSV persistence --------------------------------------------------------


def test_store_writes_spec_csv(tmp_path):
    store = make_store(tmp_path)
    store.set_label("23-P09-B1_EL_Cell001.tif", "EL", "crack", 1, "Max Muster")
    rows = read_csv(store.csv_path)
    assert len(rows) == 1
    assert list(rows[0].keys()) == EXPECTED_COLUMNS
    row = rows[0]
    assert row["datename"] == "23-P09-B1_EL_Cell001.tif"
    assert row["Name of labeler"] == "Max Muster"
    assert (row["uv"], row["vi"], row["el"]) == ("0", "0", "1")  # exactly one modality = 1
    assert row["crack"] == "1" and row["good"] == "0"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Datum"])
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", row["Zeit"])


def test_store_updates_row_in_place(tmp_path):
    store = make_store(tmp_path)
    filename = "23-P09-B1_EL_Cell001.tif"
    store.set_label(filename, "EL", "crack", 1, "Max")
    store.set_label(filename, "EL", "good", 1, "Erika")
    rows = read_csv(store.csv_path)
    assert len(rows) == 1  # no duplicate row for the same file
    assert rows[0]["crack"] == "0" and rows[0]["good"] == "1"
    assert rows[0]["Name of labeler"] == "Erika"


def test_labeling_second_file_preserves_first_row(tmp_path):
    store = make_store(tmp_path)
    store.set_label("23-P09-B1_EL_Cell001.tif", "EL", "crack", 1, "Max")
    first_datum = read_csv(store.csv_path)[0]["Datum"]
    # labeling another file must not break the CSV write nor touch the first row
    store.set_label("23-P09-B1_EL_Cell002.tif", "EL", "cross", 1, "Max")
    rows = read_csv(store.csv_path)
    assert len(rows) == 2
    by_name = {row["datename"]: row for row in rows}
    assert by_name["23-P09-B1_EL_Cell001.tif"]["crack"] == "1"
    assert by_name["23-P09-B1_EL_Cell001.tif"]["Datum"] == first_datum
    assert by_name["23-P09-B1_EL_Cell002.tif"]["cross"] == "1"


def test_uvf_maps_to_uv_column(tmp_path):
    store = make_store(tmp_path)
    store.set_label("23-P09-B1_UVF_Cell001.tif", "UVF", "good", 1, "Max")
    row = read_csv(store.csv_path)[0]
    assert (row["uv"], row["vi"], row["el"]) == ("1", "0", "0")


def test_unlabeled_file_returns_zero_state(tmp_path):
    store = make_store(tmp_path)
    state = store.get_state("23-P09-B1_EL_Cell042.tif")
    assert state == {key: 0 for key in [GOOD] + DEFECTS}


# -- change log -------------------------------------------------------------


def test_change_log_format_and_append_only(tmp_path):
    store = make_store(tmp_path)
    filename = "23-P09-B1_UVF_Cell001.tif"
    store.set_label(filename, "UVF", "good", 1, "Max")
    store.set_label(filename, "UVF", "dark", 1, "Max")
    lines = Path(store.log_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| Max \| "
        r"23-P09-B1_UVF_Cell001\.tif \| before: .+ \| after: .+$"
    )
    assert pattern.fullmatch(lines[0])
    assert "before: good=1, crack=0" in lines[1]
    after_part = lines[1].split("after: ", 1)[1]
    assert "good=0" in after_part and "dark=1" in after_part


# -- batch save (set_states) --------------------------------------------------


def test_set_states_batch_writes_one_row_per_file(tmp_path):
    store = make_store(tmp_path)
    results = store.set_states(
        {
            "23-P09-B1_EL_Cell001.tif": ("EL", {"crack": 1}),
            "23-P09-B1_VI_Cell002.tif": ("VI", {"good": 1}),
        },
        "Max",
    )
    assert results["23-P09-B1_EL_Cell001.tif"]["crack"] == 1
    assert results["23-P09-B1_VI_Cell002.tif"]["good"] == 1
    rows = read_csv(store.csv_path)
    assert len(rows) == 2
    by_name = {row["datename"]: row for row in rows}
    assert (by_name["23-P09-B1_EL_Cell001.tif"]["uv"],
            by_name["23-P09-B1_EL_Cell001.tif"]["vi"],
            by_name["23-P09-B1_EL_Cell001.tif"]["el"]) == ("0", "0", "1")
    assert (by_name["23-P09-B1_VI_Cell002.tif"]["uv"],
            by_name["23-P09-B1_VI_Cell002.tif"]["vi"],
            by_name["23-P09-B1_VI_Cell002.tif"]["el"]) == ("0", "1", "0")
    # one log entry per changed file
    lines = Path(store.log_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "23-P09-B1_EL_Cell001.tif" in lines[0]
    assert "23-P09-B1_VI_Cell002.tif" in lines[1]


def test_set_states_cascades_from_stored_state(tmp_path):
    store = make_store(tmp_path)
    filename = "23-P09-B1_EL_Cell001.tif"
    store.set_label(filename, "EL", "crack", 1, "Max")
    results = store.set_states({filename: ("EL", {"good": 1})}, "Max")
    assert results[filename]["good"] == 1 and results[filename]["crack"] == 0
    lines = Path(store.log_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # one entry from set_label, one from set_states
    assert "before: good=0, crack=1" in lines[1]
    after_part = lines[1].split("after: ", 1)[1]
    assert "good=1" in after_part and "crack=0" in after_part


def test_set_states_skips_unchanged(tmp_path):
    store = make_store(tmp_path)
    filename = "23-P09-B1_EL_Cell001.tif"
    store.set_label(filename, "EL", "crack", 1, "Max")
    results = store.set_states({filename: ("EL", {"crack": 1})}, "Max")
    assert results == {}
    assert len(Path(store.log_path).read_text(encoding="utf-8").splitlines()) == 1
    rows = read_csv(store.csv_path)
    assert len(rows) == 1 and rows[0]["Datum"] != ""  # row untouched


def test_set_states_rejects_unknown_key(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.set_states({"23-P09-B1_EL_Cell001.tif": ("EL", {"nope": 1})}, "Max")


def test_set_states_rejects_good_defect_conflict(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.set_states(
            {"23-P09-B1_EL_Cell001.tif": ("EL", {"good": 1, "crack": 1})}, "Max"
        )
