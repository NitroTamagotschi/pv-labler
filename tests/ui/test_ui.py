"""Browser smoke tests for the main labeling workflow (Playwright)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

DEFECT_KEYS = ["crack", "cross", "dark", "corrosion", "discoloration", "delamination"]


def test_login_and_gallery(login):
    page = login
    # Unclassified + Good + one tab per defect
    expect(page.locator(".tab")).to_have_count(len(DEFECT_KEYS) + 2)
    expect(page.locator(".card")).not_to_have_count(0)
    expect(page.locator("#modality")).to_contain_text("All")


def test_checkbox_good_exclusivity(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    # setting Crack moves the card out of the Unclassified view
    card.locator('.label-checkbox[data-key="crack"]').click()
    expect(card).to_have_count(0)
    # in the Crack tab it reappears with Crack checked
    page.goto(base + "/main?modality=EL&tab=crack")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    expect(card).to_be_visible()
    expect(card.locator('.label-checkbox[data-key="crack"]')).to_be_checked()
    # setting Good clears Crack and moves the card to the Good tab
    card.locator('.label-checkbox[data-key="good"]').click()
    expect(card).to_have_count(0)
    page.goto(base + "/main?modality=EL&tab=good")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    expect(card.locator('.label-checkbox[data-key="good"]')).to_be_checked()
    expect(card.locator('.label-checkbox[data-key="crack"]')).not_to_be_checked()


def test_group_modal_shows_missing_modality(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    # this group has no UVF image on purpose
    card = page.locator('[data-filename="23-P09-B2_EL_Cell002.tif"]')
    card.locator(".card-image").click()
    modal = page.locator("#group-modal")
    expect(modal).to_be_visible()
    body = page.locator("#modal-body")
    expect(body.locator("img")).to_have_count(2)  # VI + EL present
    expect(body.locator(".modal-missing")).to_have_text("Image missing")  # UVF missing
    expect(body.locator("figcaption")).to_have_text(["VI", "EL", "UVF"])
    page.locator("#modal-close").click()
    expect(modal).to_be_hidden()


def test_cell_type_panel_multiselect(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=VI&tab=unclassified")
    page.locator("#type-filter-trigger").click()
    panel = page.locator("#type-filter-panel")
    expect(panel).to_be_visible()
    panel.locator('input[value="23-P09-B2"]').check()
    panel.locator('input[value="24-Q01-A3"]').check()
    panel.locator(".apply-btn").click()
    page.wait_for_url("**cell_type=23-P09-B2*")
    filenames = page.locator(".card").evaluate_all("els => els.map(e => e.dataset.filename)")
    assert any(name.startswith("23-P09-B2_VI") for name in filenames)
    assert any(name.startswith("24-Q01-A3_VI") for name in filenames)
    assert not any(name.startswith("23-P09-B1_VI") for name in filenames)


def test_modality_all_shows_badges(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=all&tab=unclassified")
    badges = page.locator(".card-modality")
    expect(badges.first).to_be_visible()
    texts = badges.all_text_contents()
    assert "VI" in texts and "EL" in texts and "UVF" in texts