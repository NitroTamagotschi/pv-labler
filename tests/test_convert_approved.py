"""Tests for the approved-OLLM CSV converter (scripts/convert_approved_labels.py)."""

import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "convert_approved_labels.py"

CONFIG = {
    "modalities": [
        {"code": "VI", "display_name": "VI", "filename_code": "VI"},
        {"code": "EL", "display_name": "EL", "filename_code": "EL"},
        {"code": "UVF", "display_name": "UVF", "filename_code": "UV"},
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


def _load_converter():
    spec = importlib.util.spec_from_file_location("convert_approved_labels", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _approved_csv(tmp_path, lines):
    path = tmp_path / "approved.csv"
    path.write_text("filename,labels\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _image(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_modality_info_maps_filename_codes_to_columns():
    convert = _load_converter()
    modalities = CONFIG["modalities"]
    assert convert.modality_info("23-P09-C4_VI_Cell001_normalized.tif", modalities) == (
        "vi",
        "VI",
    )
    assert convert.modality_info("23-P09-C9_UV_Cell003_normalized.tif", modalities) == (
        "uv",
        "UV",
    )
    assert convert.modality_info("23-P09-C7_el_Cell042_normalized.tif", modalities) == (
        "el",
        "EL",
    )
    assert convert.modality_info("23-P09-C5_XY_Cell020_normalized.tif", modalities) is None


def test_read_approved_rows_merges_repeated_rows_and_reports_failures(tmp_path):
    convert = _load_converter()
    path = _approved_csv(
        tmp_path,
        [
            "23-P09-C4_VI_Cell001_normalized.tif,discoloration",
            "23-P09-C4_VI_Cell001_normalized.tif,dark",
            "23-P09-C9_UV_Cell003_normalized.tif,good",
            "23-P09-C5_XY_Cell020_normalized.tif,dark",
            "23-P09-C6_VI_Cell099_normalized.tif,",
            ",dark",
        ],
    )
    failures = []
    approved = convert.read_approved_rows(str(path), CONFIG["modalities"], failures)
    assert approved["23-P09-C4_VI_Cell001_normalized.tif"] == (
        "vi",
        "VI",
        {"discoloration", "dark"},
        ["discoloration", "dark"],
    )
    assert approved["23-P09-C9_UV_Cell003_normalized.tif"] == ("uv", "UV", {"good"}, ["good"])
    assert len(approved) == 2
    reasons = {reason for _name, _labels, reason in failures}
    assert "no modality segment in file name" in reasons
    assert "empty labels" in reasons
    assert "row without filename" in reasons


def test_resolve_image_path_finds_unique_and_reports_missing_and_ambiguous():
    convert = _load_converter()
    index = {
        "23-P09-C4_VI_Cell001_normalized.tif": ["23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif"],
        "cell.tif": ["a/cell.tif", "b/cell.tif"],
    }
    assert convert.resolve_image_path(
        "23-P09-C4_VI_Cell001_normalized.tif", index
    ) == ("23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif", None)
    path, error = convert.resolve_image_path("missing.tif", index)
    assert path is None and "not found" in error
    path, error = convert.resolve_image_path("cell.tif", index)
    assert path is None and "ambiguous" in error
    # an explicit directory part is kept when it matches an existing image
    assert convert.resolve_image_path(
        "23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif", index
    ) == ("23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif", None)


def test_resolve_images_dir_prefers_override_then_config(tmp_path):
    convert = _load_converter()
    images = str(tmp_path / "images")
    assert convert.resolve_images_dir({"images_dir": images}, None) == images
    assert convert.resolve_images_dir({"images_dir": images}, "/other") == "/other"
    assert convert.resolve_images_dir({}, None) == convert.DEFAULT_IMAGES_DIR


def test_build_label_state_prefers_defects_over_good():
    convert = _load_converter()
    defect_keys = [d["key"] for d in CONFIG["labels"]["defects"]]
    state = convert.build_label_state({"good", "dark"}, "good", defect_keys)
    assert state["dark"] == 1
    assert state["good"] == 0
    assert state["crack"] == 0


def test_main_resolves_paths_writes_output_and_failure_report(tmp_path, monkeypatch):
    convert = _load_converter()
    images_dir = tmp_path / "images"
    _image(images_dir, "23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif")
    input_path = _approved_csv(
        tmp_path,
        [
            "23-P09-C4_VI_Cell001_normalized.tif,dark discoloration",
            "23-P09-C9_UV_Cell003_normalized.tif,good",
            "23-P09-C8_VI_Cell077_normalized.tif,scratch",
        ],
    )
    output_path = tmp_path / "labels.csv"
    output_path.write_text(
        "Datum,Zeit,Name of labeler,datename,uv,vi,el,good,crack,cross,dark,"
        "corrosion,discoloration,delamination\n"
        "2026-08-17,20:34:43,Kevin,TEST_23-P09-B1_VI_Cell001.tif,0,1,0,0,0,0,0,0,0,0\n"
        "2026-08-17,20:55:43,Kevin,23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif,"
        "0,1,0,0,0,0,0,0,0,0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "convert_approved_labels.py",
            str(input_path),
            "--labeler",
            "Anna",
            "--output",
            str(output_path),
            "--images-dir",
            str(images_dir),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        convert.main()
    assert excinfo.value.code == 1

    with open(output_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_name = {row["datename"]: row for row in rows}
    # untouched row keeps its original values
    assert by_name["TEST_23-P09-B1_VI_Cell001.tif"]["Name of labeler"] == "Kevin"
    # updated row is rewritten with the new labeler and labels
    updated = by_name["23-P09-C/VI/23-P09-C4_VI_Cell001_normalized.tif"]
    assert updated["Name of labeler"] == "Anna"
    assert updated["vi"] == "1" and updated["dark"] == "1" and updated["discoloration"] == "1"
    assert updated["good"] == "0"
    assert len(rows) == 2

    failure_path = tmp_path / "labels_failed.csv"
    with open(failure_path, encoding="utf-8", newline="") as f:
        failed = list(csv.DictReader(f))
    reasons = {row["reason"] for row in failed}
    assert any("not found" in reason for reason in reasons)
    assert any("unknown label token(s): scratch" in reason for reason in reasons)
    assert len(failed) == 2
