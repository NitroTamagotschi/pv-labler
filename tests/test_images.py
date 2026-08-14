"""Tests for filename parsing, scanning and grouping (images.py)."""
from images import ImageIndex, modality_filename_codes, parse_filename, scan_images

MODALITIES = [
    {"code": "VI", "display_name": "VI"},
    {"code": "EL", "display_name": "EL"},
    {"code": "UVF", "display_name": "UVF"},
]
CODES = modality_filename_codes(MODALITIES)


def test_parse_valid():
    info = parse_filename("23-P09-B1_EL_Cell001.tif", CODES)
    assert info is not None
    assert info.cell_type == "23-P09-B1"
    assert info.modality == "EL"
    assert info.cell_id == "Cell001"
    assert info.group_key == ("23-P09-B1", "Cell001")


def test_parse_underscores_in_cell_type():
    info = parse_filename("23_P09_B1_EL_Cell001.tif", CODES)
    assert info.cell_type == "23_P09_B1"


def test_parse_case_insensitive():
    info = parse_filename("23-P09-B1_el_Cell001.TIFF", CODES)
    assert info is not None
    assert info.modality == "EL"  # canonical spelling from the configuration


def test_parse_unknown_modality():
    assert parse_filename("23-P09-B1_IR_Cell001.tif", CODES) is None


def test_filename_code_override():
    # real filenames use "UV" while the technical code is "UVF" (§3.1)
    mapping = modality_filename_codes(
        [{"code": "UVF", "display_name": "UVF", "filename_code": "UV"}]
    )
    info = parse_filename("23-P09-B1_UV_Cell001.tif", mapping)
    assert info is not None
    assert info.modality == "UVF"
    assert parse_filename("23-P09-B1_UVF_Cell001.tif", mapping) is None


def test_filename_code_case_insensitive():
    mapping = modality_filename_codes(
        [{"code": "EL", "display_name": "EL", "filename_code": "el"}]
    )
    info = parse_filename("23-P09-B1_el_Cell001.tif", mapping)
    assert info is not None
    assert info.modality == "EL"
    assert parse_filename("23-P09-B1_EL_Cell001.tif", mapping) is not None


def test_parse_wrong_extension_or_missing_cell():
    assert parse_filename("23-P09-B1_EL_Cell001.png", CODES) is None
    assert parse_filename("23-P09-B1_EL.tif", CODES) is None
    assert parse_filename("random.tif", CODES) is None


def test_scan_and_group(tmp_path):
    (tmp_path / "23-P09-B1_VI_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_UVF_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B2_VI_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_XX_Cell001.tif").write_bytes(b"x")  # unknown modality
    (tmp_path / "readme.txt").write_bytes(b"x")  # not an image

    images, groups, unparseable = scan_images(str(tmp_path), CODES)
    assert set(images) == {
        "23-P09-B1_VI_Cell001.tif",
        "23-P09-B1_EL_Cell001.tif",
        "23-P09-B1_UVF_Cell001.tif",
        "23-P09-B2_VI_Cell001.tif",
    }
    assert unparseable == ["23-P09-B1_XX_Cell001.tif"]
    assert set(groups[("23-P09-B1", "Cell001")]) == {"VI", "EL", "UVF"}
    # missing modalities simply do not appear in the group
    assert set(groups[("23-P09-B2", "Cell001")]) == {"VI"}


def test_index_rescans_on_directory_change(tmp_path):
    index = ImageIndex(str(tmp_path), CODES)
    assert index.get()[0] == {}
    (tmp_path / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    assert "23-P09-B1_EL_Cell001.tif" in index.get()[0]
