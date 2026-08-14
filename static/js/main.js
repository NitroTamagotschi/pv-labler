(function () {
  "use strict";

  const APP = window.APP;
  const labelKeys = [APP.goodKey, ...APP.defectKeys];
  const currentTab = APP.tab;

  function isUnclassified(state) {
    return !state[APP.goodKey] && !APP.defectKeys.some((key) => state[key]);
  }

  function matchesFilter(state) {
    if (currentTab === "unclassified") {
      return isUnclassified(state);
    }
    return !!state[currentTab];
  }

  function setCheckboxes(card, state) {
    for (const key of labelKeys) {
      const checkbox = card.querySelector(`.label-checkbox[data-key="${key}"]`);
      if (checkbox) {
        checkbox.checked = !!state[key];
      }
    }
  }

  function removeCard(card) {
    card.remove();
    const count = document.querySelector(".tab.active .count");
    if (count) {
      const value = Math.max(0, (parseInt(count.textContent, 10) || 0) - 1);
      count.textContent = String(value);
    }
    const empty = document.querySelector(".gallery .empty");
    if (empty && !document.querySelectorAll(".gallery .card").length) {
      empty.hidden = false;
    }
  }

  async function saveLabel(card, key, checked) {
    const checkbox = card.querySelector(`.label-checkbox[data-key="${key}"]`);
    checkbox.disabled = true;
    try {
      const response = await fetch(APP.labelUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: card.dataset.filename, key: key, value: checked }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        checkbox.checked = !checked; // revert on failure
        window.alert(data.error || "Label update failed");
        return;
      }
      setCheckboxes(card, data.state);
      if (!matchesFilter(data.state)) {
        removeCard(card);
      }
    } catch (error) {
      checkbox.checked = !checked;
      window.alert("Label update failed: " + error);
    } finally {
      checkbox.disabled = false;
    }
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
    const cards = document.querySelectorAll(".card");
    for (const card of cards) {
      card.addEventListener("change", (event) => {
        const checkbox = event.target;
        if (checkbox.classList.contains("label-checkbox")) {
          saveLabel(card, checkbox.dataset.key, checkbox.checked);
        }
      });
      for (const button of card.querySelectorAll(".card-image, .card-name")) {
        button.addEventListener("click", () => openGroupModal(card.dataset.filename));
      }
    }
    const empty = document.querySelector(".gallery .empty");
    if (empty) {
      empty.hidden = cards.length > 0;
    }
    const modal = document.getElementById("group-modal");
    document.getElementById("modal-close").addEventListener("click", closeGroupModal);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeGroupModal();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) {
        closeGroupModal();
      }
    });
  });
})();
