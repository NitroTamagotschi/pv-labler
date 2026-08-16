"""Smoke tests for the Flask routes (app.py) with a small custom config."""

import json
from pathlib import Path

import numpy as np
import pytest
import tifffile

from app import _validate_config, create_app

CONFIG = {
    "modal_max_width": 1400,
    "modal_max_height": 800,
    "modalities": [
        {"code": "VI", "display_name": "VI"},
        {"code": "EL", "display_name": "EL", "preview_min": 4000, "preview_max": 30000},
    ],
    "labels": {
        "good": {"key": "good", "display_name": "Good"},
        "defects": [{"key": "crack", "display_name": "Crack"}],
    },
}


@pytest.fixture
def client(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for name in (
        "23-P09-B1_VI_Cell001.tif",
        "23-P09-B1_EL_Cell001.tif",
        "23-P09-B2_VI_Cell002.tif",
        "23-P09-B3_VI_Cell003.tif",
    ):
        tifffile.imwrite(str(images_dir / name), np.zeros((32, 32), dtype=np.uint8))
    app = create_app(
        config=CONFIG,
        images_dir=str(images_dir),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
        config_path=str(tmp_path / "config.json"),
    )
    app.config["TESTING"] = True
    return app.test_client()


def test_login_required(client):
    assert client.get("/main").status_code == 302
    assert client.get("/").status_code == 200
    # empty name is rejected
    assert client.post("/login", data={"name": "  "}).status_code == 400


def test_login_and_main_window(client):
    response = client.post("/login", data={"name": "Max"})
    assert response.status_code == 302
    page = client.get("/main")
    assert page.status_code == 200
    assert b"Unclassified" in page.data
    assert b"Cell001" in page.data
    assert b"Crack" in page.data
    assert b"--modal-max-width: 1400px" in page.data  # from config.json
    assert b"--modal-max-height: 800px" in page.data
    assert b"window-filter-panel" in page.data
    assert b"&amp;v=" in page.data  # preview URLs carry a window cache-busting signature


def test_modal_size_validation_and_default(tmp_path):
    """Modal size keys must be integers >= 200; absent they fall back to 1100px/90vh."""
    for key in ("modal_max_width", "modal_max_height"):
        with pytest.raises(ValueError):
            _validate_config(dict(CONFIG, **{key: "wide"}))
        with pytest.raises(ValueError):
            _validate_config(dict(CONFIG, **{key: 100}))
    app = create_app(
        config={k: v for k, v in CONFIG.items() if "modal_max" not in k},
        images_dir=str(tmp_path / "images"),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
    )
    with app.test_client() as client:
        client.post("/login", data={"name": "Max"})
        page = client.get("/main").data
        assert b"--modal-max-width: 1100px" in page
        assert b"--modal-max-height: 90vh" in page


def test_save_api_and_good_exclusivity(client):
    """Saving Good clears a previously stored defect (cascade from stored state)."""
    client.post("/login", data={"name": "Max"})
    res = client.post(
        "/api/save",
        json={"changes": {"23-P09-B1_EL_Cell001.tif": {"crack": 1}}},
    )
    assert res.status_code == 200
    states = res.get_json()["states"]
    assert states["23-P09-B1_EL_Cell001.tif"]["crack"] == 1
    assert states["23-P09-B1_EL_Cell001.tif"]["good"] == 0

    # saving Good must clear the stored defect (cascade from stored state)
    res = client.post(
        "/api/save",
        json={"changes": {"23-P09-B1_EL_Cell001.tif": {"good": 1}}},
    )
    states = res.get_json()["states"]
    assert states["23-P09-B1_EL_Cell001.tif"]["good"] == 1
    assert states["23-P09-B1_EL_Cell001.tif"]["crack"] == 0


def test_modality_all_shows_every_modality(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=all&tab=unclassified")
    assert b"23-P09-B1_VI_Cell001" in page.data
    assert b"23-P09-B1_EL_Cell001" in page.data
    # single modality view filters the other one out
    only_el = client.get("/main?modality=EL&tab=unclassified")
    assert b"23-P09-B1_EL_Cell001" in only_el.data
    assert b"23-P09-B1_VI_Cell001" not in only_el.data


def test_cell_type_filter(client):
    client.post("/login", data={"name": "Max"})
    all_page = client.get("/main?modality=VI&tab=unclassified")
    assert b"23-P09-B1_VI_Cell001" in all_page.data
    assert b"23-P09-B2_VI_Cell002" in all_page.data
    filtered = client.get("/main?modality=VI&tab=unclassified&cell_type=23-P09-B2")
    assert b"23-P09-B2_VI_Cell002" in filtered.data
    assert b"23-P09-B1_VI_Cell001" not in filtered.data


def test_cell_type_multi_filter(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=VI&tab=unclassified&cell_type=23-P09-B1&cell_type=23-P09-B3")
    assert b"23-P09-B1_VI_Cell001" in page.data
    assert b"23-P09-B3_VI_Cell003" in page.data
    assert b"23-P09-B2_VI_Cell002" not in page.data


def test_save_api_rejects_unknown_input(client):
    """Unknown files, unknown keys, conflicts and empty batches are rejected."""
    client.post("/login", data={"name": "Max"})
    assert (
        client.post(
            "/api/save",
            json={"changes": {"nope.tif": {"crack": 1}}},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/save",
            json={"changes": {"23-P09-B1_EL_Cell001.tif": {"nope": 1}}},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/save",
            json={"changes": {"23-P09-B1_EL_Cell001.tif": {"good": 1, "crack": 1}}},
        ).status_code
        == 400
    )
    assert client.post("/api/save", json={"changes": {}}).status_code == 400
    assert client.post("/api/save", json={}).status_code == 400


def test_all_tab_shows_labeled_and_unlabeled(client):
    """The All tab lists every image, while Unclassified only lists unlabeled ones."""
    client.post("/login", data={"name": "Max"})
    client.post(
        "/api/save",
        json={"changes": {"23-P09-B1_EL_Cell001.tif": {"crack": 1}}},
    )
    all_page = client.get("/main?modality=EL&tab=all")
    assert b"23-P09-B1_EL_Cell001.tif" in all_page.data
    unclassified = client.get("/main?modality=EL&tab=unclassified")
    assert b"23-P09-B1_EL_Cell001.tif" not in unclassified.data


def test_group_api(client):
    client.post("/login", data={"name": "Max"})
    data = client.get("/api/group/23-P09-B1_EL_Cell001.tif").get_json()
    assert data["ok"]
    assert data["group_key"] == "23-P09-B1_Cell001"
    members = {m["code"]: m for m in data["members"]}
    assert set(members) == {"VI", "EL"}
    assert members["EL"]["filename"] == "23-P09-B1_EL_Cell001.tif"
    assert members["EL"]["preview_url"] is not None


def test_preview_route(client):
    client.post("/login", data={"name": "Max"})
    res = client.get("/preview?file=23-P09-B1_VI_Cell001.tif")
    assert res.status_code == 200
    assert res.mimetype == "image/jpeg"
    # EL has a configured preview window; the request must still work
    assert client.get("/preview?file=23-P09-B1_EL_Cell001.tif").status_code == 200


def test_preview_window_validation():
    """Preview windows must be complete pairs with min < max."""
    modality = CONFIG["modalities"][0]
    others = CONFIG["modalities"][1:]
    with pytest.raises(ValueError):
        _validate_config({**CONFIG, "modalities": [{**modality, "preview_min": 1000}, *others]})
    with pytest.raises(ValueError):
        _validate_config(
            {
                **CONFIG,
                "modalities": [
                    {**modality, "preview_min": 5000, "preview_max": 5000},
                    *others,
                ],
            }
        )


def test_preview_window_endpoint(client):
    """The panel endpoint persists the window to config.json and swaps it in."""
    config_path = Path(client.application.config["PV_CONFIG_PATH"])
    client.post("/login", data={"name": "Max"})
    res = client.post("/api/preview-window", json={"code": "EL", "min": 1000, "max": 20000})
    assert res.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    el = next(m for m in saved["modalities"] if m["code"] == "EL")
    assert (el["preview_min"], el["preview_max"]) == (1000.0, 20000.0)
    assert client.application.config["PV_PREVIEW_WINDOWS"]["EL"] == (1000.0, 20000.0)
    # reset removes the entry again
    res = client.post("/api/preview-window", json={"code": "EL", "reset": True})
    assert res.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    el = next(m for m in saved["modalities"] if m["code"] == "EL")
    assert "preview_min" not in el and "preview_max" not in el
    assert "EL" not in client.application.config["PV_PREVIEW_WINDOWS"]


def test_preview_window_rejects_invalid_input(client):
    """The endpoint requires a login and a valid modality/min-max pair."""
    assert client.post("/api/preview-window", json={}).status_code == 401
    client.post("/login", data={"name": "Max"})
    assert (
        client.post("/api/preview-window", json={"code": "nope", "min": 0, "max": 10}).status_code
        == 400
    )
    assert (
        client.post("/api/preview-window", json={"code": "EL", "min": 10, "max": 10}).status_code
        == 400
    )
    assert client.post("/api/preview-window", json={"code": "EL"}).status_code == 400


def test_original_route(client):
    """The original TIFF is served byte-identical; unknown paths get a 404."""
    images_dir = Path(client.application.config["PV_IMAGES_DIR"])
    source = images_dir / "23-P09-B1_EL_Cell001.tif"
    assert source.exists()
    assert client.get("/api/original/23-P09-B1_EL_Cell001.tif").status_code == 401
    client.post("/login", data={"name": "Max"})
    res = client.get("/api/original/23-P09-B1_EL_Cell001.tif")
    assert res.status_code == 200
    assert res.mimetype == "image/tiff"
    assert res.data == source.read_bytes()
    assert client.get("/api/original/nope.tif").status_code == 404
    assert client.get("/api/original/..evil.tif").status_code == 404
