"""Round-trip test: label every sample image through the UI, then verify labels.csv."""

import csv
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

DEFECT_KEYS = ["crack", "cross", "dark", "corrosion", "discoloration", "delamination"]
LABEL_KEYS = ["good"] + DEFECT_KEYS


def _read_labels(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {row["datename"]: row for row in csv.DictReader(f)}


def _read_ground_truth(path):
    """Read ground_truth.csv into {filename: row} with label keys as ints."""
    with open(path, newline="", encoding="utf-8") as f:
        truth = {}
        for row in csv.DictReader(f):
            for key in LABEL_KEYS:
                row[key] = int(row[key])
            truth[row["datename"]] = row
        return truth


def _state_str(state):
    """Return the change-log format for one label state, in config key order."""
    return ", ".join(f"{key}={state.get(key, 0)}" for key in ["good"] + DEFECT_KEYS)


def test_roundtrip_matches_ground_truth(login, live_server, save_and_wait):
    """Label every sample image in the All tab and verify the saved CSV.

    The reference is the ground_truth.csv file written by the sample
    generator: all images are labeled according to it in a single pass,
    saved once via the button, then labels.csv is compared column by
    column with the reference.
    """
    page = login
    base = live_server["base_url"]
    truth = _read_ground_truth(live_server["ground_truth_csv"])
    page.goto(base + "/main?modality=all&tab=all")

    # one pass over the All tab: cards never leave the view before saving,
    # so all labels (including multiple defects) are set in a single pass
    for filename, expected in truth.items():
        card = page.locator(f'[data-filename="{filename}"]')
        expect(card).to_be_visible()
        for key in LABEL_KEYS:
            checkbox = card.locator(f'.label-checkbox[data-key="{key}"]')
            if expected[key] and not checkbox.is_checked():
                checkbox.click()
                expect(checkbox).to_be_checked()

    save_and_wait()

    # verify the persisted CSV against the ground truth file: same images,
    # identical label and modality columns (only the session metadata
    # date/time/labeler differs by design)
    rows = _read_labels(live_server["labels_csv"])
    assert set(rows) == set(truth)
    for filename, expected in truth.items():
        row = rows[filename]
        assert row["Name of labeler"] == "UI Tester", filename
        for key in LABEL_KEYS + ["uv", "vi", "el"]:
            assert row[key] == str(expected[key]), f"{filename}: column {key}"

    # every tab shows exactly the images whose ground truth has that label
    for key in LABEL_KEYS:
        page.goto(f"{base}/main?modality=all&tab={key}")
        visible = page.locator(".card").evaluate_all("els => els.map(e => e.dataset.filename)")
        assert set(visible) == {f for f, e in truth.items() if e[key]}, key
    page.goto(base + "/main?modality=all&tab=unclassified")
    expect(page.locator(".card")).to_have_count(0)

    # a second save cycle must update rows in place without touching others
    page.goto(base + "/main?modality=all&tab=all")
    multi = next(f for f, e in truth.items() if sum(bool(e[k]) for k in DEFECT_KEYS) > 1)
    extra_key = next(k for k in DEFECT_KEYS if truth[multi][k])
    checkbox = page.locator(f'[data-filename="{multi}"] .label-checkbox[data-key="{extra_key}"]')
    checkbox.click()  # uncheck one stored defect
    expect(checkbox).not_to_be_checked()
    save_and_wait()
    rows = _read_labels(live_server["labels_csv"])
    assert rows[multi][extra_key] == "0"
    assert len(rows) == len(truth)  # no row lost, no row added
    checkbox.click()  # restore the ground truth
    save_and_wait()
    assert _read_labels(live_server["labels_csv"])[multi][extra_key] == "1"


def test_wrong_label_still_persists(login, live_server, save_and_wait):
    """Verify that a not-visible defect label is still persisted after Save.

    The app persists what the user clicks, it does not second-guess them.
    """
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=VI&tab=unclassified")
    # per the visibility table this VI image is a "Good" cell without Dark
    filename = "TEST_23-P09-B1_VI_Cell001.tif"
    card = page.locator(f'[data-filename="{filename}"]')
    card.locator('.label-checkbox[data-key="dark"]').click()
    expect(card).to_be_visible()  # pending: stays visible until saved
    save_and_wait()
    expect(card).to_have_count(0)  # only true after the reload
    rows = _read_labels(live_server["labels_csv"])
    assert rows[filename]["dark"] == "1"
    # the same change must be in the change log: exactly one entry, with the
    # labeler, the filename and the full before/after states
    log_lines = Path(live_server["change_log"]).read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    assert log_lines[0].endswith(
        f" | UI Tester | {filename} | before: {_state_str({})} | after: {_state_str({'dark': 1})}"
    )
