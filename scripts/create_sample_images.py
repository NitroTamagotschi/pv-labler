"""Generate synthetic sample TIFF images into data/images/ for manual testing.

Creates three cell types x three cells in the modalities VI, EL and UVF,
deliberately leaving one modality out of one group so the "Image missing"
placeholder of the group pop-up can be tested. Also writes one image with an
unparseable filename to demonstrate the §10.4 handling, and a variant example
in the format 23_089_A1_EL_LR_Cell00x.jpg.
"""
import os

import numpy as np
import tifffile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.normpath(os.path.join(HERE, "..", "data", "images"))

SIZE = 384


def make_cell(modality, seed):
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
    # crack-like dark lines on some cells
    if seed % 3 == 0:
        for _ in range(rng.integers(1, 3)):
            x0, y0 = rng.uniform(0.2, 0.8, 2) * SIZE
            angle = rng.uniform(0, np.pi)
            length = rng.uniform(0.25, 0.5) * SIZE
            for i in range(int(length)):
                x = int(x0 + np.cos(angle) * i)
                y = int(y0 + np.sin(angle) * i)
                img[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = 0.02
    return (np.clip(img, 0.0, 1.0) * 65535).astype(np.uint16)


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    modalities = ["VI", "EL", "UV"]  # filename codes from config.json (UVF -> UV)
    cell_types = ["23-P09-B1", "23-P09-B2", "24-Q01-A3"]
    seed = 0
    for cell_type in cell_types:
        for cell in range(1, 4):
            cell_id = f"Cell{cell:03d}"
            for modality in modalities:
                # deliberately leave one modality out of one group
                if cell_type == cell_types[1] and cell == 2 and modality == "UV":
                    continue
                seed += 1
                name = f"{cell_type}_{modality}_{cell_id}.tif"
                tifffile.imwrite(os.path.join(IMAGES_DIR, name), make_cell(modality, seed))
                print(f"wrote {name}")
    # variant example: EL plus an EL_LR JPG variant of the same cell
    for cell in range(1, 3):
        cell_id = f"Cell{cell:03d}"
        seed += 1
        data = make_cell("EL", seed)
        name = f"23_089_A1_EL_{cell_id}.tif"
        tifffile.imwrite(os.path.join(IMAGES_DIR, name), data)
        print(f"wrote {name}")
        name_lr = f"23_089_A1_EL_LR_{cell_id}.jpg"
        Image.fromarray((data / 256).astype(np.uint8)).save(
            os.path.join(IMAGES_DIR, name_lr), quality=90
        )
        print(f"wrote {name_lr}")
    # one image with an unparseable filename, to demonstrate the §10.4 handling
    bad = os.path.join(IMAGES_DIR, "badname.tif")
    tifffile.imwrite(bad, np.zeros((64, 64), dtype=np.uint8))
    print("wrote badname.tif (unparseable on purpose)")


if __name__ == "__main__":
    main()
