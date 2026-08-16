"""Tests for the sample image schedule (scripts/create_sample_images.py)."""

import importlib.util
from pathlib import Path

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
    assert truth["23_089_A1_EL_LR_Cell001.jpg"] == truth["23_089_A1_EL_Cell001.tif"]
    assert truth["23_089_A1_EL_LR_Cell002.jpg"] == truth["23_089_A1_EL_Cell002.tif"]
