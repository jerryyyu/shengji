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
    before, c0 = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows)
    r = next(x for x in rows2 if x["ck"] == "c6d48d57")  # volVOL-144k, on the base_v2 line
    r["ce"] = "0.60100"  # below every on-scale CE today (best 0.60570)
    after, c = _render(rows2, table_only, series)
    assert "0.60100" in _registry_cell(after, "c6d48d57", 7)
    assert "0.60100" in after.split("{{")[0]  # registry
    # the day table's running best and the chart's best line both moved
    assert re.search(r"<td>10 Sep</td><td class=\"n\">\d+</td><td class=\"n\">0.60100", after)
    assert c["best_ce"] == 0.601 and c["best_day"] == "2026-09-10"
    assert "unbeaten since 10 Sep" in after
    assert f"unbeaten since {c0['best_day'][8:]} Sep" in before
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
    assert c["without_leader"] == c0["without_leader"] + 1
    # trained AFTER the best only if its day is later than the best's day
    assert c["since_best"] == c0["since_best"] + (1 if "2026-09-12" > c0["best_day"] else 0)
    assert f"{c['rows']} checkpoints; {c['models']} on the charts, {c['with_ce']} of them" in page
    assert f"{c['without_leader']} of {c['models']}</b><span>no search number yet" in page
    base, _ = _render(rows, table_only, series)
    count = lambda p: int((re.search(r"<td>12 Sep</td><td class=\"n\">(\d+)</td>", p) or [None, 0])[1])
    assert count(page) == count(base) + 1  # the by-day table gained the row on its day


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


def _circles(svg):
    return [(float(cx), float(cy)) for cx, cy in re.findall(r'<circle cx="([-0-9.]+)" cy="([-0-9.]+)"', svg)]


def test_every_plotted_dot_is_inside_its_chart_and_off_scale_models_are_named(data):
    """Codex's witness on #364: a CE above the axis must be visibly listed, never
    emitted as an off-canvas circle."""
    page, c = _render(*data)
    svgs = re.findall(r'<svg viewBox="0 0 (\d+) (\d+)">(.*?)</svg>', page, re.S)
    assert len(svgs) == 6
    for w, h, body in svgs:
        for cx, cy in _circles(body):
            assert 0 <= cx <= float(w) and 0 <= cy <= float(h), (cx, cy, w, h)
    assert c["off_scale"], "the smean-96k row (CE 1.675) is above the 0.74 axis today"
    for name, ce in c["off_scale"]:
        assert f"OFF THIS SCALE" in page and f"{name}: CE {ce:.3f}" in page
        assert f"{name} (CE {ce:.3f}) is above the CE axis" in page
    # and the on-scale count excludes it
    assert c["with_ce"] == sum(1 for r in data[0] if r["ce"] and float(r["ce"]) <= 0.74 and r["ck"] not in data[1])


def test_removing_the_off_scale_row_removes_the_note(data):
    rows, table_only, series = data
    rows2 = [r for r in rows if r["ck"] != "8a6d5260"]
    page, c = _render(rows2, table_only, series)
    assert not c["off_scale"] and "OFF THIS SCALE" not in page and "above the CE axis" not in page


def _play_cells(page):
    """checkpoint prefix -> the consolidated play cell's text (tags stripped)."""
    out = {}
    for row in re.findall(r"<tr[^>]*>(?:(?!</tr>).)*</tr>", page, re.S):
        tds = re.findall(r"<td[^>]*>.*?</td>", row, re.S)
        if len(tds) == 11:  # the registry has 11 columns after the merge
            ck = re.search(r'<span class="mono null">([0-9a-f]{8}|arm[IJ])</span>', tds[0])
            if ck:
                out[ck.group(1)] = re.sub(r"<[^>]+>", " ", tds[9])
    return out


def test_the_three_play_instruments_render_as_one_badged_column(data):
    page, c = _render(*data)
    assert page.count("<th") and "Play vs leader" in page and "vs W32 leader" not in page
    cells = _play_cells(page)
    assert len(cells) == c["rows"]
    # ten windows first (bold), then the superseded one-window pairing, then the MC-LCB number
    full = cells["8d92dd6e"]  # lr 1e-4, full mixture
    assert full.index("+0.0037") < full.index("10w") < full.index("0.0587") < full.index("superseded") < full.index("+0.0673")
    assert "1w paired" in full and "MC" in full
    assert '<b>+0.0037 [&#8209;0.0119, +0.0192] <span class="pill inst">10w</span></b>' in page
    # a model with only the one-window pairing shows it first with its own badge
    w = cells["d84b5183"]  # width 1024, lr 1e-4
    assert w.index("0.0337") < w.index("1w paired") < w.index("+0.0923") < w.index("MC")
    assert cells["3cd27716"].strip().startswith("— reference") or "reference" in cells["3cd27716"]
    assert "the control" in cells["ca58e1e9"] and "codex 260" in cells["5b43322f"]
    assert "queued" in cells["4dc21822"] and "never paired" not in cells["4dc21822"]  # queued for the leader: not a gap
    assert "never paired" in cells["528dbbe0"]  # a gap with nothing queued
    # the caption's MDE80s are derived from the intervals on the page (ten windows: ~0.023)
    assert 0.020 <= c["mde"]["10w"] <= 0.026 and c["mde"]["1w"] > c["mde"]["10w"]
    assert f"MDE80 about {c['mde']['10w']:.3f}" in page and "has no readout yet" in page


def test_a_five_window_cell_is_badged_counted_and_charted_separately(data):
    rows, table_only, series = data
    _, c0 = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows)
    next(x for x in rows2 if x["ck"] == "fc73c0f4")["ten"] = "5w +0.0105 [-0.0100, +0.0310]"
    page, c = _render(rows2, table_only, series)
    assert c["five_total"] == 1 and c["five_cross"] == 1 and c["ten_total"] == c0["ten_total"] - 1
    cell = _play_cells(page)["fc73c0f4"]
    assert "+0.0105" in cell and "5w" in cell and "10w" not in cell
    assert 'class="pt pt7"' in page and "five windows (wider)" in page  # legend + hollow marker
    assert "a null there means not large" in page and "has no readout yet" not in page
    assert f"MDE80 about {c['mde']['5w']:.3f}" in page and abs(c["mde"]["5w"] - 0.0205 * build.MDE_PER_HALFWIDTH) < 1e-6
    base, _ = _render(rows, table_only, series)
    assert 'class="pt pt7"' not in base and "five windows (wider)" not in base


@pytest.mark.parametrize("field,value,msg", [
    ("w32", "5w +0.1000 [+0.0500, +0.1500]", "belongs only in the ten-window field"),
    ("ten", "7w +0.1000 [+0.0500, +0.1500]", "neither a keyword"),
])
def test_window_prefixes_are_validated(data, field, value, msg):
    rows, table_only, series = data
    rows2 = copy.deepcopy(rows)
    rows2[0][field] = value
    errs = build.check_data(rows2, table_only, series)
    assert errs and any(msg in e for e in errs), errs
