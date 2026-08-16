"""Tests for the TIFF-to-JPEG preview generation (previews.py)."""

import numpy as np
import pytest
import tifffile
from PIL import Image

from previews import PreviewGenerator


@pytest.fixture
def generator(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    return images_dir, PreviewGenerator(str(images_dir), str(tmp_path / "previews"))


def _write_tiff(images_dir, name, data):
    tifffile.imwrite(str(images_dir / name), data)


def test_generate_uint16_preview(generator):
    images_dir, gen = generator
    rng = np.random.default_rng(1)
    _write_tiff(
        images_dir, "23-P09-B1_EL_Cell001.tif", rng.integers(0, 65535, (200, 300), dtype=np.uint16)
    )
    path = gen.get_preview_path("23-P09-B1_EL_Cell001.tif")
    assert path.endswith(".jpg")
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert img.width <= 2048 and img.height <= 2048


def test_generate_float_preview(generator):
    images_dir, gen = generator
    rng = np.random.default_rng(2)
    _write_tiff(images_dir, "23-P09-B1_UVF_Cell001.tif", rng.random((128, 128)).astype(np.float32))
    path = gen.get_preview_path("23-P09-B1_UVF_Cell001.tif")
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test_generate_jpg_preview(generator):
    images_dir, gen = generator
    rng = np.random.default_rng(3)
    Image.fromarray(rng.integers(0, 255, (64, 64), dtype=np.uint8)).save(
        str(images_dir / "23_089_A1_EL_LR_Cell001.jpg")
    )
    path = gen.get_preview_path("23_089_A1_EL_LR_Cell001.jpg")
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test_preview_is_cached(generator):
    images_dir, gen = generator
    _write_tiff(images_dir, "23-P09-B1_VI_Cell001.tif", np.zeros((64, 64), dtype=np.uint8))
    first = gen.get_preview_path("23-P09-B1_VI_Cell001.tif")
    second = gen.get_preview_path("23-P09-B1_VI_Cell001.tif")
    assert first == second


def test_uint16_conversion_keeps_high_byte(generator):
    """No normalization: a dark 16-bit recording must stay dark."""
    _, gen = generator
    dark = np.full((32, 32), 255, dtype=np.uint16)  # below the high-byte range
    assert gen._to_uint8(dark).max() == 0
    bright = np.full((32, 32), 65280, dtype=np.uint16)
    assert gen._to_uint8(bright).max() == 255


def test_uint8_passes_through_unchanged(generator):
    """8-bit data is displayed exactly as stored."""
    _, gen = generator
    arr = np.arange(256, dtype=np.uint8).reshape(16, 16)
    assert np.array_equal(gen._to_uint8(arr), arr)


def test_float_is_only_scaled_by_255(generator):
    _, gen = generator
    assert gen._to_uint8(np.zeros((4, 4), dtype=np.float32)).max() == 0
    assert gen._to_uint8(np.ones((4, 4), dtype=np.float32)).min() == 255


def test_preview_from_subfolder(generator):
    images_dir, gen = generator
    sub = images_dir / "sub"
    sub.mkdir()
    _write_tiff(sub, "23-P09-B1_EL_Cell001.tif", np.zeros((64, 64), dtype=np.uint8))
    path = gen.get_preview_path("sub/23-P09-B1_EL_Cell001.tif")
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test_rejects_traversal_and_non_image(generator):
    _, gen = generator
    with pytest.raises(ValueError):
        gen.get_preview_path("../evil.tif")
    with pytest.raises(ValueError):
        gen.get_preview_path("/abs/23-P09-B1_EL_Cell001.tif")
    with pytest.raises(ValueError):
        gen.get_preview_path("x.bmp")


def test_missing_file_raises(generator):
    _, gen = generator
    with pytest.raises(FileNotFoundError):
        gen.get_preview_path("nope.tif")
