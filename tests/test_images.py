"""Tests for filename parsing, scanning and grouping (images.py)."""

import pytest

from images import ImageIndex, modality_filename_codes, parse_filename, scan_images

MODALITIES = [
    {"code": "VI", "display_name": "VI", "filename_code": "VI"},
    {"code": "EL", "display_name": "EL", "filename_code": "EL"},
    {"code": "UVF", "display_name": "UVF", "filename_code": "UV"},
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
    mapping = modality_filename_codes([{"code": "EL", "display_name": "EL", "filename_code": "el"}])
    info = parse_filename("23-P09-B1_el_Cell001.tif", mapping)
    assert info is not None
    assert info.modality == "EL"
    assert parse_filename("23-P09-B1_EL_Cell001.tif", mapping) is not None


def test_parse_wrong_extension_or_missing_cell():
    assert parse_filename("23-P09-B1_EL_Cell001.bmp", CODES) is None
    assert parse_filename("23-P09-B1_EL.tif", CODES) is None
    assert parse_filename("random.tif", CODES) is None


def test_parse_jpg_with_variant():
    info = parse_filename("23_089_A1_EL_LR_Cell001.jpg", CODES)
    assert info is not None
    assert info.cell_type == "23_089_A1"
    assert info.modality == "EL"
    assert info.variant == "LR"
    assert info.cell_id == "Cell001"
    assert info.group_key == ("23_089_A1", "Cell001")


def test_parse_multiple_variant_segments():
    info = parse_filename("23_089_A1_EL_LR_HF_Cell001.jpg", CODES)
    assert info is not None
    assert info.variant == "LR_HF"


def test_parse_png_extension():
    info = parse_filename("23-P09-B1_EL_Cell001.png", CODES)
    assert info is not None and info.modality == "EL"


def test_scan_and_group(tmp_path):
    (tmp_path / "23-P09-B1_VI_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_UV_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B2_VI_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_XX_Cell001.tif").write_bytes(b"x")  # unknown modality
    (tmp_path / "readme.txt").write_bytes(b"x")  # not an image

    images, groups, unparseable = scan_images(str(tmp_path), CODES)
    assert set(images) == {
        "23-P09-B1_VI_Cell001.tif",
        "23-P09-B1_EL_Cell001.tif",
        "23-P09-B1_UV_Cell001.tif",
        "23-P09-B2_VI_Cell001.tif",
    }
    assert unparseable == ["23-P09-B1_XX_Cell001.tif"]
    assert set(groups[("23-P09-B1", "Cell001")]) == {"VI", "EL", "UVF"}
    # missing modalities simply do not appear in the group
    assert set(groups[("23-P09-B2", "Cell001")]) == {"VI"}


def test_scan_finds_images_in_subfolders(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23-P09-B1_VI_Cell001.tif").write_bytes(b"x")
    images, groups, unparseable = scan_images(str(tmp_path), CODES)
    assert set(images) == {"sub/23-P09-B1_EL_Cell001.tif", "23-P09-B1_VI_Cell001.tif"}
    assert unparseable == []
    # folder boundaries do not break the group
    assert set(groups[("23-P09-B1", "Cell001")]) == {"VI", "EL"}


def test_scan_same_basename_in_two_folders(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    (tmp_path / "b" / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    images, _, _ = scan_images(str(tmp_path), CODES)
    assert set(images) == {"a/23-P09-B1_EL_Cell001.tif", "b/23-P09-B1_EL_Cell001.tif"}


def test_scan_unparseable_in_subfolder_reports_relative_path(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "badname.tif").write_bytes(b"x")
    _, _, unparseable = scan_images(str(tmp_path), CODES)
    assert unparseable == ["sub/badname.tif"]


def test_index_rescans_on_directory_change(tmp_path):
    index = ImageIndex(str(tmp_path), CODES)
    assert index.get()[0] == {}
    (tmp_path / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    assert "23-P09-B1_EL_Cell001.tif" in index.get()[0]


def test_index_rescans_on_subfolder_change(tmp_path):
    index = ImageIndex(str(tmp_path), CODES)
    assert index.get()[0] == {}
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "23-P09-B1_EL_Cell001.tif").write_bytes(b"x")
    assert "sub/23-P09-B1_EL_Cell001.tif" in index.get()[0]


def test_group_with_variant_and_plain(tmp_path):
    (tmp_path / "23_089_A1_EL_Cell001.tif").write_bytes(b"x")
    (tmp_path / "23_089_A1_EL_LR_Cell001.jpg").write_bytes(b"x")
    _, groups, _ = scan_images(str(tmp_path), CODES)
    variants = groups[("23_089_A1", "Cell001")]["EL"]
    assert set(variants) == {None, "LR"}


# All filename formats from the user's real dataset must parse correctly.
@pytest.mark.parametrize(
    "filename,expected",
    [
        ("23_089_A1_EL01_LR_Cell001.jpg", ("23_089_A1", "EL", "Cell001", "01_LR")),
        ("23_089_A1_EL_LR_Cell001.jpg", ("23_089_A1", "EL", "Cell001", "LR")),
        ("23-P09-A1_EL_Cell020.tif", ("23-P09-A1", "EL", "Cell020", None)),
        ("23-P09-A2_UV_Cell054.tif", ("23-P09-A2", "UVF", "Cell054", None)),
        ("24-128_A2_EL_LR_Cell003.jpg", ("24-128_A2", "EL", "Cell003", "LR")),
        ("25-P03-A6_EL_P4_Cell019.tif", ("25-P03-A6", "EL", "Cell019", "P4")),
        ("25-P03-A6_UV_Cell017.tif", ("25-P03-A6", "UVF", "Cell017", None)),
        ("C14_A10_UV_Cell009.tif", ("C14_A10", "UVF", "Cell009", None)),
        ("C14_A6_UV_Cell046.tif", ("C14_A6", "UVF", "Cell046", None)),
        ("C14_A8_VI_Cell025.tif", ("C14_A8", "VI", "Cell025", None)),
        ("C14_H4_VI_Cell141.tif", ("C14_H4", "VI", "Cell141", None)),
        ("011_UV_Cell012.jpg", ("011", "UVF", "Cell012", None)),
        ("120_EL_Cell013.jpg", ("120", "EL", "Cell013", None)),
        ("23-P09-A2_EL_Cell114_normalized.tif", ("23-P09-A2", "EL", "Cell114", "normalized")),
        ("24-128_A2_UV_Cell035_normalized.tif", ("24-128_A2", "UVF", "Cell035", "normalized")),
        ("C14_A8_EL_Cell113_normalized.tif", ("C14_A8", "EL", "Cell113", "normalized")),
        ("C14_B6_UV_Cell068_normalized.tif", ("C14_B6", "UVF", "Cell068", "normalized")),
        ("23_P08_H1_VI_Cell021.tif", ("23_P08_H1", "VI", "Cell021", None)),
        ("1000000431018_UV_Cell034.tif", ("1000000431018", "UVF", "Cell034", None)),
        ("1000000474015_EL_Cell011.tif", ("1000000474015", "EL", "Cell011", None)),
    ],
)
def test_real_world_filenames(filename, expected):
    info = parse_filename(filename, CODES)
    assert info is not None
    assert (info.cell_type, info.modality, info.cell_id, info.variant) == expected
