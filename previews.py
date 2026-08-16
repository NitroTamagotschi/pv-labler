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

PREVIEW_MAX_SIZE = 1024
PREVIEW_QUALITY = 90


class PreviewError(Exception):
    """Raised when a preview cannot be generated."""


class PreviewGenerator:
    """Generate and cache JPEG previews of the images in images_dir."""

    def __init__(self, images_dir, previews_dir):
        """Store the image and preview directories and a generation lock."""
        self.images_dir = os.path.abspath(images_dir)
        self.previews_dir = previews_dir
        self._lock = threading.Lock()

    def resolve_source(self, filename):
        """Validate a requested filename and return the absolute source path."""
        if os.path.basename(filename) != filename:
            raise ValueError("Invalid image filename")
        if not filename.lower().endswith(IMAGE_EXTENSIONS):
            raise ValueError("Unsupported image extension")
        return os.path.join(self.images_dir, filename)

    def get_preview_path(self, filename):
        """Return the path of the cached preview, generating it on first use."""
        source = self.resolve_source(filename)
        if not os.path.isfile(source):
            raise FileNotFoundError(source)
        cache_path = os.path.join(self.previews_dir, self._cache_name(filename, source))
        if not os.path.isfile(cache_path):
            with self._lock:
                if not os.path.isfile(cache_path):
                    self._generate(source, cache_path)
        return cache_path

    def _cache_name(self, filename, source):
        """Return the preview cache filename keyed by filename and source mtime."""
        mtime = os.stat(source).st_mtime_ns
        digest = hashlib.sha256(f"{filename}|{mtime}".encode()).hexdigest()[:16]
        stem = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in os.path.splitext(filename)[0]
        )
        return f"{stem}_{digest}.jpg"

    def _generate(self, source, cache_path):
        """Write the cached JPEG preview for one source image (atomic replace)."""
        data = self._read_source(source)
        image = Image.fromarray(self._to_uint8(data))
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

    def _read_source(self, source):
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

    def _to_uint8(self, data):
        """Convert arbitrary image data to an 8-bit RGB-safe array."""
        arr = np.asarray(data)
        if arr.size == 0:
            raise PreviewError("Empty image")
        arr = np.squeeze(arr)
        if arr.ndim == 3 and arr.shape[2] in (3, 4):
            return self._scale_to_uint8(arr[:, :, :3])
        if arr.ndim != 2:
            raise PreviewError(f"Unsupported image shape {arr.shape}")
        return self._scale_to_uint8(arr)

    def _scale_to_uint8(self, arr):
        """Normalize arbitrary data to uint8 for display.

        Float data is scaled by min/max; integer data gets a 2-98 percentile
        stretch so dark EL recordings remain visible.
        """
        if arr.dtype == np.bool_:
            return arr.astype(np.uint8) * 255
        values = arr.astype(np.float64)
        finite = np.isfinite(values)
        if not finite.any():
            return np.zeros(arr.shape[:2], dtype=np.uint8)
        if arr.dtype.kind == "f":
            lo, hi = float(np.min(values[finite])), float(np.max(values[finite]))
        else:
            lo, hi = np.nanpercentile(values, 2), np.nanpercentile(values, 98)
            if not hi > lo:
                lo, hi = float(np.min(values[finite])), float(np.max(values[finite]))
        if not hi > lo:
            hi = lo + 1.0
        scaled = (values - lo) / (hi - lo)
        return np.clip(scaled * 255.0, 0.0, 255.0).astype(np.uint8)
