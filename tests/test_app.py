"""Smoke tests for the Flask routes (app.py) with a small custom config."""
import numpy as np
import pytest
import tifffile

from app import create_app

CONFIG = {
    "modalities": [
        {"code": "VI", "display_name": "VI"},
        {"code": "EL", "display_name": "EL"},
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


def test_save_api_and_good_exclusivity(client):
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
    page = client.get(
        "/main?modality=VI&tab=unclassified&cell_type=23-P09-B1&cell_type=23-P09-B3"
    )
    assert b"23-P09-B1_VI_Cell001" in page.data
    assert b"23-P09-B3_VI_Cell003" in page.data
    assert b"23-P09-B2_VI_Cell002" not in page.data


def test_save_api_rejects_unknown_input(client):
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
