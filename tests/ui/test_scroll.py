"""Infinite-scroll test: the gallery loads card batches while scrolling."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui


def test_gallery_loads_more_on_scroll(scrolling_live_server, sample_script, page):
    """Scrolling to the sentinel appends batches until every card is loaded."""
    page.goto(scrolling_live_server["base_url"] + "/")
    page.fill("#name", "UI Tester")
    page.click("button[type=submit]")
    page.wait_for_url("**/main*")
    page.goto(scrolling_live_server["base_url"] + "/main?modality=all&tab=all")
    expect(page.locator(".card")).to_have_count(12)

    last = 12
    while page.locator("#gallery-sentinel").count() > 0:
        page.keyboard.press("End")  # scroll to the bottom: the sentinel fires
        page.wait_for_function(
            "(n) => document.querySelectorAll('.card').length > n",
            arg=last,
        )
        last = page.locator(".card").count()

    truth = sample_script.ground_truth_labels()
    expect(page.locator(".card")).to_have_count(len(truth))

    # a card from a later batch is fully wired: its checkbox arms the Save button
    card = page.locator(".card").last
    card.locator('.label-checkbox[data-key="good"]').click()
    expect(page.locator("#save-btn")).to_be_enabled()
