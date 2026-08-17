"""Tests for the sample image schedule (scripts/create_sample_images.py)."""

import csv
import importlib.util
from pathlib import Path

from app import load_config
from images import modality_filename_codes, parse_filename
from labels import modality_to_column

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_sample_images.py"


def _load_schedule():
    spec = importlib.util.spec_from_file_location("create_sample_images", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schedule_covers_every_defect_type():
    schedule = _load_schedule()
    scheduled = {d for entry in schedule.CELL_DEFECTS for d in entry}
    assert scheduled == set(schedule.DEFECT_VISIBILITY)


def test_schedule_contains_multi_defect_cells():
    schedule = _load_schedule()
    multi = [entry for entry in schedule.CELL_DEFECTS if len(entry) > 1]
    assert len(multi) >= 3


def test_schedule_contains_good_cell():
    schedule = _load_schedule()
    assert any(not entry for entry in schedule.CELL_DEFECTS)


def test_every_defect_visible_in_some_modality():
    schedule = _load_schedule()
    for key, modalities in schedule.DEFECT_VISIBILITY.items():
        assert modalities, f"defect {key} has no visible modality"


def test_ground_truth_covers_every_image():
    schedule = _load_schedule()
    planned = {filename for filename, _, _ in schedule.image_plan()}
    assert set(schedule.ground_truth_labels()) == planned


def test_ground_truth_good_rows_have_no_defects():
    schedule = _load_schedule()
    for filename, row in schedule.ground_truth_labels().items():
        if row["good"]:
            assert not any(row[key] for key in schedule.DEFECT_VISIBILITY), filename
        else:
            assert any(row[key] for key in schedule.DEFECT_VISIBILITY), filename


def test_ground_truth_variant_jpg_matches_its_tif():
    schedule = _load_schedule()
    truth = schedule.ground_truth_labels()
    assert truth["TEST_23_089_A1_EL_LR_Cell001.jpg"] == truth["TEST_23_089_A1_EL_Cell001.tif"]
    assert truth["TEST_23_089_A1_EL_LR_Cell002.jpg"] == truth["TEST_23_089_A1_EL_Cell002.tif"]


def test_ground_truth_csv_schema_and_values(tmp_path):
    """ground_truth.csv uses the labels.csv schema (§8.2) and matches the labels."""
    schedule = _load_schedule()
    path = tmp_path / "ground_truth.csv"
    schedule.write_ground_truth_csv(str(path))
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "Datum",
            "Zeit",
            "Name of labeler",
            "datename",
            "uv",
            "vi",
            "el",
            "good",
            "crack",
            "cross",
            "dark",
            "corrosion",
            "discoloration",
            "delamination",
        ]
        rows = {row["datename"]: row for row in reader}
    truth = schedule.ground_truth_labels()
    assert set(rows) == set(truth)
    for filename, row in rows.items():
        assert row["Datum"] == "" and row["Zeit"] == ""
        assert row["Name of labeler"] == "GroundTruth"
        for key in ["good", *schedule.DEFECT_VISIBILITY]:
            assert row[key] == str(truth[filename][key]), filename


def test_ground_truth_csv_modality_columns_match_config(tmp_path):
    """uv/vi/el agree with the app's config-driven filename mapping."""
    schedule = _load_schedule()
    path = tmp_path / "ground_truth.csv"
    schedule.write_ground_truth_csv(str(path))
    app_config = load_config()
    filename_codes = modality_filename_codes(app_config["modalities"])
    columns = {m["code"]: modality_to_column(m["code"]) for m in app_config["modalities"]}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            info = parse_filename(row["datename"], filename_codes)
            assert info is not None, row["datename"]
            for code, column in columns.items():
                expected = "1" if code == info.modality else "0"
                assert row[column] == expected, row["datename"]
