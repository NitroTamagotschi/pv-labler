(function () {
  "use strict";

  const APP = window.APP;
  const labelKeys = [APP.goodKey, ...APP.defectKeys];
  // {card, checkboxes} pairs collected once at startup: the gallery is static
  let cardEntries = [];
  // number of dirty cards, kept incrementally so save-button updates do not
  // scan every card on each click (the gallery holds tens of thousands)
  let dirtyCount = 0;

  function collectCheckboxes(card) {
    const checkboxes = {};
    for (const key of labelKeys) {
      checkboxes[key] = card.querySelector(`.label-checkbox[data-key="${key}"]`);
    }
    return checkboxes;
  }

  // full current checkbox state of one card {key: 0|1}
  function cardState(entry) {
    const state = {};
    for (const key of labelKeys) {
      state[key] = entry.checkboxes[key].checked ? 1 : 0;
    }
    return state;
  }

  // defaultChecked holds the server-rendered state, so reverting a checkbox
  // to its initial value automatically makes the card clean again
  function cardIsDirty(entry) {
    for (const key of labelKeys) {
      const checkbox = entry.checkboxes[key];
      if (checkbox.checked !== checkbox.defaultChecked) {
        return true;
      }
    }
    return false;
  }

  function applyCardState(entry, state) {
    for (const key of labelKeys) {
      entry.checkboxes[key].checked = !!state[key];
    }
  }

  // mirror of labels.apply_label_change: Good clears defects and vice versa
  function applyLocalChange(entry, key, checked) {
    const state = cardState(entry);
    state[key] = checked ? 1 : 0;
    if (key === APP.goodKey && checked) {
      for (const defect of APP.defectKeys) {
        state[defect] = 0;
      }
    }
    if (APP.defectKeys.includes(key) && checked) {
      state[APP.goodKey] = 0;
    }
    applyCardState(entry, state);
  }

  // tracks one entry's dirty state against the incremental dirtyCount
  function updateDirty(entry) {
    const dirty = cardIsDirty(entry);
    if (dirty !== entry.dirty) {
      entry.dirty = dirty;
      dirtyCount += dirty ? 1 : -1;
    }
  }

  function refreshSaveButton() {
    const button = document.getElementById("save-btn");
    button.disabled = dirtyCount === 0;
    button.textContent = dirtyCount ? `Save (${dirtyCount})` : "Save";
  }

  async function saveChanges() {
    const changes = {};
    for (const entry of cardEntries) {
      if (cardIsDirty(entry)) {
        changes[entry.card.dataset.filename] = cardState(entry);
      }
    }
    const button = document.getElementById("save-btn");
    button.disabled = true;
    try {
      const response = await fetch(APP.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changes }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        window.alert(data.error || "Save failed");
        refreshSaveButton();
        return;
      }
      // leave the button disabled: it doubles as the beforeunload guard, so
      // the reload itself does not trigger the leave-site dialog
      location.reload();
    } catch (error) {
      window.alert("Save failed: " + error);
      refreshSaveButton();
    }
  }

  window.addEventListener("beforeunload", (event) => {
    // the disabled button doubles as the unsaved-changes flag
    if (!document.getElementById("save-btn").disabled) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  // one shared zoom state per modal: all images always show the same
  // relative section. Wheel zooms 1x-8x exactly around the cursor position,
  // dragging pans, double click resets. Interacting with any image drives
  // all images of the group. The zoom target is the stage element so the
  // preview/original toggle does not break it.
  function attachGroupZoom(stages) {
    const state = { scale: 1, fx: 0.5, fy: 0.5 }; // focal point in relative coords (0..1)

    function applyAll() {
      for (const entry of stages) {
        if (state.scale === 1) {
          entry.stage.style.transform = "";
        } else {
          entry.stage.style.transformOrigin = `${state.fx * 100}% ${state.fy * 100}%`;
          entry.stage.style.transform = `scale(${state.scale})`;
        }
        entry.figure.classList.toggle("zoomed", state.scale > 1);
      }
    }

    function setState(scale, fx, fy) {
      state.scale = scale;
      state.fx = fx;
      state.fy = fy;
      applyAll();
    }

    for (const entry of stages) {
      entry.stage.addEventListener("wheel", (event) => {
        event.preventDefault();
        const rect = entry.stage.getBoundingClientRect();
        // cursor position in relative visual coordinates (0..1)
        const vx = (event.clientX - rect.left) / rect.width;
        const vy = (event.clientY - rect.top) / rect.height;
        const factor = event.deltaY < 0 ? 1.25 : 0.8;
        const next = Math.min(8, Math.max(1, state.scale * factor));
        if (next === state.scale) {
          return;
        }
        if (next === 1) {
          setState(1, 0.5, 0.5);
          return;
        }
        // anchor the point under the cursor: convert visual to local coords
        const fx = state.fx + (vx - state.fx) / state.scale;
        const fy = state.fy + (vy - state.fy) / state.scale;
        setState(next, fx, fy);
      });

      let dragging = false;
      let startClientX = 0;
      let startClientY = 0;
      let startFx = 0;
      let startFy = 0;
      entry.stage.addEventListener("pointerdown", (event) => {
        if (state.scale <= 1) {
          return;
        }
        dragging = true;
        startClientX = event.clientX;
        startClientY = event.clientY;
        startFx = state.fx;
        startFy = state.fy;
        entry.stage.setPointerCapture(event.pointerId);
        entry.figure.classList.add("dragging");
        event.preventDefault();
      });
      entry.stage.addEventListener("pointermove", (event) => {
        if (!dragging) {
          return;
        }
        const rect = entry.stage.getBoundingClientRect();
        const fx = startFx - (event.clientX - startClientX) / rect.width;
        const fy = startFy - (event.clientY - startClientY) / rect.height;
        setState(state.scale, fx, fy);
      });
      entry.stage.addEventListener("pointerup", () => {
        dragging = false;
        entry.figure.classList.remove("dragging");
      });
      entry.stage.addEventListener("dblclick", () => setState(1, 0.5, 0.5));
    }
  }

  // toggles one modal image between the JPEG preview and a canvas rendering
  // of the original TIFF, decoded in the browser with UTIF and displayed
  // with min/max window sliders over the raw data range.
  function attachOriginalView(button, stage, img, filename, figure) {
    let canvas = null;
    let controls = null;
    let rawData = null;
    let rawChannels = 1;
    let dataMin = 0;
    let dataMax = 255;

    function renderWindow(lo, hi) {
      const ctx = canvas.getContext("2d");
      const pixels = ctx.createImageData(canvas.width, canvas.height);
      const data = pixels.data;
      const range = Math.max(1, hi - lo);
      const pixelCount = data.length / 4;
      for (let p = 0; p < pixelCount; p++) {
        for (let c = 0; c < 3; c++) {
          const index = rawChannels >= 3 ? p * rawChannels + c : p;
          const value = Math.min(1, Math.max(0, (rawData[index] - lo) / range));
          data[p * 4 + c] = Math.round(value * 255);
        }
        data[p * 4 + 3] = 255;
      }
      ctx.putImageData(pixels, 0, 0);
    }

    function buildControls() {
      const step = Math.max(1, Math.round((dataMax - dataMin) / 1000));
      const formatValue = (value) => String(Math.round(value * 100) / 100);
      const makeSlider = (labelText, value) => {
        const label = document.createElement("label");
        label.className = "modal-window-label";
        label.textContent = labelText;
        const valueSpan = document.createElement("span");
        valueSpan.className = "modal-window-value";
        valueSpan.textContent = formatValue(value);
        label.append(" ", valueSpan);
        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = String(dataMin);
        slider.max = String(dataMax);
        slider.step = String(step);
        slider.value = String(value);
        return { label, slider, valueSpan };
      };
      const min = makeSlider("Min", dataMin);
      const max = makeSlider("Max", dataMax);
      const reset = document.createElement("button");
      reset.type = "button";
      reset.className = "link-btn";
      reset.textContent = "Reset";
      const bits = document.createElement("span");
      bits.className = "modal-window-bits";
      bits.textContent = `${rawData.BYTES_PER_ELEMENT * 8}-Bit`;
      controls = document.createElement("div");
      controls.className = "modal-window-controls";
      controls.append(min.label, min.slider, max.label, max.slider, bits, reset);
      figure.appendChild(controls);
      const update = () => {
        min.valueSpan.textContent = formatValue(Number(min.slider.value));
        max.valueSpan.textContent = formatValue(Number(max.slider.value));
        const lo = Math.min(Number(min.slider.value), Number(max.slider.value));
        const hi = Math.max(Number(min.slider.value), Number(max.slider.value));
        renderWindow(lo, hi);
      };
      min.slider.addEventListener("input", update);
      max.slider.addEventListener("input", update);
      reset.addEventListener("click", () => {
        min.slider.value = String(dataMin);
        max.slider.value = String(dataMax);
        update();
      });
    }

    async function load() {
      const url = APP.originalUrl.replace("__FN__", encodeURIComponent(filename));
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Original download failed (${response.status})`);
      }
      const buffer = await response.arrayBuffer();
      const ifds = UTIF.decode(buffer);
      UTIF.decodeImage(buffer, ifds[0]);
      const ifd = ifds[0];
      // UTIF hands the raw samples over as bytes; reinterpret them according
      // to the sample size and channel count (16-bit ints, 32-bit floats and
      // RGB captures with 3+ channels are all common in practice)
      rawChannels = ifd["t277"] ? ifd["t277"][0] : 1;
      const samples = ifd.width * ifd.height * rawChannels;
      const view = new DataView(ifd.data.buffer, ifd.data.byteOffset, ifd.data.length);
      if (ifd.data.length === samples) {
        rawData = ifd.data;
      } else if (ifd.data.length === samples * 2) {
        const values = new Uint16Array(samples);
        for (let i = 0; i < samples; i++) values[i] = view.getUint16(i * 2, ifd.isLE);
        rawData = values;
      } else if (ifd.data.length === samples * 4) {
        const values = new Float32Array(samples);
        for (let i = 0; i < samples; i++) values[i] = view.getFloat32(i * 4, ifd.isLE);
        rawData = values;
      } else {
        throw new Error("Unsupported TIFF data layout");
      }
      canvas = document.createElement("canvas");
      canvas.width = ifd.width;
      canvas.height = ifd.height;
      stage.appendChild(canvas);
      dataMin = Infinity;
      dataMax = -Infinity;
      for (let i = 0; i < rawData.length; i++) {
        if (rawData[i] < dataMin) dataMin = rawData[i];
        if (rawData[i] > dataMax) dataMax = rawData[i];
      }
      buildControls();
      renderWindow(dataMin, dataMax);
    }

    async function toggle() {
      if (canvas) {
        // back to the preview
        canvas.remove();
        canvas = null;
        rawData = null;
        rawChannels = 1;
        controls.remove();
        controls = null;
        img.hidden = false;
        button.textContent = "Original";
        return;
      }
      button.textContent = "Lädt…";
      button.disabled = true;
      try {
        await load();
        img.hidden = true;
        button.textContent = "Vorschau";
      } catch (error) {
        window.alert(error.message || "Failed to load the original image");
        if (canvas) {
          canvas.remove();
          canvas = null;
          rawData = null;
        }
        button.textContent = "Original";
      } finally {
        button.disabled = false;
      }
    }

    button.addEventListener("click", toggle);
    return toggle;
  }

  function openGroupModal(filename) {
    const url = APP.groupUrl.replace("__FN__", encodeURIComponent(filename));
    fetch(url)
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) {
          window.alert(data.error || "Failed to load image group");
          return;
        }
        document.getElementById("modal-title").textContent = data.group_key;
        const body = document.getElementById("modal-body");
        body.textContent = "";
        const zoomEntries = [];
        const originalToggles = [];
        for (const member of data.members) {
          const figure = document.createElement("figure");
          figure.className = "modal-image";
          const caption = document.createElement("figcaption");
          caption.textContent = member.variant
            ? `${member.display_name} (${member.variant})`
            : member.display_name;
          figure.appendChild(caption);
          if (member.preview_url) {
            const wrap = document.createElement("div");
            wrap.className = "modal-image-wrap";
            const stage = document.createElement("div");
            stage.className = "modal-image-stage";
            const img = document.createElement("img");
            img.src = member.preview_url;
            img.alt = member.filename;
            img.draggable = false;
            stage.appendChild(img);
            wrap.appendChild(stage);
            figure.appendChild(wrap);
            zoomEntries.push({ stage: stage, figure: figure });
            const controls = document.createElement("div");
            controls.className = "modal-image-controls";
            const originalButton = document.createElement("button");
            originalButton.type = "button";
            originalButton.className = "link-btn";
            originalButton.textContent = "Original";
            const downloadLink = document.createElement("a");
            downloadLink.className = "link-btn";
            downloadLink.textContent = "Download";
            downloadLink.href = APP.originalUrl.replace(
              "__FN__",
              encodeURIComponent(member.filename)
            );
            downloadLink.setAttribute("download", member.filename.split("/").pop());
            controls.append(originalButton, downloadLink);
            figure.appendChild(controls);
            originalToggles.push(
              attachOriginalView(originalButton, stage, img, member.filename, figure)
            );
          } else {
            const missing = document.createElement("div");
            missing.className = "modal-missing";
            missing.textContent = "Image missing";
            figure.appendChild(missing);
          }
          body.appendChild(figure);
        }
        attachGroupZoom(zoomEntries);
        // the original TIFF is the default view; the preview is one click away
        for (const toggle of originalToggles) {
          toggle();
        }
        document.getElementById("group-modal").hidden = false;
      })
      .catch((error) => window.alert("Failed to load image group: " + error));
  }

  function closeGroupModal() {
    document.getElementById("group-modal").hidden = true;
  }

  document.addEventListener("DOMContentLoaded", () => {
    function makeEntry(card) {
      return { card: card, checkboxes: collectCheckboxes(card), dirty: false };
    }

    // attaches the listeners every card needs; used for the initial batch
    // and for batches appended by the infinite scroll
    function wireCard(entry) {
      entry.card.addEventListener("change", (event) => {
        const checkbox = event.target;
        if (checkbox.classList.contains("label-checkbox")) {
          applyLocalChange(entry, checkbox.dataset.key, checkbox.checked);
          updateDirty(entry);
          refreshSaveButton();
        }
      });
      for (const button of entry.card.querySelectorAll(".card-image, .card-name")) {
        button.addEventListener("click", () => openGroupModal(entry.card.dataset.filename));
      }
    }

    cardEntries = [...document.querySelectorAll(".card")].map(makeEntry);
    for (const entry of cardEntries) {
      wireCard(entry);
    }
    const empty = document.querySelector(".gallery .empty");
    if (empty) {
      empty.hidden = cardEntries.length > 0;
    }

    // infinite scroll: the sentinel marks the end of the rendered batch and
    // fetches the next one when it scrolls into view
    const sentinel = document.getElementById("gallery-sentinel");
    if (sentinel) {
      let loading = false;
      const loadMore = async () => {
        if (loading) {
          return;
        }
        loading = true;
        try {
          const offset = Number(sentinel.dataset.offset);
          const query = sentinel.dataset.query;
          const response = await fetch(`${APP.cardsUrl}?${query}&offset=${offset}`);
          const data = await response.json();
          if (!response.ok || !data.ok) {
            throw new Error(data.error || "loading more cards failed");
          }
          const known = new Set(cardEntries.map((entry) => entry.card));
          sentinel.insertAdjacentHTML("beforebegin", data.html);
          for (const card of document.querySelectorAll(".card")) {
            if (known.has(card)) {
              continue;
            }
            const entry = makeEntry(card);
            cardEntries.push(entry);
            wireCard(entry);
          }
          sentinel.dataset.offset = String(offset + data.count);
          if (data.remaining <= 0) {
            sentinel.remove();
          }
        } catch (error) {
          console.error(error);
          sentinel.textContent = "Failed to load more cards — click to retry";
        } finally {
          loading = false;
        }
      };
      sentinel.addEventListener("click", () => {
        if (sentinel.textContent) {
          sentinel.textContent = "";
          loadMore();
        }
      });
      new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting) {
            loadMore();
          }
        },
        { rootMargin: "800px" }
      ).observe(sentinel);
    }
    const modal = document.getElementById("group-modal");
    document.getElementById("save-btn").addEventListener("click", saveChanges);
    document.getElementById("modal-close").addEventListener("click", closeGroupModal);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeGroupModal();
      }
    });

    // cell type filter panel
    const typeTrigger = document.getElementById("type-filter-trigger");
    const typePanel = document.getElementById("type-filter-panel");
    if (typeTrigger && typePanel) {
      typeTrigger.addEventListener("click", (event) => {
        event.stopPropagation();
        typePanel.hidden = !typePanel.hidden;
      });
      document.addEventListener("click", (event) => {
        if (!typePanel.hidden && !typePanel.contains(event.target) && event.target !== typeTrigger) {
          typePanel.hidden = true;
        }
      });
      const toggleAllTypes = (checked) => {
        typePanel.querySelectorAll('input[name="cell_type"]').forEach((checkbox) => {
          checkbox.checked = checked;
        });
      };
      document.getElementById("tf-all").addEventListener("click", () => toggleAllTypes(true));
      document.getElementById("tf-none").addEventListener("click", () => toggleAllTypes(false));
    }

    // preview window panel: adjust the modality's preview window live and
    // persist it to config.json; the page reloads to refresh the previews
    const windowTrigger = document.getElementById("window-filter-trigger");
    const windowPanel = document.getElementById("window-filter-panel");
    if (windowTrigger && windowPanel) {
      windowTrigger.addEventListener("click", (event) => {
        event.stopPropagation();
        windowPanel.hidden = !windowPanel.hidden;
      });
      document.addEventListener("click", (event) => {
        if (
          !windowPanel.hidden &&
          !windowPanel.contains(event.target) &&
          event.target !== windowTrigger
        ) {
          windowPanel.hidden = true;
        }
      });
      const minSlider = document.getElementById("window-min");
      const maxSlider = document.getElementById("window-max");
      if (minSlider && maxSlider) {
        const minInput = document.getElementById("window-min-input");
        const maxInput = document.getElementById("window-max-input");
        const step = Number(minSlider.max) / 1000;
        minSlider.step = String(step);
        maxSlider.step = String(step);
        // sliders and number inputs stay in sync; the inputs are the source
        // of truth when saving because typed values are exact
        minSlider.addEventListener("input", () => {
          minInput.value = minSlider.value;
        });
        maxSlider.addEventListener("input", () => {
          maxInput.value = maxSlider.value;
        });
        const clampInput = (input) => {
          const low = Number(input.min);
          const high = Number(input.max);
          let value = Number(input.value);
          if (Number.isNaN(value)) value = low;
          value = Math.min(high, Math.max(low, value));
          input.value = String(value);
          return value;
        };
        const post = async (body) => {
          const response = await fetch(APP.previewWindowUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await response.json();
          if (!response.ok || !data.ok) {
            window.alert(data.error || "Preview window update failed");
            return;
          }
          location.reload();
        };
        const postFromInputs = () => {
          const min = clampInput(minInput);
          const max = clampInput(maxInput);
          if (max <= min) {
            window.alert("min must be < max");
            return;
          }
          minSlider.value = String(min);
          maxSlider.value = String(max);
          return post({ code: APP.modality, min: min, max: max });
        };
        const syncInputsFromSliders = () => {
          minInput.value = minSlider.value;
          maxInput.value = maxSlider.value;
        };
        minSlider.addEventListener("change", () => {
          syncInputsFromSliders();
          postFromInputs();
        });
        maxSlider.addEventListener("change", () => {
          syncInputsFromSliders();
          postFromInputs();
        });
        minInput.addEventListener("change", postFromInputs);
        maxInput.addEventListener("change", postFromInputs);
        document.getElementById("window-reset").addEventListener("click", () =>
          post({ code: APP.modality, reset: true })
        );
      }
    }

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        // preventDefault keeps the browser's "Save page" dialog from opening;
        // the disabled button doubles as the nothing-to-save / save-in-flight guard
        event.preventDefault();
        if (!document.getElementById("save-btn").disabled) {
          saveChanges();
        }
        return;
      }
      if (event.key === "Escape") {
        if (!modal.hidden) {
          closeGroupModal();
        }
        if (typePanel && !typePanel.hidden) {
          typePanel.hidden = true;
        }
        const winPanel = document.getElementById("window-filter-panel");
        if (winPanel && !winPanel.hidden) {
          winPanel.hidden = true;
        }
      }
    });
  });
})();
