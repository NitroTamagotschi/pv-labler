"""Round-trip test: label every sample image through the UI, then verify labels.csv."""
import csv
from pathlib import Path

import pytest
from playwright.sync_api import expect

from app import load_config
from images import modality_filename_codes, parse_filename
from labels import modality_to_column

pytestmark = pytest.mark.ui

DEFECT_KEYS = ["crack", "cross", "dark", "corrosion", "discoloration", "delamination"]


def _read_labels(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {row["datename"]: row for row in csv.DictReader(f)}


def _state_str(state):
    """The change-log format for one label state, in config key order."""
    return ", ".join(f"{key}={state.get(key, 0)}" for key in ["good"] + DEFECT_KEYS)


def test_roundtrip_matches_ground_truth(login, live_server, truth):
    """Label every sample image in the All tab, save once via the button,
    then compare labels.csv with the ground truth derived from the schedule."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=all&tab=all")

    # one pass over the All tab: cards never leave the view before saving,
    # so all labels (including multiple defects) are set in a single pass
    for filename, expected in truth.items():
        card = page.locator(f'[data-filename="{filename}"]')
        expect(card).to_be_visible()
        for key in ["good"] + DEFECT_KEYS:
            checkbox = card.locator(f'.label-checkbox[data-key="{key}"]')
            if expected[key] and not checkbox.is_checked():
                checkbox.click()
                expect(checkbox).to_be_checked()

    # save once and wait for the reload (button text is the post-reload state)
    page.locator("#save-btn").click()
    expect(page.locator("#save-btn")).to_have_text("Save")

    # verify the persisted CSV against the ground truth.
    rows = _read_labels(live_server["labels_csv"])
    assert set(rows) == set(truth)

    app_config = load_config()
    filename_codes = modality_filename_codes(app_config["modalities"])
    modality_cols = {
        m["code"]: modality_to_column(m["code"]) for m in app_config["modalities"]
    }
    for filename, expected in truth.items():
        row = rows[filename]
        assert row["Name of labeler"] == "UI Tester", filename
        for key in ["good"] + DEFECT_KEYS:
            assert row[key] == str(expected[key]), f"{filename}: column {key}"
        info = parse_filename(filename, filename_codes)
        assert info is not None, filename
        for code, column in modality_cols.items():
            assert row[column] == ("1" if code == info.modality else "0"), filename


def test_wrong_label_still_persists(login, live_server):
    """Labeling a defect that is not visible on the modality must still save:
    the app persists what the user clicks, it does not second-guess them."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=VI&tab=unclassified")
    # per the visibility table this VI image is a "Good" cell without Dark
    filename = "23-P09-B1_VI_Cell001.tif"
    card = page.locator(f'[data-filename="{filename}"]')
    card.locator('.label-checkbox[data-key="dark"]').click()
    expect(card).to_be_visible()  # pending: stays visible until saved
    page.locator("#save-btn").click()
    expect(card).to_have_count(0)  # only true after the reload
    rows = _read_labels(live_server["labels_csv"])
    assert rows[filename]["dark"] == "1"
    # the same change must be in the change log: exactly one entry, with the
    # labeler, the filename and the full before/after states
    log_lines = Path(live_server["change_log"]).read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    assert log_lines[0].endswith(
        f" | UI Tester | {filename} | "
        f"before: {_state_str({})} | after: {_state_str({'dark': 1})}"
    )