"""Scanning, parsing and grouping of the image files in data/images/.

Filename format (specification.md §4.1, extended):
    <Solarzellentyp>_<Modalität>[_<Variante>...]_<Bildidentifikator>[_<Zusatz>...].<ext>
Examples:
    23-P09-B1_EL_Cell001.tif
    23_089_A1_EL_LR_Cell001.jpg         variant "LR"
    23_089_A1_EL01_LR_Cell001.jpg       modality "EL" with digit suffix, variant "01_LR"
    23-P09-A2_EL_Cell114_normalized.tif variant "normalized"

The cell type may itself contain underscores. The modality is the rightmost
segment matching a filename code optionally followed by digits; the cell
identifier is the rightmost segment matching "Cell<digits>" (fallback: the
last segment). Segments between modality and cell identifier, plus trailing
segments, form the variant.
"""

import functools
import os
import re
from collections.abc import Callable

IMAGE_EXTENSIONS = (".tif", ".tiff", ".jpg", ".jpeg", ".png")

CELL_PATTERN = re.compile(r"^cell\d+$", re.IGNORECASE)


@functools.lru_cache(maxsize=8)
def _modality_pattern(codes_tuple: tuple[str, ...]) -> re.Pattern[str]:
    """Regex matching a modality segment: a code optionally followed by digits."""
    return re.compile(
        r"^(" + "|".join(re.escape(code) for code in codes_tuple) + r")(\d*)$",
        re.IGNORECASE,
    )


class ImageInfo:
    """Metadata of one image file, parsed from its filename."""

    __slots__ = ("filename", "cell_type", "modality", "cell_id", "variant", "group_key")

    def __init__(
        self,
        filename: str,
        cell_type: str,
        modality: str,
        cell_id: str,
        variant: str | None = None,
    ) -> None:
        """Store the parsed filename metadata of one image."""
        self.filename = filename
        self.cell_type = cell_type
        self.modality = modality
        self.cell_id = cell_id
        self.variant = variant
        self.group_key = (cell_type, cell_id)


def modality_filename_codes(modalities: list[dict]) -> dict[str, str]:
    """Return {lowercase filename code: canonical modality code}.

    Each modality may define an optional 'filename_code' that is used in the
    image file names (specification §3.1); it defaults to the modality code.
    Matching is case-insensitive.
    """
    mapping = {}
    for modality in modalities:
        filename_code = (modality.get("filename_code") or modality["code"]).lower()
        mapping[filename_code] = modality["code"]
    return mapping


def parse_filename(filename: str, filename_codes: dict[str, str]) -> ImageInfo | None:
    """Parse a filename into ImageInfo, or return None if it is invalid.

    filename may be a path relative to images_dir; only the basename is
    parsed, the directory part is preserved in ImageInfo.filename using "/"
    as separator. filename_codes maps lowercase filename codes to canonical
    modality codes (see modality_filename_codes); matching is
    case-insensitive. If several segments match, the rightmost one is treated
    as the modality.
    """
    directory, basename = os.path.split(filename.replace("\\", "/"))
    stem, ext = os.path.splitext(basename)
    if ext.lower() not in IMAGE_EXTENSIONS:
        return None
    parts = stem.split("_")
    if len(parts) < 2 or not parts[-1]:
        return None
    # find the rightmost modality segment (code with optional digit suffix)
    pattern = _modality_pattern(tuple(filename_codes))
    modality_idx = None
    for idx in range(len(parts) - 1, -1, -1):
        match = pattern.match(parts[idx])
        if match:
            modality_idx = idx
            modality = filename_codes[match.group(1).lower()]
            digit_suffix = match.group(2)
            break
    if modality_idx is None:
        return None
    # cell identifier: rightmost "Cell<digits>" segment after the modality,
    # falling back to the last segment
    cell_idx = len(parts) - 1
    for idx in range(len(parts) - 1, modality_idx, -1):
        if CELL_PATTERN.match(parts[idx]):
            cell_idx = idx
            break
    if cell_idx <= modality_idx:
        return None
    cell_type = "_".join(parts[:modality_idx])
    if not cell_type:
        return None
    variant_parts = [digit_suffix] if digit_suffix else []
    variant_parts.extend(parts[modality_idx + 1 : cell_idx])
    variant_parts.extend(parts[cell_idx + 1 :])
    return ImageInfo(
        filename=f"{directory}/{basename}" if directory else basename,
        cell_type=cell_type,
        modality=modality,
        cell_id=parts[cell_idx],
        variant="_".join(variant_parts) or None,
    )


def scan_images(
    images_dir: str, filename_codes: dict[str, str], log: Callable[..., None] | None = None
) -> tuple[dict[str, ImageInfo], dict, list[str]]:
    """Recursively scan images_dir (including subfolders) once.

    Returns (images, groups, unparseable):
      images      {relative path: ImageInfo}  (paths use "/" as separator)
      groups      {group_key: {modality_code: {variant|None: ImageInfo}}}
      unparseable list of relative paths that could not be assigned to a group
    """
    images = {}
    groups = {}
    unparseable = []
    if not os.path.isdir(images_dir):
        return images, groups, unparseable
    paths = []
    for root, dirnames, filenames in os.walk(images_dir):
        dirnames.sort()
        for name in sorted(filenames):
            relative = os.path.relpath(os.path.join(root, name), images_dir)
            if relative.lower().endswith(IMAGE_EXTENSIONS):
                paths.append(relative.replace(os.sep, "/"))
    for path in paths:
        info = parse_filename(path, filename_codes)
        if info is None:
            unparseable.append(path)
            continue
        images[info.filename] = info
        variant_group = groups.setdefault(info.group_key, {}).setdefault(info.modality, {})
        variant_group[info.variant] = info
    if log is not None:
        for path in unparseable:
            log("Ignoring image with unparseable filename or unknown modality: %s", path)
    return images, groups, unparseable


class ImageIndex:
    """Scans the image directory once per directory change, then serves the cache."""

    def __init__(
        self,
        images_dir: str,
        filename_codes: dict[str, str],
        log: Callable[..., None] | None = None,
    ) -> None:
        """Store the image directory, modality codes and an empty cache."""
        self.images_dir = images_dir
        self.filename_codes = dict(filename_codes)
        self.log = log
        self._cache = None
        self._signature = None

    def _dir_signature(self) -> tuple[int, int] | None:
        """Return the recursive file count plus the newest directory mtime.

        Both are computed over the whole tree so that images appearing in
        subfolders invalidate the cache. Only directories are stat'ed: the
        index depends on filenames, and adding/removing/renaming files
        updates their directory's mtime — with a large image set this keeps
        the check cheap enough to run on every request. The count guards
        against filesystems with coarse timestamp resolution, where a
        freshly added file may not change any directory mtime yet.
        """
        try:
            count = 0
            newest = 0
            for root, dirnames, filenames in os.walk(self.images_dir):
                dirnames.sort()
                count += len(filenames)
                newest = max(newest, os.stat(root).st_mtime_ns)
            return (count, newest)
        except OSError:
            return None

    def get(self) -> tuple[dict[str, ImageInfo], dict]:
        """Return the current (images, groups) tuple, rescanning if needed."""
        signature = self._dir_signature()
        if self._cache is None or signature != self._signature:
            images, groups, _ = scan_images(self.images_dir, self.filename_codes, log=self.log)
            self._cache = (images, groups)
            self._signature = signature
        return self._cache
