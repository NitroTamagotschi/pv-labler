"""Multispectral solar-cell image labeling tool (Flask app).

Implements specification/specification.md: name-based login, gallery with
modality dropdown and label-filter tabs, checkbox labeling with the Good
exclusivity rules, group view pop-up and CSV/change-log persistence.
"""

import json
import os
import re

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

import images
import labels
import previews

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
LABELS_CSV = os.path.join(DATA_DIR, "labels.csv")
CHANGE_LOG = os.path.join(DATA_DIR, "change_log.txt")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PREVIEWS_DIR = os.path.join(BASE_DIR, "static", "previews")

LABEL_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")
MODALITY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

# tab keys that are not labels; they can never be configured as label keys
RESERVED_TAB_KEYS = ("unclassified", "all")


def load_config(path=CONFIG_PATH):
    """Load and validate config.json (specification §3.3)."""
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    _validate_config(config)
    return config


def _validate_config(config):
    """Raise ValueError for invalid config.json contents."""
    modalities = config.get("modalities")
    if not isinstance(modalities, list) or not modalities:
        raise ValueError("config.json: 'modalities' must be a non-empty list")
    codes = []
    filename_codes = []
    for modality in modalities:
        code = (modality.get("code") or "").strip()
        display_name = (modality.get("display_name") or "").strip()
        if not code or not display_name:
            raise ValueError("config.json: each modality needs 'code' and 'display_name'")
        if code.lower() == "all":
            raise ValueError("config.json: modality code 'all' is reserved")
        if not MODALITY_CODE_PATTERN.fullmatch(code):
            raise ValueError(f"config.json: invalid modality code {code!r}")
        filename_code = (modality.get("filename_code") or code).strip()
        if not MODALITY_CODE_PATTERN.fullmatch(filename_code):
            raise ValueError(f"config.json: invalid filename_code {filename_code!r}")
        codes.append(code)
        filename_codes.append(filename_code.lower())
    if len(set(codes)) != len(codes):
        raise ValueError("config.json: duplicate modality codes")
    if len(set(filename_codes)) != len(filename_codes):
        raise ValueError("config.json: duplicate filename_code values (case-insensitive)")

    good = config.get("labels", {}).get("good", {})
    defects = config.get("labels", {}).get("defects", [])
    if not (good.get("key") or "").strip() or not (good.get("display_name") or "").strip():
        raise ValueError("config.json: labels.good needs 'key' and 'display_name'")
    if not isinstance(defects, list):
        raise ValueError("config.json: labels.defects must be a list")
    keys = [good["key"].strip()] + [(d.get("key") or "").strip() for d in defects]
    for key in keys:
        if not key or not LABEL_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"config.json: invalid label key {key!r}")
        if key in RESERVED_TAB_KEYS:
            raise ValueError(f"config.json: label key {key!r} is reserved")
    if len(set(keys)) != len(keys):
        raise ValueError("config.json: duplicate label keys")


def _matches_tab(state, tab, is_unclassified):
    """Return whether a label state belongs to the given tab view."""
    if tab == "unclassified":
        return is_unclassified
    if tab == "all":
        return True
    return bool(state.get(tab, 0))


def create_app(config=None, images_dir=None, labels_csv=None, change_log=None, previews_dir=None):
    """Create the Flask app wired to the given config and storage locations."""
    app = Flask(__name__)
    app.secret_key = os.environ.get("PV_LABLER_SECRET_KEY", "dev-secret-key-change-me")
    config = config if config is not None else load_config()
    images_dir = images_dir or IMAGES_DIR
    os.makedirs(images_dir, exist_ok=True)

    app.config["PV_CONFIG"] = config
    app.config["PV_IMAGES_DIR"] = images_dir
    app.config["PV_STORE"] = labels.LabelStore(
        labels_csv or LABELS_CSV, change_log or CHANGE_LOG, config
    )
    app.config["PV_INDEX"] = images.ImageIndex(
        images_dir, images.modality_filename_codes(config["modalities"]), log=app.logger.warning
    )
    app.config["PV_PREVIEWS"] = previews.PreviewGenerator(images_dir, previews_dir or PREVIEWS_DIR)

    @app.route("/")
    def index():
        """Render the login page, or redirect a logged-in user to main."""
        if "name" in session:
            return redirect(url_for("main"))
        return render_template("login.html")

    @app.route("/login", methods=["POST"])
    def login():
        """Store the submitted user name in the session and redirect to main."""
        name = (request.form.get("name") or "").strip()
        if not name:
            return render_template("login.html", error="Please enter your name."), 400
        session["name"] = name
        return redirect(url_for("main"))

    @app.route("/logout")
    def logout():
        """Clear the session and return to the login page."""
        session.clear()
        return redirect(url_for("index"))

    @app.route("/main")
    def main():
        """Render the main window: gallery, tabs and filters for the session."""
        if "name" not in session:
            return redirect(url_for("index"))
        cfg = app.config["PV_CONFIG"]
        modality_codes = [m["code"] for m in cfg["modalities"]]
        good_key = cfg["labels"]["good"]["key"]
        defect_keys = [d["key"] for d in cfg["labels"]["defects"]]
        label_keys = [good_key] + defect_keys
        valid_tabs = [RESERVED_TAB_KEYS[0], *label_keys, RESERVED_TAB_KEYS[1]]

        modality = request.args.get("modality", modality_codes[0])
        if modality != "all" and modality not in modality_codes:
            modality = modality_codes[0]
        tab = request.args.get("tab", "unclassified")
        if tab not in valid_tabs:
            tab = "unclassified"

        all_images, _ = app.config["PV_INDEX"].get()
        states = app.config["PV_STORE"].get_states()

        all_types = sorted({info.cell_type for info in all_images.values()})
        selected_types = [t for t in request.args.getlist("cell_type") if t in all_types]
        if len(selected_types) == len(all_types):
            selected_types = []  # all selected == no filter
        # image count per cell type in the selected modality (for the panel)
        type_counts = {t: 0 for t in all_types}

        counts = {t: 0 for t in valid_tabs}
        cards = []
        modality_displays = {m["code"]: m["display_name"] for m in cfg["modalities"]}
        for filename, info in all_images.items():
            if modality != "all" and info.modality != modality:
                continue
            type_counts[info.cell_type] = type_counts.get(info.cell_type, 0) + 1
            if selected_types and info.cell_type not in selected_types:
                continue
            state = states.get(filename, {})
            is_unclassified = not state.get(good_key, 0) and not any(
                state.get(k, 0) for k in defect_keys
            )
            # one predicate drives both the tab counts and the card filter
            for t in valid_tabs:
                if _matches_tab(state, t, is_unclassified):
                    counts[t] += 1
            if not _matches_tab(state, tab, is_unclassified):
                continue
            cards.append(
                {
                    "filename": filename,
                    "name": os.path.splitext(filename)[0],
                    "modality_display": modality_displays.get(info.modality, info.modality),
                    "good": state.get(good_key, 0),
                    "defects": {k: state.get(k, 0) for k in defect_keys},
                    "preview_url": url_for("preview", file=filename),
                }
            )

        tabs = [
            {"key": "unclassified", "label": "Unclassified", "count": counts["unclassified"]},
            {
                "key": good_key,
                "label": cfg["labels"]["good"]["display_name"],
                "count": counts[good_key],
            },
        ]
        tabs.extend(
            {"key": d["key"], "label": d["display_name"], "count": counts[d["key"]]}
            for d in cfg["labels"]["defects"]
        )
        tabs.append({"key": "all", "label": "All", "count": counts["all"]})
        if not selected_types:
            cell_type_label = "All"
        elif len(selected_types) == 1:
            cell_type_label = selected_types[0]
        else:
            cell_type_label = f"{len(selected_types)} selected"

        return render_template(
            "main.html",
            user=session["name"],
            modalities=cfg["modalities"],
            modality=modality,
            tab=tab,
            tabs=tabs,
            cards=cards,
            selected_types=selected_types,
            cell_type_label=cell_type_label,
            cell_types=[{"value": t, "count": type_counts[t]} for t in all_types],
            good_key=good_key,
            good_label=cfg["labels"]["good"]["display_name"],
            defects=cfg["labels"]["defects"],
            defect_keys=defect_keys,
        )

    @app.route("/api/save", methods=["POST"])
    def api_save():
        """Persist the pending label changes of the Save button in one batch.

        Body: {"changes": {filename: {key: 0|1}}}. Everything is validated
        before the first write, so a failed request never partially persists.
        """
        if "name" not in session:
            return jsonify(ok=False, error="Not logged in"), 401
        data = request.get_json(silent=True) or {}
        changes = data.get("changes")
        if not isinstance(changes, dict) or not changes:
            return jsonify(ok=False, error="No changes to save"), 400
        all_images, _ = app.config["PV_INDEX"].get()
        updates = {}
        for filename, label_state in changes.items():
            filename = str(filename)
            info = all_images.get(filename)
            if info is None:
                return jsonify(ok=False, error=f"Unknown image: {filename}"), 404
            if not isinstance(label_state, dict):
                return jsonify(ok=False, error="Invalid label state"), 400
            updates[filename] = (info.modality, label_state)
        try:
            states = app.config["PV_STORE"].set_states(updates, session["name"])
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, states=states)

    @app.route("/api/group/<path:filename>")
    def api_group(filename):
        """Return the images of one group with their previews (JSON)."""
        if "name" not in session:
            return jsonify(ok=False, error="Not logged in"), 401
        all_images, groups = app.config["PV_INDEX"].get()
        info = all_images.get(filename)
        if info is None:
            return jsonify(ok=False, error="Unknown image"), 404
        members = []
        for modality in app.config["PV_CONFIG"]["modalities"]:
            code = modality["code"]
            variants = groups[info.group_key].get(code, {})
            if not variants:
                members.append(
                    {
                        "code": code,
                        "display_name": modality["display_name"],
                        "variant": None,
                        "filename": None,
                        "preview_url": None,
                    }
                )
            for variant in sorted(variants, key=lambda v: (v is not None, v or "")):
                member = variants[variant]
                members.append(
                    {
                        "code": code,
                        "display_name": modality["display_name"],
                        "variant": variant,
                        "filename": member.filename,
                        "preview_url": url_for("preview", file=member.filename),
                    }
                )
        return jsonify(ok=True, group_key=f"{info.cell_type}_{info.cell_id}", members=members)

    @app.route("/preview")
    def preview():
        """Serve the cached JPEG preview of one image file."""
        if "name" not in session:
            abort(401)
        filename = request.args.get("file", "")
        generator = app.config["PV_PREVIEWS"]
        try:
            cache_path = generator.get_preview_path(filename)
        except (ValueError, OSError, previews.PreviewError) as exc:
            app.logger.warning("Preview request failed for %r: %s", filename, exc)
            abort(404)
        return send_file(cache_path, mimetype="image/jpeg")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
