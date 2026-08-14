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
