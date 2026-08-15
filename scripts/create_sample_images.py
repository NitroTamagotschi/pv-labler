"""Generate synthetic sample images into data/images/ for manual testing.

Defect labels are drawn as text into the images. A defect only appears in
the modalities in which it is visible (per the project's defect-visibility
table): crack/cross on EL and UVF, dark on EL, corrosion on VI and EL,
discoloration on VI and UVF, delamination on VI.

Creates three cell types x three cells in the modalities VI, EL and UVF,
deliberately leaving one modality out of one group so the "Image missing"
placeholder of the group pop-up can be tested. Also writes one image with an
unparseable filename to demonstrate the §10.4 handling, a variant example
in the format 23_089_A1_EL_LR_Cell00x.jpg, and one full-coverage image per
modality (TEST_ALL) in which every defect type appears regardless of the
visibility table.

`image_plan()` and `ground_truth_labels()` are the single source of truth for
what gets generated; the Playwright UI tests use them to verify the labeling
round trip.
"""
import os

import numpy as np
import tifffile
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.normpath(os.path.join(HERE, "..", "data", "images"))

SIZE = 384
MODALITIES = ["VI", "EL", "UV"]  # filename codes from config.json (UVF -> UV)

# Defect visibility per modality (filename codes; UV = the UVF modality).
# From the user's table:
#   Zellriss -> crack (EL, UVF), Kreuzriss -> cross (EL, UVF),
#   Inaktiver Bereich -> dark (EL), Korrosion -> corrosion (VI, EL),
#   Verfaerbung -> discoloration (VI, UVF), Schichtentrennung -> delamination (VI)
DEFECT_VISIBILITY = {
    "crack": ["EL", "UV"],
    "cross": ["EL", "UV"],
    "dark": ["EL"],
    "corrosion": ["VI", "EL"],
    "discoloration": ["VI", "UV"],
    "delamination": ["VI"],
}

# Deterministic defect combination per cell; empty means a "Good" cell.
CELL_DEFECTS = [
    ["crack"],
    ["cross"],
    ["dark"],
    ["corrosion"],
    ["discoloration"],
    ["delamination"],
    ["crack", "corrosion"],
    ["cross", "discoloration"],
    [],
    ["crack", "cross", "dark"],
    ["delamination", "corrosion"],
    ["discoloration", "crack"],
]


def load_font(size):
    try:
        windows_fonts = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
        return ImageFont.truetype(os.path.join(windows_fonts, "arial.ttf"), size)
    except OSError:
        return ImageFont.load_default()


def draw_defects(img, defect_names):
    """Draw the visible defect names as text into the uint16 image."""
    if not defect_names:
        return img
    arr8 = (img / 256).astype(np.uint8)
    canvas = Image.fromarray(arr8)
    draw = ImageDraw.Draw(canvas)
    font = load_font(28)
    margin, gap = 10, 14
    y = margin
    for name in defect_names:
        bbox = draw.textbbox((0, 0), name, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([margin - 4, y - 4, margin + w + 4, y + h + 4], fill=30)
        draw.text((margin, y), name, fill=255, font=font)
        y += h + gap
    return (np.asarray(canvas).astype(np.uint16) * 257)


def make_cell(modality, seed, defect_names):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    radius = np.hypot(xx - SIZE / 2, yy - SIZE / 2)
    # round cell body on a darker background
    base = np.clip(1.0 - radius / (SIZE * 0.62), 0.0, 1.0)
    texture = rng.normal(0.5, 0.08, (SIZE, SIZE))
    if modality == "EL":
        img = 0.06 + 0.35 * base * texture
    elif modality == "UV":
        img = 0.02 + 0.60 * base * texture
    else:  # VI
        img = 0.05 + 0.90 * base * texture
    img = (np.clip(img, 0.0, 1.0) * 65535).astype(np.uint16)
    return draw_defects(img, defect_names)


def visible_defect_keys(defect_keys, modality):
    """Defect keys that are visible in the given modality."""
    return [key for key in defect_keys if modality in DEFECT_VISIBILITY[key]]


def display_names(defect_keys):
    """Display names matching the label checkboxes in the UI."""
    return [key.capitalize() for key in defect_keys]


def image_plan():
    """Yield (filename, modality, visible_defect_keys) for every sample image.

    Single source of truth for the generated image set; generation and the
    UI test ground truth both use it.
    """
    cell_types = ["23-P09-B1", "23-P09-B2", "24-Q01-A3"]
    cell_counter = 0
    for cell_type in cell_types:
        for cell in range(1, 4):
            cell_id = f"Cell{cell:03d}"
            defects = CELL_DEFECTS[cell_counter % len(CELL_DEFECTS)]
            cell_counter += 1
            for modality in MODALITIES:
                # deliberately leave one modality out of one group
                if cell_type == "23-P09-B2" and cell_id == "Cell002" and modality == "UV":
                    continue
                visible = visible_defect_keys(defects, modality)
                yield f"{cell_type}_{modality}_{cell_id}.tif", modality, visible
    # variant example: EL plus an EL_LR JPG variant with the same content
    for cell in range(1, 3):
        cell_id = f"Cell{cell:03d}"
        defects = CELL_DEFECTS[cell_counter % len(CELL_DEFECTS)]
        cell_counter += 1
        visible = visible_defect_keys(defects, "EL")
        yield f"23_089_A1_EL_{cell_id}.tif", "EL", visible
        yield f"23_089_A1_EL_LR_{cell_id}.jpg", "EL", visible
    # full-coverage images: every defect type regardless of the visibility table
    for modality in MODALITIES:
        yield f"TEST_ALL_{modality}_Cell001.tif", modality, sorted(DEFECT_VISIBILITY)


def build_sample_images(images_dir):
    """Write all sample images from image_plan() into images_dir.

    Returns [(filename, visible_defect_keys)] for coverage checks.
    """
    os.makedirs(images_dir, exist_ok=True)
    written = []
    seed = 0
    for filename, modality, visible in image_plan():
        seed += 1
        image = make_cell(modality, seed, display_names(visible))
        if filename.lower().endswith((".tif", ".tiff")):
            tifffile.imwrite(os.path.join(images_dir, filename), image)
        else:
            Image.fromarray((image / 256).astype(np.uint8)).save(
                os.path.join(images_dir, filename), quality=90
            )
        written.append((filename, visible))
    return written


def ground_truth_labels():
    """{filename: {label_key: 0|1}} — the labels a correct labeling session
    of the generated images would produce (good=1 for images without any
    visible defect, otherwise the visible defects are set)."""
    labels = {}
    for filename, modality, visible in image_plan():
        row = {key: 0 for key in DEFECT_VISIBILITY}
        if visible:
            for key in visible:
                row[key] = 1
            row["good"] = 0
        else:
            row["good"] = 1
        labels[filename] = row
    return labels


def main():
    written = build_sample_images(IMAGES_DIR)
    for filename, visible in written:
        print(f"wrote {filename} ({', '.join(display_names(visible)) or 'good'})")

    # sanity checks: every defect type must actually be drawn somewhere, and
    # some images must show more than one defect
    drawn_keys = {key for _, visible in written for key in visible}
    multi_image_count = sum(1 for _, visible in written if len(visible) > 1)
    missing = set(DEFECT_VISIBILITY) - drawn_keys
    if missing:
        raise SystemExit(f"schedule does not cover defect(s): {sorted(missing)}")
    if multi_image_count < 2:
        raise SystemExit("too few images with multiple defect types")
    print(
        f"coverage check passed: all {len(DEFECT_VISIBILITY)} defect types drawn, "
        f"{multi_image_count} images with multiple defects"
    )

    # one image with an unparseable filename, to demonstrate the §10.4 handling
    bad = os.path.join(IMAGES_DIR, "badname.tif")
    tifffile.imwrite(bad, np.zeros((64, 64), dtype=np.uint8))
    print("wrote badname.tif (unparseable on purpose)")


if __name__ == "__main__":
    main()