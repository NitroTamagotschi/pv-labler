"""On-demand JPEG previews for the (possibly 16-bit/float) TIFF source images.

The original TIFF files are only ever read, never modified. Generated previews
are cached in static/previews/ and keyed by filename and source mtime.
"""

import hashlib
import os
import threading

import numpy as np
import tifffile
from PIL import Image

from images import IMAGE_EXTENSIONS

PREVIEW_MAX_SIZE = 2048
PREVIEW_QUALITY = 90


class PreviewError(Exception):
    """Raised when a preview cannot be generated."""


def probe_data_range(source: str) -> float:
    """Return the raw value range (max) of one image for slider sizing.

    TIFFs are probed header-only (float -> 1.0, wider than 8-bit -> 65535,
    otherwise 255); other formats are always 8-bit. Errors fall back to 255.
    """
    if source.lower().endswith((".tif", ".tiff")):
        try:
            with tifffile.TiffFile(source) as tif:
                dtype = tif.pages[0].dtype
            if dtype.kind == "f":
                return 1.0
            return 65535.0 if dtype.itemsize > 1 else 255.0
        except Exception:
            return 255.0
    return 255.0


class PreviewGenerator:
    """Generate and cache JPEG previews of the images in images_dir."""

    def __init__(self, images_dir: str, previews_dir: str) -> None:
        """Store the image and preview directories and a generation lock."""
        self.images_dir = os.path.abspath(images_dir)
        self.previews_dir = previews_dir
        self._lock = threading.Lock()

    def resolve_source(self, filename: str) -> str:
        """Validate a requested filename and return the absolute source path.

        The filename may be a path relative to images_dir (e.g. "sub/x.tif");
        absolute paths, drive prefixes and ".." traversal are rejected, and
        the resolved path must stay inside images_dir.
        """
        normalized = os.path.normpath(filename)
        if normalized.startswith(("..", os.sep, "/")) or os.path.splitdrive(normalized)[0]:
            raise ValueError("Invalid image filename")
        if not normalized.lower().endswith(IMAGE_EXTENSIONS):
            raise ValueError("Unsupported image extension")
        images_root = os.path.abspath(self.images_dir)
        source = os.path.abspath(os.path.join(images_root, normalized))
        if os.path.commonpath([images_root, source]) != images_root:
            raise ValueError("Invalid image filename")
        return source

    def get_preview_path(self, filename: str, window: tuple[float, float] | None = None) -> str:
        """Return the path of the cached preview, generating it on first use.

        window optionally maps the raw data range (lo, hi) linearly onto the
        8-bit display; without it, wider integer data keeps its high byte.
        """
        source = self.resolve_source(filename)
        if not os.path.isfile(source):
            raise FileNotFoundError(source)
        cache_path = os.path.join(self.previews_dir, self._cache_name(filename, source, window))
        if not os.path.isfile(cache_path):
            with self._lock:
                if not os.path.isfile(cache_path):
                    self._generate(source, cache_path, window)
        return cache_path

    def _cache_name(self, filename: str, source: str, window: tuple[float, float] | None) -> str:
        """Return the cache filename keyed by filename, mtime, size and window."""
        mtime = os.stat(source).st_mtime_ns
        digest = hashlib.sha256(
            f"{filename}|{mtime}|{PREVIEW_MAX_SIZE}|{window}".encode()
        ).hexdigest()[:16]
        stem = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in os.path.splitext(filename)[0]
        )
        return f"{stem}_{digest}.jpg"

    def _generate(self, source: str, cache_path: str, window: tuple[float, float] | None) -> None:
        """Write the cached JPEG preview for one source image (atomic replace)."""
        data = self._read_source(source)
        image = Image.fromarray(self._to_uint8(data, window))
        image.thumbnail((PREVIEW_MAX_SIZE, PREVIEW_MAX_SIZE), Image.Resampling.LANCZOS)
        os.makedirs(self.previews_dir, exist_ok=True)
        tmp_path = cache_path + ".tmp"
        try:
            image.save(tmp_path, format="JPEG", quality=PREVIEW_QUALITY)
            os.replace(tmp_path, cache_path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _read_source(self, source: str) -> np.ndarray:
        """Read the image data, using tifffile for TIFFs and Pillow otherwise."""
        if source.lower().endswith((".tif", ".tiff")):
            try:
                with tifffile.TiffFile(source) as tif:
                    return tif.pages[0].asarray()
            except Exception as exc:
                try:
                    with Image.open(source) as img:
                        return np.asarray(img)
                except Exception:
                    raise PreviewError(f"Cannot read {os.path.basename(source)}: {exc}") from exc
        try:
            with Image.open(source) as img:
                return np.asarray(img)
        except Exception as exc:
            raise PreviewError(f"Cannot read {os.path.basename(source)}: {exc}") from exc

    def _to_uint8(self, data: np.ndarray, window: tuple[float, float] | None = None) -> np.ndarray:
        """Convert image data to uint8 without any normalization.

        Only the conversion needed for display is applied: integer data
        either keeps its raw mapping (8-bit passes through unchanged, wider
        data keeps its high byte) or, when window (lo, hi) is given, is
        mapped linearly onto 0-255 with clipping outside the window. Float
        data (expected in the 0.0-1.0 range) is scaled by 255, and boolean
        masks become 0/255.
        """
        arr = np.asarray(data)
        if arr.size == 0:
            raise PreviewError("Empty image")
        arr = np.squeeze(arr)
        if arr.ndim == 3 and arr.shape[2] in (3, 4):
            arr = arr[:, :, :3]
        elif arr.ndim != 2:
            raise PreviewError(f"Unsupported image shape {arr.shape}")
        if arr.dtype == np.bool_:
            return arr.astype(np.uint8) * 255
        if window is not None and arr.dtype.kind in "ui":
            lo, hi = window
            # clamp to the image's own raw range, so a window configured in
            # 16-bit units cannot crush 8-bit images (and vice versa)
            native_max = (1 << (arr.dtype.itemsize * 8)) - 1
            hi = min(float(hi), float(native_max))
            lo = min(float(lo), hi)
            if hi > lo:
                scaled = (arr.astype(np.float64) - lo) / (hi - lo)
                return np.clip(scaled * 255.0, 0.0, 255.0).astype(np.uint8)
            # the window collapses against the native range: fall through
            # to the raw mapping below
        if arr.dtype == np.uint8:
            return np.ascontiguousarray(arr)
        if arr.dtype.kind == "f":
            return np.clip(arr * 255.0, 0.0, 255.0).astype(np.uint8)
        if arr.dtype.kind == "i":
            arr = arr.view(f"u{arr.dtype.itemsize}")  # reinterpret the same bits
        shift = (arr.itemsize - 1) * 8
        return (arr >> shift).astype(np.uint8)
