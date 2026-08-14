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


def test_label_api_and_good_exclusivity(client):
    client.post("/login", data={"name": "Max"})
    res = client.post(
        "/api/label",
        json={"filename": "23-P09-B1_EL_Cell001.tif", "key": "crack", "value": True},
    )
    assert res.status_code == 200
    state = res.get_json()["state"]
    assert state["crack"] == 1 and state["good"] == 0

    # setting Good must clear the defect
    res = client.post(
        "/api/label",
        json={"filename": "23-P09-B1_EL_Cell001.tif", "key": "good", "value": True},
    )
    state = res.get_json()["state"]
    assert state["good"] == 1 and state["crack"] == 0


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


def test_label_api_rejects_unknown_input(client):
    client.post("/login", data={"name": "Max"})
    assert (
        client.post(
            "/api/label",
            json={"filename": "nope.tif", "key": "crack", "value": True},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/label",
            json={"filename": "23-P09-B1_EL_Cell001.tif", "key": "nope", "value": True},
        ).status_code
        == 400
    )


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
