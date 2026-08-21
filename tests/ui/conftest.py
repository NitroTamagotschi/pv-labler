"""Fixtures for the Playwright UI tests: a live app instance with sample images."""

import importlib.util
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]


def load_sample_script():
    """Load the sample-image generator script as a module."""
    spec = importlib.util.spec_from_file_location(
        "create_sample_images", ROOT / "scripts" / "create_sample_images.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def sample_script():
    """Return the sample-image generator script loaded as a module."""
    return load_sample_script()


def _bootstrap(tmp_path, sample_script):
    """Start the app on a random port with freshly generated sample images."""
    from app import create_app, load_config

    images_dir = tmp_path / "images"
    previews_dir = tmp_path / "previews"
    data_dir = tmp_path / "data"
    sample_script.build_sample_images(
        str(images_dir), ground_truth_csv=str(data_dir / "ground_truth.csv")
    )

    app = create_app(
        config=load_config(),
        images_dir=str(images_dir),
        labels_csv=str(data_dir / "labels.csv"),
        change_log=str(data_dir / "change_log.txt"),
        previews_dir=str(previews_dir),
        config_path=str(data_dir / "config.json"),
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_ready(base_url)
    except Exception:
        server.shutdown()
        raise
    return {
        "server": server,
        "thread": thread,
        "base_url": base_url,
        "labels_csv": data_dir / "labels.csv",
        "change_log": data_dir / "change_log.txt",
        "config_path": data_dir / "config.json",
        "ground_truth_csv": data_dir / "ground_truth.csv",
    }


@pytest.fixture
def live_server(tmp_path, sample_script):
    """Start the app on a random port with freshly generated sample images."""
    info = _bootstrap(tmp_path, sample_script)
    yield info
    info["server"].shutdown()
    info["thread"].join(timeout=5)


@pytest.fixture
def scrolling_live_server(tmp_path, sample_script, monkeypatch):
    """live_server with a small card batch so infinite scrolling is exercised."""
    import app as app_module

    monkeypatch.setattr(app_module, "GALLERY_BATCH", 12)
    info = _bootstrap(tmp_path, sample_script)
    yield info
    info["server"].shutdown()
    info["thread"].join(timeout=5)


def _wait_until_ready(base_url, timeout=15):
    """Poll base_url until the server answers with HTTP 200."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(base_url + "/", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start in time")
        time.sleep(0.1)


@pytest.fixture
def login(page, live_server):
    """Log into the app with the name "UI Tester" and return the page."""
    page.goto(live_server["base_url"] + "/")
    page.fill("#name", "UI Tester")
    page.click("button[type=submit]")
    page.wait_for_url("**/main*")
    return page


@pytest.fixture
def save_and_wait(page):
    """Click the Save button and wait until the reloaded page shows a clean button."""

    def _save():
        page.locator("#save-btn").click()
        expect(page.locator("#save-btn")).to_have_text("Save")

    return _save
