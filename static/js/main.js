(function () {
  "use strict";

  const APP = window.APP;
  const labelKeys = [APP.goodKey, ...APP.defectKeys];
  // {card, checkboxes} pairs collected once at startup: the gallery is static
  let cardEntries = [];

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

  function refreshSaveButton() {
    let count = 0;
    for (const entry of cardEntries) {
      if (cardIsDirty(entry)) {
        count += 1;
      }
    }
    const button = document.getElementById("save-btn");
    button.disabled = count === 0;
    button.textContent = count ? `Save (${count})` : "Save";
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
        for (const member of data.members) {
          const figure = document.createElement("figure");
          figure.className = "modal-image";
          if (member.preview_url) {
            const img = document.createElement("img");
            img.src = member.preview_url;
            img.alt = member.filename;
            figure.appendChild(img);
          } else {
            const missing = document.createElement("div");
            missing.className = "modal-missing";
            missing.textContent = "Image missing";
            figure.appendChild(missing);
          }
          const caption = document.createElement("figcaption");
          caption.textContent = member.variant
            ? `${member.display_name} (${member.variant})`
            : member.display_name;
          figure.appendChild(caption);
          body.appendChild(figure);
        }
        document.getElementById("group-modal").hidden = false;
      })
      .catch((error) => window.alert("Failed to load image group: " + error));
  }

  function closeGroupModal() {
    document.getElementById("group-modal").hidden = true;
  }

  document.addEventListener("DOMContentLoaded", () => {
    cardEntries = [...document.querySelectorAll(".card")].map((card) => ({
      card: card,
      checkboxes: collectCheckboxes(card),
    }));
    for (const entry of cardEntries) {
      entry.card.addEventListener("change", (event) => {
        const checkbox = event.target;
        if (checkbox.classList.contains("label-checkbox")) {
          applyLocalChange(entry, checkbox.dataset.key, checkbox.checked);
          refreshSaveButton();
        }
      });
      for (const button of entry.card.querySelectorAll(".card-image, .card-name")) {
        button.addEventListener("click", () => openGroupModal(entry.card.dataset.filename));
      }
    }
    const empty = document.querySelector(".gallery .empty");
    if (empty) {
      empty.hidden = cardEntries.length > 0;
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

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (!modal.hidden) {
          closeGroupModal();
        }
        if (typePanel && !typePanel.hidden) {
          typePanel.hidden = true;
        }
      }
    });
  });
})();
