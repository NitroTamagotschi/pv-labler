"""Scanning, parsing and grouping of the image files in data/images/.

Filename format (specification.md §4.1):
    <Solarzellentyp>_<Modalität>_<Bildidentifikator>.tif
The cell type may itself contain underscores, so everything before the last
two underscore-separated segments is treated as the cell type.
"""
import os
import re

IMAGE_EXTENSIONS = (".tif", ".tiff")

FILENAME_PATTERN = re.compile(
    r"^(?P<type>.+)_(?P<modality>[^_]+)_(?P<cell>[^_]+)\.(?:tif|tiff)$",
    re.IGNORECASE,
)


class ImageInfo:
    """Metadata of one image file, parsed from its filename."""

    __slots__ = ("filename", "cell_type", "modality", "cell_id", "group_key")

    def __init__(self, filename, cell_type, modality, cell_id):
        self.filename = filename
        self.cell_type = cell_type
        self.modality = modality
        self.cell_id = cell_id
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
    (see modality_filename_codes); matching is case-insensitive.
    """
    match = FILENAME_PATTERN.match(filename)
    if match is None:
        return None
    configured = filename_codes.get(match.group("modality").lower())
    if configured is None:
        return None
    return ImageInfo(
        filename=filename,
        cell_type=match.group("type"),
        modality=configured,
        cell_id=match.group("cell"),
    )


def scan_images(images_dir, filename_codes, log=None):
    """Scan images_dir once.

    Returns (images, groups, unparseable):
      images      {filename: ImageInfo}
      groups      {group_key: {modality_code: ImageInfo}}
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
            groups.setdefault(info.group_key, {})[info.modality] = info
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
        try:
            return os.stat(self.images_dir).st_mtime_ns
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
