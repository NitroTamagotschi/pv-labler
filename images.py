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

IMAGE_EXTENSIONS = (".tif", ".tiff", ".jpg", ".jpeg", ".png")

CELL_PATTERN = re.compile(r"^cell\d+$", re.IGNORECASE)


@functools.lru_cache(maxsize=8)
def _modality_pattern(codes_tuple):
    """Regex matching a modality segment: a code optionally followed by digits."""
    return re.compile(
        r"^(" + "|".join(re.escape(code) for code in codes_tuple) + r")(\d*)$",
        re.IGNORECASE,
    )


class ImageInfo:
    """Metadata of one image file, parsed from its filename."""

    __slots__ = ("filename", "cell_type", "modality", "cell_id", "variant", "group_key")

    def __init__(self, filename, cell_type, modality, cell_id, variant=None):
        self.filename = filename
        self.cell_type = cell_type
        self.modality = modality
        self.cell_id = cell_id
        self.variant = variant
        self.group_key = (cell_type, cell_id)


def modality_filename_codes(modalities):
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


def parse_filename(filename, filename_codes):
    """Parse a filename into ImageInfo, or return None if it is invalid.

    filename_codes maps lowercase filename codes to canonical modality codes
    (see modality_filename_codes); matching is case-insensitive. If several
    segments match, the rightmost one is treated as the modality.
    """
    stem, ext = os.path.splitext(filename)
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
        filename=filename,
        cell_type=cell_type,
        modality=modality,
        cell_id=parts[cell_idx],
        variant="_".join(variant_parts) or None,
    )


def scan_images(images_dir, filename_codes, log=None):
    """Scan images_dir once.

    Returns (images, groups, unparseable):
      images      {filename: ImageInfo}
      groups      {group_key: {modality_code: {variant|None: ImageInfo}}}
      unparseable list of image filenames that could not be assigned to a group
    """
    images = {}
    groups = {}
    unparseable = []
    if not os.path.isdir(images_dir):
        return images, groups, unparseable
    with os.scandir(images_dir) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if not entry.is_file():
                continue
            name = entry.name
            if not name.lower().endswith(IMAGE_EXTENSIONS):
                continue
            info = parse_filename(name, filename_codes)
            if info is None:
                unparseable.append(name)
                continue
            images[info.filename] = info
            variant_group = groups.setdefault(info.group_key, {}).setdefault(
                info.modality, {}
            )
            variant_group[info.variant] = info
    if log is not None:
        for name in unparseable:
            log("Ignoring image with unparseable filename or unknown modality: %s", name)
    return images, groups, unparseable


class ImageIndex:
    """Scans the image directory once per directory change, then serves the cache."""

    def __init__(self, images_dir, filename_codes, log=None):
        self.images_dir = images_dir
        self.filename_codes = dict(filename_codes)
        self.log = log
        self._cache = None
        self._signature = None

    def _dir_signature(self):
        """Directory mtime plus entry count.

        The entry count guards against filesystems with coarse timestamp
        resolution, where a freshly added file may not change the directory
        mtime yet.
        """
        try:
            mtime = os.stat(self.images_dir).st_mtime_ns
            count = sum(1 for _ in os.scandir(self.images_dir))
            return (mtime, count)
        except OSError:
            return None

    def get(self):
        """Return the current (images, groups) tuple, rescanning if needed."""
        signature = self._dir_signature()
        if self._cache is None or signature != self._signature:
            images, groups, _ = scan_images(
                self.images_dir, self.filename_codes, log=self.log
            )
            self._cache = (images, groups)
            self._signature = signature
        return self._cache
