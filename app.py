"""Multispectral solar-cell image labeling tool (Flask app).

Implements specification/specification.md: name-based login, gallery with
modality dropdown and label-filter tabs, checkbox labeling with the Good
exclusivity rules, group view pop-up and CSV/change-log persistence.
"""

import hashlib
import json
import os
import re
import tempfile

from flask import (
    Flask,
    Response,
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


def load_config(path: str = CONFIG_PATH) -> dict:
    """Load and validate config.json (specification §3.3)."""
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    _validate_config(config)
    return config


def _validate_config(config: dict) -> None:
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
        preview_min = modality.get("preview_min")
        preview_max = modality.get("preview_max")
        if (preview_min is None) != (preview_max is None):
            raise ValueError(
                f"config.json: modality {code!r}: "
                "'preview_min' and 'preview_max' must be set together"
            )
        if preview_min is not None and (
            isinstance(preview_min, bool)
            or isinstance(preview_max, bool)
            or not isinstance(preview_min, (int, float))
            or not isinstance(preview_max, (int, float))
            or preview_max <= preview_min
        ):
            raise ValueError(
                f"config.json: modality {code!r}: 'preview_min' must be < 'preview_max'"
            )
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

    for key in ("modal_max_width", "modal_max_height"):
        value = config.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 200
        ):
            raise ValueError(f"config.json: '{key}' must be an integer >= 200")


def _matches_tab(state: dict, tab: str, is_unclassified: bool) -> bool:
    """Return whether a label state belongs to the given tab view."""
    if tab == "unclassified":
        return is_unclassified
    if tab == "all":
        return True
    return bool(state.get(tab, 0))


def create_app(
    config: dict | None = None,
    images_dir: str | None = None,
    labels_csv: str | None = None,
    change_log: str | None = None,
    previews_dir: str | None = None,
    config_path: str | None = None,
) -> Flask:
    """Create the Flask app wired to the given config and storage locations.

    config_path is the file the preview-window endpoint writes back to; it
    defaults to config.json when the app loads its own config from disk and
    is None (no write-back) when a config dict is passed without a path.
    """
    app = Flask(__name__)
    app.secret_key = os.environ.get("PV_LABLER_SECRET_KEY", "dev-secret-key-change-me")
    if config is None:
        config = load_config()
        config_path = config_path if config_path is not None else CONFIG_PATH
    app.config["PV_CONFIG_PATH"] = config_path
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
    app.config["PV_PREVIEW_WINDOWS"] = {
        m["code"]: (m["preview_min"], m["preview_max"])
        for m in config["modalities"]
        if "preview_min" in m
    }

    @app.route("/")
    def index() -> Response | str:
        """Render the login page, or redirect a logged-in user to main."""
        if "name" in session:
            return redirect(url_for("main"))
        return render_template("login.html")

    @app.route("/login", methods=["POST"])
    def login() -> Response | tuple[str, int]:
        """Store the submitted user name in the session and redirect to main."""
        name = (request.form.get("name") or "").strip()
        if not name:
            return render_template("login.html", error="Please enter your name."), 400
        session["name"] = name
        return redirect(url_for("main"))

    @app.route("/logout")
    def logout() -> Response:
        """Clear the session and return to the login page."""
        session.clear()
        return redirect(url_for("index"))

    @app.route("/main")
    def main() -> Response | str:
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
        # preview-window info: slider range (probed from the first image of the
        # selected modality) and a per-window cache-busting signature for URLs
        preview_range = 255.0
        if modality != "all":
            for info in all_images.values():
                if info.modality == modality:
                    preview_range = previews.probe_data_range(
                        os.path.join(app.config["PV_IMAGES_DIR"], info.filename)
                    )
                    break
        window_sig = {
            m["code"]: hashlib.md5(
                repr(app.config["PV_PREVIEW_WINDOWS"].get(m["code"])).encode()
            ).hexdigest()[:8]
            for m in cfg["modalities"]
        }
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
                    "name": os.path.splitext(os.path.basename(filename))[0],
                    "modality_display": modality_displays.get(info.modality, info.modality),
                    "good": state.get(good_key, 0),
                    "defects": {k: state.get(k, 0) for k in defect_keys},
                    "preview_url": url_for("preview", file=filename, v=window_sig[info.modality]),
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

        modal_height = cfg.get("modal_max_height", "90vh")
        modal_max_height = f"{modal_height}px" if isinstance(modal_height, int) else modal_height

        preview_window = app.config["PV_PREVIEW_WINDOWS"].get(modality)
        preview_window_min = preview_window[0] if preview_window else 0
        preview_window_max = preview_window[1] if preview_window else preview_range
        preview_window_label = (
            f"{preview_window_min:g} – {preview_window_max:g}" if preview_window else "Standard"
        )
        if preview_range >= 65535:
            preview_bits = "16-Bit"
        elif preview_range > 1:
            preview_bits = "8-Bit"
        else:
            preview_bits = "Float"

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
            modal_max_width=cfg.get("modal_max_width", 1100),
            modal_max_height=modal_max_height,
            preview_window_label=preview_window_label,
            preview_window_min=preview_window_min,
            preview_window_max=preview_window_max,
            preview_range=preview_range,
            preview_bits=preview_bits,
        )

    @app.route("/api/save", methods=["POST"])
    def api_save() -> Response:
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
    def api_group(filename: str) -> Response:
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
    def preview() -> Response:
        """Serve the cached JPEG preview of one image file."""
        if "name" not in session:
            abort(401)
        filename = request.args.get("file", "")
        generator = app.config["PV_PREVIEWS"]
        info = app.config["PV_INDEX"].get()[0].get(filename)
        window = app.config["PV_PREVIEW_WINDOWS"].get(info.modality) if info is not None else None
        try:
            cache_path = generator.get_preview_path(filename, window=window)
        except (ValueError, OSError, previews.PreviewError) as exc:
            app.logger.warning("Preview request failed for %r: %s", filename, exc)
            abort(404)
        return send_file(cache_path, mimetype="image/jpeg")

    @app.route("/api/original/<path:filename>")
    def api_original(filename: str) -> Response:
        """Serve the original image file for the in-app original view."""
        if "name" not in session:
            return jsonify(ok=False, error="Not logged in"), 401
        try:
            source = app.config["PV_PREVIEWS"].resolve_source(filename)
        except ValueError:
            abort(404)
        if not os.path.isfile(source):
            abort(404)
        return send_file(source, mimetype="image/tiff")

    @app.route("/api/preview-window", methods=["POST"])
    def api_preview_window() -> Response:
        """Update or reset the preview window of one modality in config.json."""
        if "name" not in session:
            return jsonify(ok=False, error="Not logged in"), 401
        config_path = app.config.get("PV_CONFIG_PATH")
        if not config_path:
            return jsonify(ok=False, error="Config is not file-backed"), 400
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "")
        current = app.config["PV_CONFIG"]
        if code not in [m["code"] for m in current["modalities"]]:
            return jsonify(ok=False, error="Unknown modality"), 400
        new_config = json.loads(json.dumps(current))
        entry = next(m for m in new_config["modalities"] if m["code"] == code)
        if data.get("reset"):
            entry.pop("preview_min", None)
            entry.pop("preview_max", None)
        else:
            try:
                lo = float(data["min"])
                hi = float(data["max"])
            except (KeyError, TypeError, ValueError):
                return jsonify(ok=False, error="min and max are required"), 400
            if hi <= lo:
                return jsonify(ok=False, error="min must be < max"), 400
            entry["preview_min"] = lo
            entry["preview_max"] = hi
        try:
            _validate_config(new_config)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        # atomic write back, then swap the running config
        directory = os.path.dirname(os.path.abspath(config_path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, config_path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        app.config["PV_CONFIG"] = new_config
        app.config["PV_PREVIEW_WINDOWS"] = {
            m["code"]: (m["preview_min"], m["preview_max"])
            for m in new_config["modalities"]
            if "preview_min" in m
        }
        return jsonify(ok=True)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
