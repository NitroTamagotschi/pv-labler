"""Smoke tests for the Flask routes (app.py) with a small custom config."""

import csv
import json
import re
from pathlib import Path

import numpy as np
import pytest
import tifffile

import app as app_module
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


def test_config_images_dir_is_used(tmp_path):
    """A configured images_dir replaces data/images/; its images are listed."""
    external = tmp_path / "external"
    external.mkdir()
    tifffile.imwrite(str(external / "23-P09-B1_VI_Cell001.tif"), np.zeros((32, 32), dtype=np.uint8))
    app = create_app(
        config=dict(CONFIG, images_dir=str(external)),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
    )
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/login", data={"name": "Max"})
        page = client.get("/main?modality=all&tab=unclassified")
        assert b"23-P09-B1_VI_Cell001" in page.data


def test_config_images_dir_must_exist(tmp_path):
    """A configured images_dir that is missing fails loudly at startup."""
    with pytest.raises(ValueError, match="does not exist"):
        create_app(
            config=dict(CONFIG, images_dir=str(tmp_path / "missing")),
            labels_csv=str(tmp_path / "labels.csv"),
            change_log=str(tmp_path / "change_log.txt"),
            previews_dir=str(tmp_path / "previews"),
        )


def test_config_images_dir_validation():
    """The images_dir key must be a non-empty string when present."""
    for value in (42, True, [], "   "):
        with pytest.raises(ValueError, match="images_dir"):
            _validate_config(dict(CONFIG, images_dir=value))


def test_explicit_images_dir_wins_over_config(tmp_path):
    """The create_app parameter takes precedence over the config entry."""
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    app = create_app(
        config=dict(CONFIG, images_dir=str(tmp_path / "nowhere")),
        images_dir=str(explicit),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
    )
    assert app.config["PV_IMAGES_DIR"] == str(explicit)


def test_gallery_batching_and_api_cards(monkeypatch, tmp_path):
    """/main renders only the first batch; /api/cards serves the rest."""
    monkeypatch.setattr(app_module, "GALLERY_BATCH", 3)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for i in range(1, 6):
        tifffile.imwrite(
            str(images_dir / f"23-P09-B1_VI_Cell{i:03d}.tif"), np.zeros((32, 32), dtype=np.uint8)
        )
    app = create_app(
        config=CONFIG,
        images_dir=str(images_dir),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
    )
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/login", data={"name": "Max"})
        page = client.get("/main?modality=all&tab=unclassified")
        assert page.data.count(b'class="card"') == 3
        assert b'id="gallery-sentinel"' in page.data
        assert b'data-offset="3"' in page.data
        res = client.get("/api/cards?modality=all&tab=unclassified&offset=3")
        data = res.get_json()
        assert data["ok"]
        assert data["count"] == 2
        assert data["remaining"] == 0
        assert data["html"].count('class="card"') == 2
        # past the end there is nothing left
        assert (
            client.get("/api/cards?modality=all&tab=unclassified&offset=5").get_json()["count"] == 0
        )
        # auth and argument validation
        assert app.test_client().get("/api/cards").status_code == 401
        assert client.get("/api/cards?offset=abc").status_code == 400


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
    """Preview windows must be complete pairs with min < max and boolean invert."""
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
    for bad_invert in (1, "yes", [True]):
        with pytest.raises(ValueError):
            _validate_config(
                {**CONFIG, "modalities": [{**modality, "preview_invert": bad_invert}, *others]}
            )
    # invert alone (without a window) and False are both valid
    _validate_config(
        {**CONFIG, "modalities": [{**modality, "preview_invert": True}, *others]}
    )
    _validate_config(
        {**CONFIG, "modalities": [{**modality, "preview_invert": False}, *others]}
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
    assert client.application.config["PV_PREVIEW_WINDOWS"]["EL"] == (1000.0, 20000.0, False)
    # reset removes the entry again
    res = client.post("/api/preview-window", json={"code": "EL", "reset": True})
    assert res.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    el = next(m for m in saved["modalities"] if m["code"] == "EL")
    assert "preview_min" not in el and "preview_max" not in el
    assert "EL" not in client.application.config["PV_PREVIEW_WINDOWS"]


def test_preview_window_endpoint_invert(client):
    """The invert flag updates independently of the window and survives reset."""
    config_path = Path(client.application.config["PV_CONFIG_PATH"])
    client.post("/login", data={"name": "Max"})
    # EL starts with a configured window: invert must keep it
    res = client.post("/api/preview-window", json={"code": "EL", "invert": True})
    assert res.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    el = next(m for m in saved["modalities"] if m["code"] == "EL")
    assert (el["preview_min"], el["preview_max"], el["preview_invert"]) == (
        4000.0,
        30000.0,
        True,
    )
    assert client.application.config["PV_PREVIEW_WINDOWS"]["EL"] == (4000.0, 30000.0, True)
    # a window update must not drop the invert flag
    res = client.post("/api/preview-window", json={"code": "EL", "min": 1000, "max": 20000})
    assert res.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    el = next(m for m in saved["modalities"] if m["code"] == "EL")
    assert el["preview_invert"] is True
    # VI has no window: invert alone yields a (None, None, True) entry and
    # the preview route keeps working with it
    res = client.post("/api/preview-window", json={"code": "VI", "invert": True})
    assert res.status_code == 200
    assert client.application.config["PV_PREVIEW_WINDOWS"]["VI"] == (None, None, True)
    assert client.get("/preview?file=23-P09-B1_VI_Cell001.tif").status_code == 200
    # reset removes the window, the invert flag and the whole entry
    res = client.post("/api/preview-window", json={"code": "EL", "reset": True})
    assert res.status_code == 200
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    el = next(m for m in saved["modalities"] if m["code"] == "EL")
    assert "preview_min" not in el and "preview_max" not in el and "preview_invert" not in el
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
    # invert must be a real JSON boolean
    assert client.post("/api/preview-window", json={"code": "EL", "invert": "true"}).status_code == 400
    assert client.post("/api/preview-window", json={"code": "EL", "invert": 1}).status_code == 400


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


# --- search filter ------------------------------------------------------------


def test_search_filter(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=all&tab=unclassified&q=Cell001")
    assert b"23-P09-B1_VI_Cell001" in page.data
    assert b"23-P09-B1_EL_Cell001" in page.data
    assert b"23-P09-B2_VI_Cell002" not in page.data


def test_search_wildcard_middle(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=all&tab=unclassified&q=23-P09-B1*Cell001")
    assert page.data.count(b'class="card"') == 2
    # implicit trailing star: both B1 files match, B2/B3 do not
    page = client.get("/main?modality=all&tab=unclassified&q=23-P09-B1*")
    assert page.data.count(b'class="card"') == 2
    assert b"23-P09-B2_VI_Cell002" not in page.data


def test_search_case_insensitive(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=all&tab=unclassified&q=cell001")
    assert page.data.count(b'class="card"') == 2
    page = client.get("/main?modality=all&tab=unclassified&q=CELL002")
    assert b"23-P09-B2_VI_Cell002" in page.data
    assert b"23-P09-B1_VI_Cell001" not in page.data


def test_search_combines_with_modality(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=EL&tab=unclassified&q=Cell001")
    assert b"23-P09-B1_EL_Cell001" in page.data
    assert b"23-P09-B1_VI_Cell001" not in page.data


def test_search_combines_with_cell_type(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=VI&tab=unclassified&q=Cell00&cell_type=23-P09-B2")
    assert b"23-P09-B2_VI_Cell002" in page.data
    assert b"23-P09-B1_VI_Cell001" not in page.data


def test_search_reflected_in_tab_counts(client):
    """Tab and cell-type counts follow the search-filtered image set."""
    client.post("/login", data={"name": "Max"})
    client.post(
        "/api/save",
        json={"changes": {"23-P09-B1_EL_Cell001.tif": {"crack": 1}}},
    )
    page = client.get("/main?modality=all&tab=unclassified&q=Cell001")
    assert page.data.count(b'class="card"') == 1
    assert b"23-P09-B1_VI_Cell001" in page.data
    page = client.get("/main?modality=all&tab=all&q=Cell001")
    assert page.data.count(b'class="card"') == 2
    # the cell-type panel counts respect the search (B2 matches nothing)
    assert b'23-P09-B2 <span class="count">0</span>' in page.data


def test_search_infinite_scroll_and_sentinel(monkeypatch, tmp_path):
    """The sentinel query carries the search; /api/cards batches follow it."""
    monkeypatch.setattr(app_module, "GALLERY_BATCH", 2)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for i in range(1, 6):
        tifffile.imwrite(
            str(images_dir / f"23-P09-B1_VI_Cell{i:03d}.tif"), np.zeros((32, 32), dtype=np.uint8)
        )
    app = create_app(
        config=CONFIG,
        images_dir=str(images_dir),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
    )
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/login", data={"name": "Max"})
        page = client.get("/main?modality=VI&tab=unclassified&q=23-P09*")
        assert page.data.count(b'class="card"') == 2
        # the sentinel query carries the percent-encoded search pattern
        assert re.search(rb'data-query="[^"]*q=23-P09%2A[^"]*"', page.data)
        res = client.get("/api/cards?modality=VI&tab=unclassified&q=23-P09*&offset=2")
        data = res.get_json()
        assert data["ok"]
        assert data["count"] == 2
        assert data["remaining"] == 1
        assert data["html"].count('class="card"') == 2
        # the next batch under the same search finishes the set
        data = client.get("/api/cards?modality=VI&tab=unclassified&q=23-P09*&offset=4").get_json()
        assert data["count"] == 1
        assert data["remaining"] == 0
        # a pattern without matches returns an empty batch
        data = client.get(
            "/api/cards?modality=VI&tab=unclassified&q=NoSuch*&offset=0"
        ).get_json()
        assert data["count"] == 0
        assert data["remaining"] == 0


def test_search_empty_or_whitespace_is_no_filter(client):
    client.post("/login", data={"name": "Max"})
    for query in ("q=", "q=%20", "q=%20%20"):
        page = client.get(f"/main?modality=all&tab=unclassified&{query}")
        assert page.data.count(b'class="card"') == 4


def test_search_overlong_is_truncated(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=all&tab=unclassified&q=" + "x" * 250)
    # the rendered input shows the truncated pattern
    assert b'name="q" value="' + b"x" * 200 + b'"' in page.data
    # the truncated pattern matches nothing, so the gallery stays empty
    assert b'class="card"' not in page.data
    assert b'id="gallery-sentinel"' not in page.data


def test_search_ui_preservation(client):
    """The search is kept in forms and tab links and dropped by the ✕ link."""
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=EL&tab=all&cell_type=23-P09-B1&q=Cell001")
    # search input + hidden inputs in the modality form, the type panel and
    # the comparison panel
    assert page.data.count(b'name="q" value="Cell001"') == 4
    # tab links carry the search
    assert (
        b'href="/main?modality=EL&amp;tab=unclassified&amp;cell_type=23-P09-B1&amp;q=Cell001"'
        in page.data
    )
    # the clear link keeps every filter except q
    assert (
        b'class="search-clear" href="/main?modality=EL&amp;tab=all&amp;cell_type=23-P09-B1"'
        in page.data
    )
    # following the clear link renders an empty search input
    cleared = client.get("/main?modality=EL&tab=all&cell_type=23-P09-B1")
    assert b'name="q" value=""' in cleared.data


def test_search_empty_result(client):
    client.post("/login", data={"name": "Max"})
    page = client.get("/main?modality=all&tab=unclassified&q=NoSuchImage")
    assert b'class="card"' not in page.data
    assert b'id="gallery-sentinel"' not in page.data
    assert b"No images match the current filter." in page.data


# --- comparison mode ------------------------------------------------------------

AI_COLUMNS = ["model", "image_path", "file_name", "good", "crack", "uncertain", "visual_status"]
AI_ROOT = "/mnt/other-machine/normalized_images"


def write_source(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def ai_row(filename, good, crack, uncertain="0", note=""):
    return ["gpt-test", f"{AI_ROOT}/{filename}", filename, good, crack, uncertain, note]


@pytest.fixture
def compare_client(client):
    """Logged-in client with stored labels and an AI result CSV next to labels.csv.

    Labels: B1_VI good, B1_EL crack, B2_VI good, B3_VI unlabeled. The AI agrees
    on B1_VI (crack not assessed), sees no crack on B1_EL, flags a crack on B2_VI
    (uncertain) and has one row without a matching image.
    """
    client.post("/login", data={"name": "Max"})
    client.post(
        "/api/save",
        json={
            "changes": {
                "23-P09-B1_VI_Cell001.tif": {"good": 1},
                "23-P09-B1_EL_Cell001.tif": {"crack": 1},
                "23-P09-B2_VI_Cell002.tif": {"good": 1},
            }
        },
    )
    write_source(
        Path(client.application.config["PV_COMPARE_DIR"]) / "ai.csv",
        AI_COLUMNS,
        [
            ai_row("23-P09-B1_VI_Cell001.tif", "1", "", note="clean surface"),
            ai_row("23-P09-B1_EL_Cell001.tif", "1", "0", note="no crack visible"),
            ai_row("23-P09-B2_VI_Cell002.tif", "0", "1", uncertain="1", note="maybe a crack"),
            ai_row("23-P09-B3_VI_Cell003.tif", "1", "0"),
            ai_row("unknown_VI_Cell099.tif", "1", "0"),
        ],
    )
    return client


def tab_counts(html):
    """Return {tab label: count text} of the rendered tab bar."""
    pattern = r'<a class="tab[^"]*"[^>]*>\s*(.*?)\s*<span class="count">([^<]*)</span>'
    return {label: count for label, count in re.findall(pattern, html, re.S)}


def card_names(html):
    return re.findall(r'<article class="card[^"]*" data-filename="([^"]+)"', html)


def compare_trigger(html):
    """Return the markup of the comparison panel's trigger button."""
    return re.search(r'<button[^>]*id="compare-trigger".*?</button>', html, re.S).group(0)


def test_compare_panel_lists_sources(compare_client):
    """The panel offers the CSVs next to labels.csv; unusable files are disabled."""
    data_dir = Path(compare_client.application.config["PV_COMPARE_DIR"])
    write_source(data_dir / "failed.csv", ["filename", "labels", "reason"], [["a", "b", "c"]])
    page = compare_client.get("/main").get_data(as_text=True)
    assert re.search(r"Vergleich:\s+aus", compare_trigger(page))
    assert 'name="src" value="ai.csv"' in page
    assert 'value="labels.csv"' not in page  # the reference itself is never offered
    assert 'name="src" value="failed.csv"' not in page
    assert "failed.csv <span" in page and "keine Labelspalten" in page
    # outside the comparison the normal tabs and cards are unchanged
    assert "Unclassified" in tab_counts(page)
    assert "card-compare" not in page


def test_compare_dir_parameter(tmp_path):
    """An explicit compare_dir replaces the directory of labels.csv."""
    sources = tmp_path / "ai_results"
    sources.mkdir()
    write_source(sources / "run1.csv", ["file_name", "good"], [["x_VI_Cell001.tif", "1"]])
    app = create_app(
        config=CONFIG,
        images_dir=str(tmp_path / "images"),
        labels_csv=str(tmp_path / "labels.csv"),
        change_log=str(tmp_path / "change_log.txt"),
        previews_dir=str(tmp_path / "previews"),
        compare_dir=str(sources),
    )
    with app.test_client() as client:
        client.post("/login", data={"name": "Max"})
        assert b'name="src" value="run1.csv"' in client.get("/main").data


def test_compare_mode_tabs_and_counts(compare_client):
    page = compare_client.get("/main?modality=all&src=ai.csv").get_data(as_text=True)
    assert tab_counts(page) == {
        "Abweichungen": "2",
        "Good ≠": "2",
        "Crack ≠": "2",
        "Übereinstimmung": "1",
        "Unsicher": "1",
        "Nicht vergleichbar": "1",
        "All": "4",
    }
    trigger = compare_trigger(page)
    assert 'title="A = ai"' in trigger
    assert '<span class="src-tag src-0">A</span>' in trigger
    # the differences tab is the default and lists the deviating images
    assert re.search(r'class="tab active"[^>]*>\s*Abweichungen', page)
    assert sorted(card_names(page)) == ["23-P09-B1_EL_Cell001.tif", "23-P09-B2_VI_Cell002.tif"]
    assert page.count("card-compare has-diff") == 2


def test_compare_tabs_filter_images(compare_client):
    def cards(query):
        page = compare_client.get(f"/main?modality=all&src=ai.csv&{query}")
        return sorted(card_names(page.get_data(as_text=True)))

    assert cards("tab=cmp-agree") == ["23-P09-B1_VI_Cell001.tif"]
    assert cards("tab=cmp-uncertain") == ["23-P09-B2_VI_Cell002.tif"]
    # unlabeled in labels.csv: shown, but not compared
    assert cards("tab=cmp-none") == ["23-P09-B3_VI_Cell003.tif"]
    assert len(cards("tab=all")) == 4
    # label tab with direction filter: who set the label
    assert cards("tab=crack") == ["23-P09-B1_EL_Cell001.tif", "23-P09-B2_VI_Cell002.tif"]
    assert cards("tab=crack&only=labeler") == ["23-P09-B1_EL_Cell001.tif"]
    assert cards("tab=crack&only=source") == ["23-P09-B2_VI_Cell002.tif"]
    # an invalid direction or a direction on a non-label tab is ignored
    assert cards("tab=crack&only=sideways") == cards("tab=crack")
    assert cards("tab=cmp-diff&only=labeler") == cards("tab=cmp-diff")
    # a normal-mode tab falls back to the differences tab
    assert cards("tab=unclassified") == cards("tab=cmp-diff")


def test_compare_direction_links(compare_client):
    page = compare_client.get("/main?modality=all&src=ai.csv&tab=crack&only=labeler")
    html = page.get_data(as_text=True)
    assert "Labeler ✓ · A ✗ <span" in html
    assert "Labeler ✗ · A ✓ <span" in html
    assert re.search(r'class="seg-btn active" href="[^"]*only=labeler">Labeler ✓ · A ✗', html)
    # tab links drop the direction, which only belongs to the active label tab
    assert 'href="/main?modality=all&amp;tab=good&amp;src=ai.csv"' in html


def test_compare_card_markup(compare_client):
    html = compare_client.get("/main?modality=all&src=ai.csv&tab=all").get_data(as_text=True)
    card = re.search(
        r'<article[^>]*data-filename="23-P09-B1_EL_Cell001.tif">(.*?)</article>', html, re.S
    ).group(1)
    # the labeler's checkbox stays editable; the source value sits next to it
    assert re.search(r'<div class="label-row diff" data-key="good">', card)
    assert re.search(r'class="src-val src-0 v1 diff"\s+data-v="1"', card)  # AI: good
    assert re.search(r'class="src-val src-0 v0 diff"\s+data-v="0"', card)  # AI: no crack
    assert "no crack visible" in card
    agree = re.search(
        r'<article[^>]*data-filename="23-P09-B1_VI_Cell001.tif">(.*?)</article>', html, re.S
    ).group(1)
    # crack was not assessed: no difference, rendered as "–"
    assert re.search(r'class="src-val src-0 na"\s+data-v=""', agree)
    assert "diff" not in agree
    uncertain = re.search(
        r'<article[^>]*data-filename="23-P09-B2_VI_Cell002.tif">(.*?)</article>', html, re.S
    ).group(1)
    assert 'class="badge-uncertain"' in uncertain


def test_compare_statistics(compare_client):
    html = compare_client.get("/main?modality=all&src=ai.csv").get_data(as_text=True)
    summary = re.search(r"<summary>Statistik(.*?)</summary>", html, re.S).group(1)
    assert "33.3 % übereinstimmend (1 von 3)" in summary
    assert "ohne Label in labels.csv: 1" in html
    assert "unsicher: 1" in html
    assert "1 Zeilen ohne passendes Bild" in html  # unknown_VI_Cell099.tif
    assert "gpt-test" in html  # model column in the legend
    # confusion cells link to the matching gallery view
    assert 'href="/main?modality=all&amp;tab=crack&amp;src=ai.csv&amp;only=labeler">1</a>' in html
    assert 'href="/main?modality=all&amp;tab=crack&amp;src=ai.csv&amp;only=source">1</a>' in html
    # the statistics follow the modality filter: only EL Cell001 is compared
    el = compare_client.get("/main?modality=EL&src=ai.csv").get_data(as_text=True)
    assert "0.0 % übereinstimmend (0 von 1)" in el


def test_compare_rejects_unknown_sources(compare_client):
    """Only files the panel offers can be selected; others fall back to normal mode."""
    data_dir = Path(compare_client.application.config["PV_COMPARE_DIR"])
    write_source(data_dir / "failed.csv", ["filename", "labels", "reason"], [["a", "b", "c"]])
    for src in ("labels.csv", "../config.json", "failed.csv", "missing.csv", ""):
        page = compare_client.get("/main", query_string={"src": src}).get_data(as_text=True)
        assert "Unclassified" in tab_counts(page), src
        assert "Abweichungen" not in page, src


def test_compare_state_is_kept(monkeypatch, compare_client):
    """Forms, links, the sentinel and /api/cards carry the comparison along."""
    monkeypatch.setattr(app_module, "GALLERY_BATCH", 1)
    html = compare_client.get("/main?modality=all&src=ai.csv&tab=all&q=23").get_data(as_text=True)
    # hidden inputs in the modality, search and cell-type forms
    assert html.count('<input type="hidden" name="src" value="ai.csv">') == 3
    assert re.search(r'name="src" value="ai.csv" checked', html)  # panel checkbox
    assert re.search(r'data-query="[^"]*src=ai.csv[^"]*"', html)
    assert 'href="/main?modality=all&amp;tab=cmp-diff&amp;q=23&amp;src=ai.csv"' in html  # tab link
    assert 'class="search-clear" href="/main?modality=all&amp;tab=all&amp;src=ai.csv"' in html
    # ending the comparison keeps the other filters
    assert 'id="compare-clear" href="/main?modality=all&amp;tab=all&amp;q=23"' in html
    data = compare_client.get("/api/cards?modality=all&src=ai.csv&tab=all&q=23&offset=1").get_json()
    assert data["ok"] and data["count"] == 1 and data["remaining"] == 2
    assert "card-compare" in data["html"]
    assert "src-val" in data["html"]


def test_compare_two_sources_and_scope(compare_client):
    data_dir = Path(compare_client.application.config["PV_COMPARE_DIR"])
    columns = ["labeler", "image_path", "good", "crack"]
    # B agrees with labels.csv everywhere
    write_source(
        data_dir / "second.csv",
        columns,
        [
            ["Eva", "23-P09-B1_VI_Cell001.tif", "1", "0"],
            ["Eva", "23-P09-B1_EL_Cell001.tif", "0", "1"],
            ["Eva", "23-P09-B2_VI_Cell002.tif", "1", "0"],
        ],
    )
    write_source(data_dir / "third.csv", columns, [["Udo", "23-P09-B1_VI_Cell001.tif", "1", "0"]])
    base = "/main?modality=all&src=ai.csv&src=second.csv"

    def differences(query):
        page = compare_client.get(base + query).get_data(as_text=True)
        return tab_counts(page)["Abweichungen"]

    html = compare_client.get(base + "&src=third.csv").get_data(as_text=True)
    # at most two sources are used at the same time
    assert html.count('<input type="hidden" name="src"') == 6
    assert '<input type="hidden" name="src" value="third.csv">' not in html
    assert not re.search(r'name="src" value="third.csv" checked', html)
    assert 'title="A = ai&#10;B = second"' in compare_trigger(html)
    assert 'class="src-tag src-1"' in html
    assert "A oder B" in html
    # any source: B1_EL and B2_VI differ from A; B agrees everywhere
    assert differences("") == "2"
    assert differences("&scope=ai.csv") == "2"
    assert differences("&scope=second.csv") == "0"
    assert differences("&scope=nope") == "2"  # unknown scope: any source


def test_compare_mode_saving(compare_client):
    """Labels saved in the comparison mode land in labels.csv; the source stays as is."""
    source = Path(compare_client.application.config["PV_COMPARE_DIR"]) / "ai.csv"
    before = source.read_bytes()
    res = compare_client.post(
        "/api/save", json={"changes": {"23-P09-B1_EL_Cell001.tif": {"good": 1}}}
    )
    assert res.status_code == 200
    html = compare_client.get("/main?modality=all&src=ai.csv").get_data(as_text=True)
    # B1_EL now agrees with the AI (good, no crack)
    assert card_names(html) == ["23-P09-B2_VI_Cell002.tif"]
    assert tab_counts(html)["Übereinstimmung"] == "2"
    assert source.read_bytes() == before
