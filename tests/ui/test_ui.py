"""Browser smoke tests for the main labeling workflow (Playwright)."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError, expect

pytestmark = pytest.mark.ui

DEFECT_KEYS = ["crack", "cross", "dark", "corrosion", "discoloration", "delamination"]


def test_login_and_gallery(login):
    """The gallery shows all tabs (incl. the trailing All tab) and cards."""
    page = login
    # Unclassified + Good + one tab per defect + All (last)
    expect(page.locator(".tab")).to_have_count(len(DEFECT_KEYS) + 3)
    expect(page.locator(".tab").last).to_contain_text("All")
    expect(page.locator(".card")).not_to_have_count(0)
    expect(page.locator("#modality")).to_contain_text("All")


def test_checkbox_good_exclusivity(login, live_server, save_and_wait):
    """Verify pending and persisted Good exclusivity.

    Pending clicks stay in the current tab; saving persists Good and clears
    the previously clicked defect from the card and the Crack tab.
    """
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    # a pending click must NOT move the card out of the current tab
    card.locator('.label-checkbox[data-key="crack"]').click()
    expect(card).to_be_visible()
    expect(card.locator('.label-checkbox[data-key="crack"]')).to_be_checked()
    expect(page.locator("#save-btn")).to_be_enabled()
    expect(page.locator("#save-btn")).to_contain_text("Save (1)")
    # setting Good clears the pending Crack locally, card stays visible
    card.locator('.label-checkbox[data-key="good"]').click()
    expect(card.locator('.label-checkbox[data-key="good"]')).to_be_checked()
    expect(card.locator('.label-checkbox[data-key="crack"]')).not_to_be_checked()
    expect(card).to_be_visible()
    # saving reloads the page: the card leaves Unclassified and lands in Good
    save_and_wait()
    expect(card).to_have_count(0)  # only true after the reload
    page.goto(base + "/main?modality=EL&tab=good")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    expect(card).to_be_visible()
    expect(card.locator('.label-checkbox[data-key="good"]')).to_be_checked()
    expect(card.locator('.label-checkbox[data-key="crack"]')).not_to_be_checked()
    # the persisted Good keeps it out of the Crack tab
    page.goto(base + "/main?modality=EL&tab=crack")
    expect(card).to_have_count(0)


def test_revert_clears_dirtiness(login, live_server):
    """Clicking a checkbox back to its initial state removes it from Save."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    crack = card.locator('.label-checkbox[data-key="crack"]')
    crack.click()
    expect(page.locator("#save-btn")).to_be_enabled()
    crack.click()  # back to the initial state
    expect(page.locator("#save-btn")).to_be_disabled()
    assert not live_server["labels_csv"].exists()  # nothing persisted without Save


def test_ctrl_s_saves_like_button(login, live_server):
    """Ctrl+S persists pending changes exactly like clicking the Save button."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    card.locator('.label-checkbox[data-key="crack"]').click()
    expect(page.locator("#save-btn")).to_be_enabled()
    page.keyboard.press("Control+s")
    expect(page.locator("#save-btn")).to_have_text("Save")  # only after the reload
    expect(card).to_have_count(0)  # card left Unclassified via the reload
    assert live_server["labels_csv"].exists()
    page.goto(base + "/main?modality=EL&tab=crack")
    card = page.locator('[data-filename="TEST_ALL_EL_Cell001.tif"]')
    expect(card.locator('.label-checkbox[data-key="crack"]')).to_be_checked()


def test_ctrl_s_clean_state_is_noop(login, live_server):
    """Ctrl+S with a clean state does not navigate and persists nothing."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    expect(page.locator("#save-btn")).to_be_disabled()
    with pytest.raises(TimeoutError):
        with page.expect_navigation(timeout=2000):
            page.keyboard.press("Control+s")
    assert not live_server["labels_csv"].exists()


def test_group_modal_shows_missing_modality(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    # this group has no UVF image on purpose
    card = page.locator('[data-filename="TEST_23-P09-B2_EL_Cell002.tif"]')
    card.locator(".card-image").click()
    modal = page.locator("#group-modal")
    expect(modal).to_be_visible()
    body = page.locator("#modal-body")
    expect(body.locator("img")).to_have_count(2)  # VI + EL present
    expect(body.locator(".modal-missing")).to_have_text("Image missing")  # UVF missing
    expect(body.locator("figcaption")).to_have_text(["VI", "EL", "UVF"])
    page.locator("#modal-close").click()
    expect(modal).to_be_hidden()


def test_modal_zoom_wheel_and_double_click_reset(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_23-P09-B2_EL_Cell002.tif"]')
    card.locator(".card-image").click()
    stages = page.locator("#modal-body .modal-image-stage")
    expect(stages).to_have_count(2)  # VI + EL (UVF missing on purpose)
    first = stages.first
    second = stages.nth(1)
    expect(first).to_be_visible()
    expect(first).to_have_css("transform", "none")
    first.hover()
    page.mouse.wheel(0, -600)  # zoom in around the cursor
    expect(first).not_to_have_css("transform", "none")
    # the other modality zooms in sync: same transform and same focal point
    expect(second).not_to_have_css("transform", "none")
    assert first.evaluate("e => e.style.transformOrigin") == second.evaluate(
        "e => e.style.transformOrigin"
    )
    first.dblclick()  # reset
    expect(first).to_have_css("transform", "none")
    expect(second).to_have_css("transform", "none")


def test_modal_original_view_with_window_controls(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_23-P09-B2_EL_Cell002.tif"]')
    card.locator(".card-image").click()
    figure = page.locator("#modal-body figure").first
    # the original TIFF is the default view and loads on its own
    canvas = figure.locator("canvas")
    expect(canvas).to_be_visible()
    expect(figure.locator(".modal-image-stage img")).to_be_hidden()
    expect(figure.locator(".modal-image-controls .view-toggle")).to_have_text("Vorschau")
    expect(figure.locator(".modal-window-controls")).to_be_visible()
    expect(figure.locator(".modal-window-controls")).to_contain_text("Min")
    expect(figure.locator(".modal-window-controls")).to_contain_text("Max")
    # the sliders show their current values, the caption sits above the image
    expect(figure.locator(".modal-window-value")).to_have_count(2)
    expect(figure.locator(".modal-window-bits")).to_have_text("8-Bit")
    assert figure.evaluate("el => el.firstElementChild.tagName") == "FIGCAPTION"
    download_button = figure.locator(".modal-image-controls .download-btn")
    expect(download_button).to_have_text("Download")
    with page.expect_download() as download_info:
        download_button.click()
    assert download_info.value.suggested_filename == "TEST_23-P09-B2_VI_Cell002.tif"
    # the min/max window maps the brightest deterministic sample pixel to 255
    max_pixel = canvas.evaluate(
        """el => {
            const data = el.getContext("2d").getImageData(0, 0, el.width, el.height).data;
            let max = 0;
            for (let i = 0; i < data.length; i += 4) max = Math.max(max, data[i]);
            return max;
        }"""
    )
    assert max_pixel == 255
    # the sliders span the native range, so the raw 1:1 mapping is reachable
    sliders = figure.locator(".modal-window-controls input[type=range]")
    expect(sliders.nth(0)).to_have_attribute("min", "0")
    expect(sliders.nth(0)).to_have_attribute("max", "255")
    sliders.nth(0).evaluate("el => { el.value = '0'; el.dispatchEvent(new Event('input')); }")
    expect(figure.locator(".modal-window-value").first).to_have_text("0")
    # switch back to the preview on demand
    figure.locator(".modal-image-controls .view-toggle").click()
    expect(canvas).to_have_count(0)
    expect(figure.locator(".modal-image-stage img")).to_be_visible()


def test_preview_window_panel_updates_config(login, live_server):
    """The main-menu sliders persist the window to config.json and reload."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=UVF&tab=unclassified")
    page.locator("#window-filter-trigger").click()
    panel = page.locator("#window-filter-panel")
    expect(panel).to_be_visible()
    expect(panel.locator("#window-bits")).to_have_text("8-Bit")
    # reset first so the test is independent of the current config values
    panel.locator("#window-reset").click()
    expect(panel).to_be_hidden()  # fresh page after the reload
    page.locator("#window-filter-trigger").click()
    expect(panel).to_be_visible()
    # exact values can be typed into the number input
    max_input = panel.locator("#window-max-input")
    max_input.fill("26")
    max_input.press("Enter")  # triggers change -> save + reload
    # the new window shows up in the trigger
    expect(page.locator("#window-filter-trigger")).to_contain_text("26")
    config_text = Path(live_server["config_path"]).read_text(encoding="utf-8")
    assert '"preview_max": 26.0' in config_text


def test_preview_window_panel_invert_persists(login, live_server):
    """The panel checkbox persists the invert flag to config.json and reloads."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=UVF&tab=unclassified")
    page.locator("#window-filter-trigger").click()
    panel = page.locator("#window-filter-panel")
    expect(panel).to_be_visible()
    # reset first so the test is independent of the current config values
    panel.locator("#window-reset").click()
    expect(panel).to_be_hidden()  # fresh page after the reload
    page.locator("#window-filter-trigger").click()
    expect(panel).to_be_visible()
    invert = panel.locator("#window-invert")
    expect(invert).not_to_be_checked()
    invert.check()  # triggers change -> save + reload
    expect(panel).to_be_hidden()
    config_text = Path(live_server["config_path"]).read_text(encoding="utf-8")
    assert '"preview_invert": true' in config_text
    # the fresh page renders the checkbox checked and marks the trigger
    expect(page.locator("#window-filter-trigger")).to_contain_text("invertiert")
    page.locator("#window-filter-trigger").click()
    expect(page.locator("#window-filter-panel #window-invert")).to_be_checked()
    # unchecking removes the flag again
    page.locator("#window-filter-panel #window-invert").uncheck()
    expect(page.locator("#window-filter-panel")).to_be_hidden()
    config_text = Path(live_server["config_path"]).read_text(encoding="utf-8")
    assert '"preview_invert": false' in config_text
    expect(page.locator("#window-filter-trigger")).not_to_contain_text("invertiert")


def test_modal_original_view_rgb(login, live_server):
    """The original view also renders multi-channel (RGB) TIFFs."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=UVF&tab=unclassified")
    card = page.locator('[data-filename="TEST_23-P09-B1_UV_Cell004.tif"]')
    card.locator(".card-image").click()
    # the group also contains the nested EL Cell004 — scope by the image
    figure = page.locator(
        "#modal-body figure", has=page.locator('img[alt="TEST_23-P09-B1_UV_Cell004.tif"]')
    )
    canvas = figure.locator("canvas")
    expect(canvas).to_be_visible()
    max_pixel = canvas.evaluate(
        """el => {
            const data = el.getContext("2d").getImageData(0, 0, el.width, el.height).data;
            let max = 0;
            for (let i = 0; i < data.length; i += 4) max = Math.max(max, data[i]);
            return max;
        }"""
    )
    assert max_pixel == 255


def test_modal_invert_per_figure_and_master(login, live_server):
    """Each figure inverts on its own; the master button inverts all at once."""
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=EL&tab=unclassified")
    card = page.locator('[data-filename="TEST_23-P09-B2_EL_Cell002.tif"]')
    card.locator(".card-image").click()
    figures = page.locator("#modal-body .modal-image")
    expect(figures).to_have_count(3)  # VI + EL, UVF missing (no controls)
    first = figures.nth(0)
    second = figures.nth(1)
    master = page.locator("#modal-invert-all")
    expect(master).to_have_attribute("aria-pressed", "false")
    # per-figure toggle: class, CSS filter on the stage and aria state
    first.locator(".invert-toggle").click()
    expect(first).to_have_class(re.compile(r"inverted"))
    expect(first.locator(".modal-image-stage")).to_have_css("filter", "invert(1)")
    expect(first.locator(".invert-toggle")).to_have_attribute("aria-pressed", "true")
    expect(second).not_to_have_class(re.compile(r"inverted"))
    expect(second.locator(".modal-image-stage")).not_to_have_css("filter", "invert(1)")
    first.locator(".invert-toggle").click()  # back off
    expect(first).not_to_have_class(re.compile(r"inverted"))
    expect(first.locator(".modal-image-stage")).to_have_css("filter", "none")
    # master switch: one click inverts both, the next click reverts both
    master.click()
    expect(first).to_have_class(re.compile(r"inverted"))
    expect(second).to_have_class(re.compile(r"inverted"))
    expect(master).to_have_attribute("aria-pressed", "true")
    master.click()
    expect(first).not_to_have_class(re.compile(r"inverted"))
    expect(second).not_to_have_class(re.compile(r"inverted"))
    expect(master).to_have_attribute("aria-pressed", "false")


def test_cell_type_panel_multiselect(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=VI&tab=unclassified")
    page.locator("#type-filter-trigger").click()
    panel = page.locator("#type-filter-panel")
    expect(panel).to_be_visible()
    panel.locator('input[value="TEST_23-P09-B2"]').check()
    panel.locator('input[value="TEST_24-Q01-A3"]').check()
    panel.locator(".apply-btn").click()
    page.wait_for_url("**cell_type=TEST_23-P09-B2*")
    filenames = page.locator(".card").evaluate_all("els => els.map(e => e.dataset.filename)")
    assert any(name.startswith("TEST_23-P09-B2_VI") for name in filenames)
    assert any(name.startswith("TEST_24-Q01-A3_VI") for name in filenames)
    assert not any(name.startswith("TEST_23-P09-B1_VI") for name in filenames)


def test_modality_all_shows_badges(login, live_server):
    page = login
    base = live_server["base_url"]
    page.goto(base + "/main?modality=all&tab=unclassified")
    badges = page.locator(".card-modality")
    expect(badges.first).to_be_visible()
    texts = badges.all_text_contents()
    assert "VI" in texts and "EL" in texts and "UVF" in texts
