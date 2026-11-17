"""Tests for the comparison with external label sources (compare.py)."""

import csv
import os

import pytest

import compare
from compare import (
    TAB_AGREE,
    TAB_ALL,
    TAB_DIFF,
    TAB_NONE,
    TAB_UNCERTAIN,
    CompareStats,
    LabelStats,
    SourceCache,
    SourceResult,
    basename_index,
    compare_image,
    discover_sources,
    header_error,
    in_direction,
    load_source,
    matches_tab,
    parse_flag,
    read_header,
    resolve_image,
    tab_keys,
)

LABEL_KEYS = ["good", "crack", "dark", "discoloration"]

VI_1 = "23-P09-A/VI/23-P09-A1_VI_Cell001_normalized.tif"
EL_1 = "23-P09-A/EL/23-P09-A1_EL_Cell001_normalized.tif"
EL_2 = "23-P09-A/EL/23-P09-A1_EL_Cell002_normalized.tif"
EL_2_COPY = "other/23-P09-A1_EL_Cell002_normalized.tif"  # same basename as EL_2
FLAT = "flat_EL_Cell009.tif"
# compare.py only looks at the keys of the image index
IMAGES = dict.fromkeys([VI_1, EL_1, EL_2, EL_2_COPY, FLAT])

AI_ROOT = "/run/media/user/Volume/normalized_images"
AI_COLUMNS = [
    "date",
    "time",
    "model",
    "image_path",
    "file_name",
    "good",
    "crack",
    "dark",
    "discoloration",
    "uncertain",
    "valid_result",
    "visual_status",
]


def write_csv(path, columns, rows, delimiter=",", encoding="utf-8"):
    with open(path, "w", newline="", encoding=encoding) as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(columns)
        writer.writerows(rows)
    return str(path)


def ai_row(path, name=None, uncertain="0", valid="1", note="", **labels):
    """One row in the AI result schema; labels missing from **labels stay empty."""
    name = path.rsplit("/", 1)[-1] if name is None else name
    values = [labels.get(key, "") for key in LABEL_KEYS]
    return ["2026-11-01", "16:50:05", "gpt-test", path, name, *values, uncertain, valid, note]


def result(values, valid=True, uncertain=False, note=None):
    return SourceResult({key: values.get(key) for key in LABEL_KEYS}, valid, uncertain, note)


def state(**labels):
    return {key: labels.get(key, 0) for key in LABEL_KEYS}


# -- parsing -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1),
        (" 0 ", 0),
        ("1.0", 1),
        ("0.0", 0),
        ("True", 1),
        ("false", 0),
        ("", None),
        ("nan", None),
        ("maybe", None),
        (None, None),
    ],
)
def test_parse_flag(raw, expected):
    assert parse_flag(raw) == expected


def test_read_header_handles_bom_and_semicolons(tmp_path):
    """Excel exports (BOM, semicolons, odd casing) still yield clean column names."""
    path = write_csv(
        tmp_path / "excel.csv",
        [" Image_Path", "GOOD", "crack"],
        [["a.tif", "1", "0"]],
        delimiter=";",
        encoding="utf-8-sig",
    )
    assert read_header(path) == (["image_path", "good", "crack"], ";")


def test_header_error():
    assert header_error(["image_path", "good"], LABEL_KEYS) is None
    assert header_error(["file_name", "dark"], LABEL_KEYS) is None
    assert "Bildspalte" in header_error(["good", "crack"], LABEL_KEYS)
    assert "Labelspalten" in header_error(["filename", "labels", "reason"], LABEL_KEYS)


def test_discover_sources(tmp_path):
    """Only top-level CSV files are offered, labels.csv never; headers are checked."""
    write_csv(tmp_path / "labels.csv", ["image_path", "good"], [])
    write_csv(tmp_path / "results gpt.csv", ["image_path", "good"], [])
    write_csv(tmp_path / "AI2.CSV", ["file_name", "crack"], [])
    write_csv(tmp_path / "labels_failed.csv", ["filename", "labels", "reason"], [])
    (tmp_path / "notes.txt").write_text("not a csv", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    write_csv(tmp_path / "sub" / "nested.csv", ["image_path", "good"], [])

    files = discover_sources(str(tmp_path), LABEL_KEYS, exclude=[str(tmp_path / "labels.csv")])
    assert [f.id for f in files] == ["AI2.CSV", "labels_failed.csv", "results gpt.csv"]
    errors = {f.id: f.error for f in files}
    assert errors["results gpt.csv"] is None
    assert errors["AI2.CSV"] is None
    assert "Labelspalten" in errors["labels_failed.csv"]
    assert files[0].path == os.path.join(str(tmp_path), "AI2.CSV")


def test_discover_sources_missing_directory(tmp_path):
    assert discover_sources(str(tmp_path / "missing"), LABEL_KEYS) == []


# -- image resolution --------------------------------------------------------


def test_resolve_image():
    basenames = basename_index(IMAGES)
    # an absolute path from another machine resolves via its relative suffix
    assert resolve_image(f"{AI_ROOT}/{VI_1}", IMAGES, basenames) == VI_1
    # Windows separators and drive letters
    windows = "C:\\Thesis\\normalized_images\\" + EL_1.replace("/", "\\")
    assert resolve_image(windows, IMAGES, basenames) == EL_1
    # the longest existing suffix wins, so equal basenames in other folders stay apart
    assert resolve_image(f"{AI_ROOT}/{EL_2}", IMAGES, basenames) == EL_2
    assert resolve_image(f"{AI_ROOT}/{EL_2_COPY}", IMAGES, basenames) == EL_2_COPY
    # relative paths match directly
    assert resolve_image(f" {FLAT} ", IMAGES, basenames) == FLAT
    # a unique basename is the fallback when the folders differ
    elsewhere = "/elsewhere/{}".format
    assert (
        resolve_image(elsewhere("23-P09-A1_VI_Cell001_normalized.tif"), IMAGES, basenames) == VI_1
    )
    # an ambiguous basename, an unknown image and an empty cell do not resolve
    assert (
        resolve_image(elsewhere("23-P09-A1_EL_Cell002_normalized.tif"), IMAGES, basenames) is None
    )
    assert resolve_image(f"{AI_ROOT}/nope_EL_Cell777.tif", IMAGES, basenames) is None
    assert resolve_image("   ", IMAGES, basenames) is None


# -- loading -------------------------------------------------------------------


def test_load_source_ai_schema(tmp_path):
    """The AI result schema: empty cells, flags, notes, duplicates and unmatched rows."""
    rows = [
        ai_row(f"{AI_ROOT}/{VI_1}", good="0", discoloration="1", uncertain="1", note="yellow"),
        ai_row(f"{AI_ROOT}/{EL_1}", good="1", crack="0", dark="0"),
        ai_row(f"{AI_ROOT}/{EL_2}", good="0", crack="1", valid="0", note="API error"),
        # image_path does not resolve, the file_name column does
        ai_row("/nowhere/x.tif", name=FLAT, good="1", crack="0", dark="0"),
        ai_row(f"{AI_ROOT}/missing_EL_Cell777.tif", good="1"),
        [""] * len(AI_COLUMNS),  # blank lines are skipped
        # a later run of the same image overrides the first one
        ai_row(f"{AI_ROOT}/{VI_1}", good="0", discoloration="0", uncertain="1", note="redo"),
    ]
    path = write_csv(tmp_path / "ai.csv", AI_COLUMNS, rows)
    source = load_source(path, "ai.csv", LABEL_KEYS, IMAGES)

    assert source.error is None
    assert source.name == "ai"
    assert source.detail == "gpt-test"
    assert source.label_keys == LABEL_KEYS
    assert source.has_uncertain
    assert source.rows == 6
    assert source.duplicates == 1
    assert source.unmatched == 1
    assert source.unmatched_samples == [f"{AI_ROOT}/missing_EL_Cell777.tif"]
    assert set(source.results) == {VI_1, EL_1, EL_2, FLAT}

    vi = source.results[VI_1]
    assert vi.values == {"good": 0, "crack": None, "dark": None, "discoloration": 0}
    assert (vi.valid, vi.uncertain, vi.note) == (True, True, "redo")
    el = source.results[EL_1]
    assert el.values == {"good": 1, "crack": 0, "dark": 0, "discoloration": None}
    assert (el.valid, el.uncertain, el.note) == (True, False, None)
    assert not source.results[EL_2].valid  # valid_result=0
    assert source.results[EL_2].note == "API error"
    assert source.results[FLAT].values["good"] == 1


def test_load_source_labels_schema(tmp_path):
    """A file in the labels.csv schema works as source (second labeler, ground truth)."""
    columns = ["date", "time", "labeler", "image_path", "uv", "vi", "el", *LABEL_KEYS]
    path = write_csv(
        tmp_path / "ground_truth.csv",
        columns,
        [
            ["", "", "GroundTruth", EL_1, "0", "0", "1", "0", "1", "1", "0"],
            ["", "", "GroundTruth", VI_1, "0", "1", "0", "1", "0", "0", "0"],
        ],
    )
    source = load_source(path, "ground_truth.csv", LABEL_KEYS, IMAGES)
    assert source.error is None
    assert source.detail == "GroundTruth"
    assert not source.has_uncertain
    assert source.results[EL_1].values == {"good": 0, "crack": 1, "dark": 1, "discoloration": 0}
    assert source.results[VI_1].valid


def test_load_source_missing_label_columns_fall_back_to_not_assessed(tmp_path):
    """Configured labels without a column count as not assessed for every image."""
    path = write_csv(tmp_path / "partial.csv", ["file_name", "good"], [[FLAT, "1"], [EL_1, ""]])
    source = load_source(path, "partial.csv", LABEL_KEYS, IMAGES)
    assert source.label_keys == ["good"]
    assert source.results[FLAT].values == {**dict.fromkeys(LABEL_KEYS), "good": 1}
    # a row without a single assessed label is unusable
    assert not source.results[EL_1].valid


def test_load_source_errors(tmp_path):
    path = write_csv(tmp_path / "failed.csv", ["filename", "labels", "reason"], [["a", "b", "c"]])
    assert "Labelspalten" in load_source(path, "failed.csv", LABEL_KEYS, IMAGES).error
    missing = load_source(str(tmp_path / "gone.csv"), "gone.csv", LABEL_KEYS, IMAGES)
    assert missing.error.startswith("nicht lesbar")
    assert missing.results == {}


# -- comparing -----------------------------------------------------------------


def test_compare_image_ignores_unassessed_labels():
    cmp = compare_image(
        state(crack=1),
        [result({"good": 0, "crack": 0, "dark": None, "discoloration": 1})],
        LABEL_KEYS,
    )
    assert cmp.labeled
    (source,) = cmp.sources
    assert source.status == compare.STATUS_OK
    # dark is not assessed by the source, so it is no difference
    assert source.diffs == {"crack", "discoloration"}


def test_compare_image_unlabeled_missing_and_invalid():
    results = [None, result({"good": 1}, valid=False, note="API error"), result({"good": 1})]
    cmp = compare_image(state(), results, LABEL_KEYS)
    assert not cmp.labeled
    missing, invalid, ok = cmp.sources
    assert missing.status == compare.STATUS_MISSING
    assert missing.values == dict.fromkeys(LABEL_KEYS)
    assert invalid.status == compare.STATUS_INVALID
    assert invalid.note == "API error"
    # an unlabeled image is never compared, even with a valid result
    assert ok.status == compare.STATUS_OK and not ok.diffs


def test_tab_keys_single_source():
    differing = compare_image(state(good=1), [result({"good": 0, "crack": 1})], LABEL_KEYS)
    assert tab_keys(differing, None) == [TAB_ALL, TAB_DIFF, "crack", "good"]
    agreeing = compare_image(state(good=1), [result({"good": 1}, uncertain=True)], LABEL_KEYS)
    assert tab_keys(agreeing, None) == [TAB_ALL, TAB_AGREE, TAB_UNCERTAIN]
    unlabeled = compare_image(state(), [result({"good": 1})], LABEL_KEYS)
    assert tab_keys(unlabeled, None) == [TAB_ALL, TAB_NONE]
    missing = compare_image(state(good=1), [None], LABEL_KEYS)
    assert tab_keys(missing, None) == [TAB_ALL, TAB_NONE]


def test_tab_keys_scope_with_two_sources():
    """The scope narrows the evaluation to one source; None means any source."""
    cmp = compare_image(
        state(crack=1),
        [result({"crack": 1}), result({"crack": 0, "good": 0})],
        LABEL_KEYS,
    )
    assert tab_keys(cmp, None) == [TAB_ALL, TAB_DIFF, "crack"]
    assert tab_keys(cmp, 0) == [TAB_ALL, TAB_AGREE]
    assert tab_keys(cmp, 1) == [TAB_ALL, TAB_DIFF, "crack"]
    # B without a result: comparable through A only
    partial = compare_image(state(crack=1), [result({"crack": 1}), None], LABEL_KEYS)
    assert tab_keys(partial, None) == [TAB_ALL, TAB_AGREE]
    assert tab_keys(partial, 1) == [TAB_ALL, TAB_NONE]


def test_direction_filter():
    """Within a label tab the stored value tells which side set the label."""
    missed = compare_image(state(crack=1), [result({"crack": 0})], LABEL_KEYS)
    extra = compare_image(state(good=1), [result({"good": 1, "crack": 1})], LABEL_KEYS)
    assert in_direction(missed, "crack", compare.ONLY_LABELER)
    assert not in_direction(missed, "crack", compare.ONLY_SOURCE)
    assert in_direction(extra, "crack", compare.ONLY_SOURCE)
    assert in_direction(extra, "crack", "")
    assert matches_tab(missed, "crack", None, compare.ONLY_LABELER)
    assert not matches_tab(extra, "crack", None, compare.ONLY_LABELER)
    assert matches_tab(extra, "crack", None, compare.ONLY_SOURCE)
    assert not matches_tab(extra, "good", None)  # good agrees
    assert matches_tab(extra, TAB_ALL, None)


# -- statistics ----------------------------------------------------------------


def test_compare_stats_counts():
    stats = CompareStats(1, LABEL_KEYS)
    cases = [
        (state(crack=1), result({"good": 0, "crack": 1})),  # crack tp, agree
        (state(crack=1), result({"good": 0, "crack": 0})),  # crack fn
        (state(good=1), result({"good": 1, "crack": 1})),  # crack fp, good conflict
        (state(good=1), result({"good": 1, "crack": 0}, uncertain=True)),  # crack tn
        (state(), result({"good": 1})),  # unlabeled
        (state(good=1), None),  # missing
        (state(good=1), result({"good": 1}, valid=False)),  # invalid
    ]
    for human, res in cases:
        stats.add(compare_image(human, [res], LABEL_KEYS))
    (source,) = stats.sources
    assert (source.compared, source.agree) == (4, 2)
    assert (source.unlabeled, source.missing, source.invalid, source.uncertain) == (1, 1, 1, 1)
    assert source.agreement == 0.5
    crack = source.labels["crack"]
    assert (crack.tp, crack.fn, crack.fp, crack.tn) == (1, 1, 1, 1)
    good = source.labels["good"]
    assert (good.tp, good.fn, good.fp, good.tn) == (2, 0, 0, 2)
    assert source.labels["dark"].n == 0  # never assessed


def test_label_stats_metrics():
    counts = LabelStats()
    counts.tp, counts.fn, counts.fp, counts.tn = 2, 1, 1, 4
    assert counts.n == 8
    assert counts.agreement == pytest.approx(0.75)
    assert counts.precision == pytest.approx(2 / 3)
    assert counts.recall == pytest.approx(2 / 3)
    assert counts.f1 == pytest.approx(2 / 3)
    # kappa = (p_o - p_e) / (1 - p_e) with p_e = (3*3 + 5*5) / 64
    expected = (0.75 - 34 / 64) / (1 - 34 / 64)
    assert counts.kappa == pytest.approx(expected)


def test_label_stats_undefined_metrics():
    empty = LabelStats()
    assert empty.agreement is None and empty.kappa is None and empty.f1 is None
    only_negatives = LabelStats()
    only_negatives.tn = 5
    assert only_negatives.agreement == 1.0
    # one class on both sides: precision, recall, F1 and kappa are undefined
    assert only_negatives.precision is None
    assert only_negatives.recall is None
    assert only_negatives.f1 is None
    assert only_negatives.kappa is None


# -- cache ---------------------------------------------------------------------


def test_source_cache_reloads_on_file_or_image_change(tmp_path):
    path = write_csv(tmp_path / "ai.csv", ["file_name", "good"], [[FLAT, "1"]])
    cache = SourceCache()
    first = cache.get(path, "ai.csv", LABEL_KEYS, IMAGES)
    assert cache.get(path, "ai.csv", LABEL_KEYS, IMAGES) is first
    # a changed file is parsed again
    write_csv(tmp_path / "ai.csv", ["file_name", "good"], [[FLAT, "0"], [EL_1, "1"]])
    second = cache.get(path, "ai.csv", LABEL_KEYS, IMAGES)
    assert second is not first
    assert second.results[FLAT].values["good"] == 0
    # a rescanned image index (new dict object) remaps the rows
    third = cache.get(path, "ai.csv", LABEL_KEYS, dict(IMAGES))
    assert third is not second
