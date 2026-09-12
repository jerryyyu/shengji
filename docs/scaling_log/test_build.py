"""Consumer tests for the scaling log generator: a change in models.py must reach
the charts, the tables AND the headline prose together, and malformed rows must
be refused.  Run: python3 -m pytest docs/scaling_log/test_build.py -q"""
import copy
import importlib.util
import re
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("scaling_build", Path(__file__).with_name("build.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


@pytest.fixture(scope="module")
def data():
    return build.load()


def _render(rows, table_only, series):
    page, c = build.render(copy.deepcopy(rows), set(table_only), copy.deepcopy(series))
    return page, c


def _registry_cell(page, ck, col):
    row = re.search(r'<tr[^>]*>(?:(?!</tr>).)*' + ck + r'(?:(?!</tr>).)*</tr>', page, re.S).group(0)
    return re.sub(r"<[^>]+>", "", re.findall(r"<td[^>]*>.*?</td>", row, re.S)[col])


def test_baseline_renders_and_matches_the_committed_page(data):
    page, c = _render(*data)
    assert page == open(Path(__file__).with_name("scaling.html")).read()
    assert c["ten_total"] == c["ten_cross"]  # today: every ten-window arm crosses zero


def test_changing_a_val_ce_moves_the_chart_dot_the_registry_and_the_day_table(data):
    rows, table_only, series = data
    before, _ = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows)
    r = next(x for x in rows2 if x["ck"] == "c6d48d57")  # volVOL-144k, on the base_v2 line
    r["ce"] = "0.60100"
    after, c = _render(rows2, table_only, series)
    assert "0.60100" in _registry_cell(after, "c6d48d57", 7)
    assert "0.60100" in after.split("{{")[0]  # registry
    # the day table's running best and the chart's best line both moved
    assert re.search(r"<td>10 Sep</td><td class=\"n\">\d+</td><td class=\"n\">0.60100", after)
    assert c["best_ce"] == 0.601 and c["best_day"] == "2026-09-10"
    assert "unbeaten since 10 Sep" in after and "unbeaten since 08 Sep" in before
    # chart 1's base_v2 polyline changed (coordinates come from the row)
    poly = lambda p: re.findall(r'<polyline class="ln ln2" points="([^"]+)"', p)[0]
    assert poly(before) != poly(after)


def test_adding_a_model_updates_every_count(data):
    rows, table_only, series = data
    _, c0 = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows) + [dict(zip(build.FIELDS, (
        "new arm", "0badf00d", "2026-09-12", "v2", 512, "3e-4", "96k", "14,077,520", "0.62000", "",
        "", "", "", "a test row")))]
    page, c = _render(rows2, table_only, series)
    assert c["rows"] == c0["rows"] + 1 and c["models"] == c0["models"] + 1 and c["with_ce"] == c0["with_ce"] + 1
    assert c["without_leader"] == c0["without_leader"] + 1 and c["since_best"] == c0["since_best"] + 1
    assert f"{c['rows']} checkpoints; {c['models']} on the charts, {c['with_ce']} of them" in page
    assert f"{c['without_leader']} of {c['models']}</b><span>no search number yet" in page
    assert re.search(r"<td>12 Sep</td><td class=\"n\">1</td>", page)


def test_a_positive_ten_window_interval_changes_the_headline_and_the_kpi(data):
    rows, table_only, series = data
    rows2 = copy.deepcopy(rows)
    r = next(x for x in rows2 if x["ck"] == "fc73c0f4")
    r["ten"] = "+0.1000 [+0.0500, +0.1500]"
    page, c = _render(rows2, table_only, series)
    assert c["ten_cross"] == c["ten_total"] - 1 and c["above_leader"] >= 1
    assert f"{build.word(c['ten_cross'])} cross zero and one resolves" in page
    assert "all " + build.word(c["ten_total"]) + " cross zero" not in page
    assert f"{c['above_leader']} of {c['with_leader']}</b><span>models above the leader" in page
    # the whole page, not only the KPI: the section-1b sentence follows the same rows
    assert "None beats the current one." not in page and "One beats the current one." in page


def test_chart_series_follow_checkpoint_identity_not_typed_numbers(data):
    rows, table_only, series = data
    rows2 = copy.deepcopy(rows)
    r = next(x for x in rows2 if x["ck"] == "e2436f98")  # h2048 on the 144k width line
    r["ce"] = "0.70000"
    page, c = _render(rows2, table_only, series)
    y_of = lambda p: [float(v) for v in re.findall(r'<polyline class="ln ln5" points="([^"]+)"', p)[0].split()[-1].split(",")][1]
    base, _ = _render(rows, table_only, series)
    assert y_of(page) < y_of(base)  # a higher val_ce draws the last point (h2048) higher up the SVG (smaller y)
    assert "smaller is monotonically better" in page  # still monotone: h2048 only got worse


def test_breaking_the_width_ordering_rewrites_the_width_caption(data):
    rows, table_only, series = data
    rows2 = copy.deepcopy(rows)
    next(x for x in rows2 if x["ck"] == "fc73c0f4")["ce"] = "0.63000"  # h256 now the worst at 144k
    page, c = _render(rows2, table_only, series)
    assert not c["w144_monotone"]
    assert "smaller is monotonically better" not in page
    assert "the ordering is not monotone in width: h512 is best and h256 is worst" in page
    assert "The gold line runs opposite to the red." not in page


def test_a_leader_number_at_a_small_corpus_rewrites_the_coverage_sentence(data):
    rows, table_only, series = data
    base, c0 = _render(rows, table_only, series)
    assert f"nothing below {c0['min_leader_records'] / 1e6:.1f}M records has one" in base
    rows2 = copy.deepcopy(rows)
    next(x for x in rows2 if x["ck"] == "bd973b53")["w32"] = "-0.0100 [-0.0300, +0.0100]"  # run A, 8k
    page, c = _render(rows2, table_only, series)
    assert c["sizes_with_leader"] == c0["sizes_with_leader"] + 1 and c["min_leader_records"] == 1168124
    assert "nothing below 1.2M records has one" in page


@pytest.mark.parametrize("field,value,msg", [
    ("tr", "2026-99-99", "calendar date"),
    ("ten", "+0.1000 [+0.2000, -0.2000]", "not ordered"),
    ("ten", "+0.1000 [+0.0500, +0.1500] trailing", "neither a keyword"),
    ("mc", "+0.1 [+0.05, +0.15]", "neither a keyword"),
    ("ck", "notahash", "8-hex"),
])
def test_malformed_rows_are_refused(data, field, value, msg):
    rows, table_only, series = data
    rows2 = copy.deepcopy(rows)
    rows2[0][field] = value
    errs = build.check_data(rows2, table_only, series)
    assert errs and any(msg in e for e in errs), errs
    with pytest.raises(SystemExit):
        build.render(rows2, set(table_only), copy.deepcopy(series))


def test_a_series_naming_an_unknown_or_table_only_checkpoint_is_refused(data):
    rows, table_only, series = data
    s2 = copy.deepcopy(series)
    s2["base_v2"].append("c50d95ef")  # table-only probe
    assert any("table-only" in e for e in build.check_data(rows, table_only, s2))
    s2["base_v2"][-1] = "deadbeef"
    assert any("not a row" in e for e in build.check_data(rows, table_only, s2))
