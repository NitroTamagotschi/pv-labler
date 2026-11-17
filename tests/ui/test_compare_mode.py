"""Browser tests for the comparison mode (labels.csv vs. a source CSV).

The sample generator writes ground_truth.csv in the labels.csv schema next to
labels.csv, so it is offered as comparison source out of the box.
"""

import re
import shutil

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

DEFECT_KEYS = ["crack", "cross", "dark", "corrosion", "discoloration", "delamination"]


def test_compare_panel_switches_mode(login, live_server):
    """Selecting a source in the panel turns the comparison on; the link ends it."""
    page = login
    page.goto(live_server["base_url"] + "/main?modality=EL&tab=unclassified")
    expect(page.locator("#compare-trigger")).to_contain_text("Vergleich: aus")
    page.locator("#compare-trigger").click()
    panel = page.locator("#compare-panel")
    expect(panel).to_be_visible()
    panel.locator('input[value="ground_truth.csv"]').check()
    panel.locator(".apply-btn").click()
    page.wait_for_url("**src=ground_truth.csv*")
    expect(page.locator("#compare-trigger .src-tag")).to_have_text("A")
    expect(page.locator("#compare-trigger")).to_have_attribute("title", "A = ground_truth")
    expect(page.locator(".compare-bar")).to_contain_text("GroundTruth")
    # the normal-mode tab falls back to the differences tab; nothing is
    # labeled yet, so every image is "not comparable"
    expect(page.locator(".tab.active")).to_contain_text("Abweichungen")
    expect(page.locator(".card")).to_have_count(0)
    page.locator(".tab", has_text="Nicht vergleichbar").click()
    expect(page.locator(".card.card-compare").first).to_be_visible()
    # ending the comparison returns to the normal tabs and cards
    page.locator("#compare-trigger").click()
    page.locator("#compare-clear").click()
    expect(page.locator(".tab").first).to_contain_text("Unclassified")
    expect(page.locator(".card-compare")).to_have_count(0)


def test_compare_panel_limits_selection(login, live_server):
    """At most two sources can be checked; the panels close each other and on Escape."""
    data_dir = live_server["labels_csv"].parent
    for name in ("copy_a.csv", "copy_b.csv"):
        shutil.copy(live_server["ground_truth_csv"], data_dir / name)
    page = login
    page.goto(live_server["base_url"] + "/main?modality=EL")
    page.locator("#type-filter-trigger").click()
    expect(page.locator("#type-filter-panel")).to_be_visible()
    page.locator("#compare-trigger").click()
    expect(page.locator("#type-filter-panel")).to_be_hidden()
    boxes = page.locator('#compare-panel input[name="src"]')
    expect(boxes).to_have_count(3)
    boxes.nth(0).check()
    boxes.nth(1).check()
    expect(boxes.nth(2)).to_be_disabled()
    boxes.nth(1).uncheck()
    expect(boxes.nth(2)).to_be_enabled()
    page.keyboard.press("Escape")
    expect(page.locator("#compare-panel")).to_be_hidden()


def test_compare_highlight_follows_checkboxes(login, live_server, save_and_wait):
    """Differences are re-evaluated live while editing and persist after saving."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=all&src=ground_truth.csv")
    # ground truth of this image: every defect set, Good not set
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    expect(card).not_to_have_class(re.compile(r"has-diff"))  # unlabeled: not compared
    card.locator('.label-checkbox[data-key="good"]').click()
    expect(card).to_have_class(re.compile(r"has-diff"))
    expect(card.locator(".label-row.diff")).to_have_count(7)  # Good + six defects
    expect(card.locator('.label-row[data-key="good"] .src-val')).to_have_class(
        re.compile(r"\bdiff\b")
    )
    # setting the defects of the ground truth clears Good and every difference
    for key in DEFECT_KEYS:
        card.locator(f'.label-checkbox[data-key="{key}"]').click()
    expect(card.locator(".label-row.diff")).to_have_count(0)
    expect(card).not_to_have_class(re.compile(r"has-diff"))
    # the statistics panel stays open across the reload of the save
    page.locator("#compare-stats summary").click()
    expect(page.locator("#compare-stats .stats-table")).to_be_visible()
    save_and_wait()
    expect(page.locator("#compare-stats .stats-table")).to_be_visible()
    expect(page.locator("#compare-stats summary")).to_contain_text(
        "100.0 % übereinstimmend (1 von 1)"
    )
    page.goto(base + "/main?modality=EL&tab=cmp-agree&src=ground_truth.csv")
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')).to_be_visible()
