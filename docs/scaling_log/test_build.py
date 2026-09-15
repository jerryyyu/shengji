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
    # 09-14: M1's outcome head is the one ten-window interval that excludes zero (by 0.0007)
    assert c["ten_total"] == c["ten_cross"] + 1 and c["above_leader"] == 1
    assert "One nominal interval clears zero; independent confirmation is pending." in page
    assert "beats the current one" not in page


def test_changing_a_val_ce_moves_the_chart_dot_the_registry_and_the_day_table(data):
    rows, table_only, series = data
    before, c0 = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows)
    r = next(x for x in rows2 if x["ck"] == "c6d48d57")  # volVOL-144k, on the base_v2 line
    r["ce"] = "0.54100"  # below every on-scale CE today (best 0.54952, G1)
    after, c = _render(rows2, table_only, series)
    assert "0.54100" in _registry_cell(after, "c6d48d57", 7)
    assert "0.54100" in after.split("{{")[0]  # registry
    # the day table's running best and the chart's best line both moved
    assert re.search(r"<td>10 Sep</td><td class=\"n\">\d+</td><td class=\"n\">0.54100", after)
    assert c["best_ce"] == 0.541 and c["best_day"] == "2026-09-10"
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
    m1 = next(x for x in rows2 if x["ck"] == "3cb9cd62")
    m1["ten"] = "+0.0100 [-0.0100, +0.0300]"      # neutralise the real one so exactly one resolves
    page, c = _render(rows2, table_only, series)
    assert c["ten_cross"] == c["ten_total"] - 1 and c["above_leader"] >= 1
    assert f"{build.word(c['ten_cross'])} cross zero and one resolves" in page
    assert "all " + build.word(c["ten_total"]) + " cross zero" not in page
    assert f"{c['above_leader']} of {c['with_leader']}</b><span>models above the leader" in page
    # the whole page, not only the KPI: the section-1b sentence follows the same rows
    assert "None beats the current one." not in page \
        and "One nominal interval clears zero; independent confirmation is pending." in page


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
    ("w", 999, "no parameter count"),
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
    assert f"MDE80 about {c['mde']['10w']:.3f}" in page
    # the five-window clause follows the data: absent -> "no readout yet", present -> its MDE80
    if c["five_total"]:
        assert "has no readout yet" not in page and f"MDE80 about {c['mde']['5w']:.3f}" in page
    else:
        assert "has no readout yet" in page


def test_a_five_window_cell_is_badged_counted_and_charted_separately(data):
    rows, table_only, series = data
    _, c0 = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows)
    next(x for x in rows2 if x["ck"] == "fc73c0f4")["ten"] = "5w +0.0105 [-0.0100, +0.0310]"
    page, c = _render(rows2, table_only, series)
    assert c["five_total"] == c0["five_total"] + 1 and c["five_cross"] == c0["five_cross"] + 1
    assert c["ten_total"] == c0["ten_total"] - 1
    cell = _play_cells(page)["fc73c0f4"]
    assert "+0.0105" in cell and "5w" in cell and "10w" not in cell
    assert 'class="pt pt7"' in page and "fewer than ten windows (wider)" in page  # legend + hollow marker
    assert 'class="ci ci5"' in page and page.count("svg .ci3{") == 1  # its own interval class; no CSS collision (Codex, #370)
    assert "a null there means not large" in page and "has no readout yet" not in page
    assert f"MDE80 about {c['mde']['5w']:.3f}" in page
    # with no other five-window row the MDE80 is exactly this cell's half-width x 1.43
    if c["five_total"] == 1:
        assert abs(c["mde"]["5w"] - 0.0205 * build.MDE_PER_HALFWIDTH) < 1e-6
    # the marker and legend appear only when a five-window row exists
    rows0 = [r for r in rows if not re.match(r"^\d+w ", r["ten"] or "")]
    base, c_base = _render(rows0, table_only, series)
    assert c_base["five_total"] == 0
    assert 'class="pt pt7"' not in base and "fewer than ten windows (wider)" not in base


@pytest.mark.parametrize("field,value,msg", [
    ("w32", "5w +0.1000 [+0.0500, +0.1500]", "belongs only in the ten-window field"),
    ("ten", "5x +0.1000 [+0.0500, +0.1500]", "neither a keyword"),
])
def test_window_prefixes_are_validated(data, field, value, msg):
    rows, table_only, series = data
    rows2 = copy.deepcopy(rows)
    rows2[0][field] = value
    errs = build.check_data(rows2, table_only, series)
    assert errs and any(msg in e for e in errs), errs


def test_chart_1b_fans_same_corpus_models_around_one_tick_and_spans_only_leader_sizes(data):
    """Jerry (09-13): the leader-vs-records chart should cover only the sizes that have
    points and models trained on the same corpus must sit at the same x."""
    page, c = _render(*data)
    svgs = re.findall(r'<svg viewBox="0 0 (\d+) (\d+)">(.*?)</svg>', page, re.S)
    g2 = svgs[1][2]
    by_corpus = {}
    for cx, tip in re.findall(r'<circle cx="([-0-9.]+)" cy="[-0-9.]+" r="[0-9.]+" class="pt [^"]*hit" tabindex="0" data-t="([^"]*)"', g2):
        corpus = re.search(r"\| (\d+k) clusters", tip).group(1)
        by_corpus.setdefault(corpus, set()).add(float(cx))
    # one tick per corpus: the fan around it is 7 px per point, never the old 15 px pitch
    assert len(by_corpus) >= 3 and all(max(xs) - min(xs) <= 7.01 * (len(xs) - 1) for xs in by_corpus.values()), by_corpus
    assert len(by_corpus["96k"]) >= 8 and max(by_corpus["96k"]) - min(by_corpus["96k"]) < 15 * (len(by_corpus["96k"]) - 1)
    assert "96k clusters" in g2  # tick labelled with its corpus
    assert 'am">1M</text>' not in g2 and 'am">2M</text>' not in g2 and 'am">5M</text>' not in g2  # the empty low end is gone
    assert re.search(r"\d of \d corpus sizes</text>", g2)  # legend derived, not typed


def test_chart_2b_fans_same_parameter_count_models_around_one_tick(data):
    page, c = _render(*data)
    svgs = re.findall(r'<svg viewBox="0 0 (\d+) (\d+)">(.*?)</svg>', page, re.S)
    h4 = svgs[3][2]
    by_width = {}
    for cx, tip in re.findall(r'<circle cx="([-0-9.]+)" cy="[-0-9.]+" r="[0-9.]+" class="pt [^"]*hit" tabindex="0" data-t="([^"]*)"', h4):
        w = re.search(r"width (\d+)", tip).group(1)
        by_width.setdefault(w, set()).add(float(cx))
    assert len(by_width) >= 3 and all(max(xs) - min(xs) <= 7.01 * (len(xs) - 1) for xs in by_width.values()), by_width
    # the h512 tick label may be shared with a parameter-matched depth cell (e.g. "h330, h512")
    assert re.search(r'class="axs am">[^<]*\bh512\b[^<]*</text>', h4) and 'am">611k</text>' in h4
    assert 'am">273k</text>' in h4 or "h256" in h4
    assert re.search(r"\d parameter counts</text>", h4)


def test_every_encoder_generation_has_its_own_chart_class_and_count(data):
    """Codex HOLD on #383: a v4 row had been folded into v2 on chart 1. Adding a v4
    row must raise the v4 count only, get its own marker/legend line, and appear in
    the header's encoder list; the v2 count must not move."""
    rows, table_only, series = data
    page0, c0 = _render(rows, table_only, series)
    rows2 = copy.deepcopy(rows) + [dict(zip(build.FIELDS, (
        "v4 probe", "0badf00e", "2026-09-13", "v4", 512, "3e-4", "96k", "14,077,520", "0.63000", "",
        "", "", "", "a test row")))]
    page, c = _render(rows2, table_only, series)
    assert c["enc_counts"]["v2"] == c0["enc_counts"]["v2"]
    assert c["enc_counts"]["v4"] == c0["enc_counts"]["v4"] + 1
    g1 = re.findall(r'<svg viewBox="0 0 (\d+) (\d+)">(.*?)</svg>', page, re.S)[0][2]
    assert g1.count('class="pt pt8 hit"') == c["enc_counts"]["v4"]
    assert f"v4 &middot; {c['enc_counts']['v4']} run" in g1 and "v4" in re.search(r"encoder v1, v2, v3 and v4", page).group(0)
    assert f"v2 &middot; {c['enc_counts']['v2']} runs" in g1
    # with no v4 row at all, no v4 legend line and no v4 in the header
    rows0 = [r for r in rows if r["enc"] != "v4"]
    page_no, c_no = _render(rows0, table_only, series)
    assert c_no["enc_counts"]["v4"] == 0 and "v4 &middot;" not in page_no and "and v3 &middot;" in page_no


def test_table_notes_are_one_line_and_the_history_is_in_the_record(data):
    rows, table_only, series = data
    assert all(len(r["note"]) <= build.NOTE_LIMIT for r in rows)
    long = [r for r in rows if r["record"]]
    assert long, "the long histories should have moved into RECORD"
    page, _ = _render(*data)
    for r in long:
        # the full record reaches the chart dot's tooltip AND the table row's data-t
        assert r["record"][:60].replace("--", "--") in page.replace("&#8722;", "-") or r["record"][:40] in page
        assert re.search(r'<tr class="[^"]*hit"[^>]*data-t="[^"]*' + re.escape(r["ck"]), page)
    rows2 = copy.deepcopy(rows)
    rows2[0]["note"] = "x" * (build.NOTE_LIMIT + 1)
    with pytest.raises(SystemExit):
        _render(rows2, table_only, series)


def test_the_detail_panel_is_dismissable(data):
    page, _ = _render(*data)
    assert 'id="detail-x"' in page and 'aria-label="Dismiss the model record"' in page
    assert 'e.key==="Escape"' in page and "function dismiss()" in page
    assert '<th class="note">Note</th>' in page and 'td.note{white-space:normal;min-width:360px' in page


def test_every_training_day_with_a_val_ce_is_on_charts_3_and_4_and_the_day_table(data):
    rows, table_only, series = data
    page, c = _render(*data)
    days = sorted({r["tr"].lstrip("~") for r in rows if r["ce"] and r["ck"] not in table_only})
    assert c["days"] == days
    for d in days:
        assert f"<td>{d[8:]} Sep</td>" in page, f"day {d} missing from the by-day table"
    # a model trained on a NEW day (tomorrow) appears without any list being edited
    rows2 = copy.deepcopy(rows) + [dict(zip(build.FIELDS, (
        "future model", "0badc0de", "2026-09-16", "v2", 512, "3e-4", "96k", "14,077,520",
        "0.62000", "", "", "", "", "")))]
    page2, c2 = _render(rows2, table_only, series)
    assert "2026-09-16" in c2["days"] and "<td>16 Sep</td>" in page2
    assert "16 September 2026" in page2  # the header date follows the latest training day


def test_chart_1_axis_follows_the_data_and_a_dot_outside_the_frame_is_refused(data):
    rows, table_only, series = data
    page, c = _render(*data)
    x0, x1 = c["frame1"]
    svg1 = re.search(r'<svg viewBox="0 0 880 470">(.*?)</svg>', page, re.S).group(1)
    dots = re.findall(r'<circle cx="([-0-9.]+)" cy="([-0-9.]+)" r="[0-9.]+" class="pt [^"]*hit"', svg1)
    assert len(dots) == c["with_ce"]
    for cx, cy in dots:
        assert x0 - 0.01 <= float(cx) <= x1 + 0.01, (cx, x0, x1)
    # ten times the largest corpus still lands inside the frame (the axis is derived)
    rows2 = copy.deepcopy(rows) + [dict(zip(build.FIELDS, (
        "huge corpus", "0badc0df", "2026-09-14", "v2", 512, "3e-4", "1.7M", "253,887,080",
        "0.61000", "", "", "", "", "")))]
    page2, c2 = _render(rows2, table_only, series)
    assert "50M" in page2
    # a CE below the chart floor is a loud failure, never a vanished dot
    rows3 = copy.deepcopy(rows)
    rows3[0]["ce"] = "0.53000"   # the floor is 0.540 since G1 (0.54952)
    with pytest.raises(SystemExit):
        _render(rows3, table_only, series)


def test_every_row_reaches_every_surface_it_qualifies_for_and_an_omission_fails_the_build(data):
    rows, table_only, series = data
    page, c = _render(*data)
    assert build.coverage_report(page, rows, table_only, c) == []
    # a dot silently dropped from one chart is reported by checkpoint and chart
    ck = "0c40c591"  # S-d4-176k, trained 09-13: the row the typed day list lost
    svgs = re.findall(r"<svg viewBox[^>]*>.*?</svg>", page, re.S)
    broken = page.replace(svgs[4], svgs[4].replace(f"({ck})", "(dropped)"), 1)
    assert (ck, "chart 3 by training day") in build.coverage_report(broken, rows, table_only, c)
    # a registry row that vanished is reported too
    broken2 = page.replace(f'<span class="mono null">{ck}</span>', "", 1)
    assert (ck, "registry table") in build.coverage_report(broken2, rows, table_only, c)


def test_a_one_window_only_row_dropped_from_the_leader_charts_is_reported(data):
    """Codex HOLD on #393: leader charts also plot numeric one-window pairings."""
    rows, table_only, series = data
    page, c = _render(*data)
    ck = "d84b5183"  # width 1024 lr 1e-4: a one-window pairing, no ten-window cell
    row = next(r for r in rows if r["ck"] == ck)
    assert not row["ten"] and row["w32"] and build.leader_chart_eligible(row)
    svgs = re.findall(r"<svg viewBox[^>]*>.*?</svg>", page, re.S)
    broken = page
    for i in (1, 3, 5):
        assert f"({ck})" in svgs[i]
        broken = broken.replace(svgs[i], svgs[i].replace(f"({ck})", "(dropped)"), 1)
    misses = build.coverage_report(broken, rows, table_only, c)
    assert {w for k, w in misses if k == ck} == {"chart 1b data vs leader", "chart 2b width vs leader", "chart 4 leader effect by day"}
    # the month label in the day table comes from the date
    rows2 = copy.deepcopy(rows) + [dict(zip(build.FIELDS, (
        "october model", "0badc0d0", "2026-10-02", "v2", 512, "3e-4", "96k", "14,077,520",
        "0.62000", "", "", "", "", "")))]
    page2, _ = _render(rows2, table_only, series)
    assert "<td>02 Oct</td>" in page2


def test_a_checkpoint_parameter_count_overrides_the_width_map_on_the_parameter_axis(data):
    """Codex HOLD on #401: M1 (h330 + a second head, 644,568 params) was placed at the
    width map's 610,704 on charts 2 and 2b."""
    rows, table_only, series = data
    m1 = next(r for r in rows if r["ck"] == "3cb9cd62")
    twin = next(r for r in rows if r["ck"] == "0c40c591")
    assert m1["w"] == twin["w"] == 330 and m1["params"] == 644568 and twin["params"] is None

    def cx(page, ck, chart_index):
        svg = re.findall(r"<svg viewBox[^>]*>.*?</svg>", page, re.S)[chart_index]
        m = re.search(r'<circle cx="([-0-9.]+)" cy="[-0-9.]+" r="[0-9.]+" class="pt [^"]*hit" tabindex="0" data-t="[^"]*\(' + ck + r'\)', svg)
        return float(m.group(1))
    page, _ = _render(*data)
    assert cx(page, "3cb9cd62", 2) > cx(page, "0c40c591", 2)   # chart 2: more parameters sit further right
    # without the override the two would share the width map's x
    rows2 = copy.deepcopy(rows)
    next(r for r in rows2 if r["ck"] == "3cb9cd62")["params"] = None
    page2, _ = _render(rows2, table_only, series)
    assert cx(page2, "3cb9cd62", 2) == cx(page2, "0c40c591", 2)


def test_a_readout_at_any_window_count_below_ten_is_badged_with_its_count(data):
    rows, table_only, series = data
    assert build.parse_cell("7w +0.0203 [+0.0013, +0.0393]") == (0.0203, 0.0013, 0.0393, "7w")
    page, c = _render(*data)
    cells = _play_cells(page)
    # v4-96k and M1 both reached their ten (09-14): no count prefix on either cell
    assert "+0.0089" in cells["eedf3139"] and "7w" not in cells["eedf3139"]
    assert "+0.0184" in cells["3cb9cd62"] and "5w" not in cells["3cb9cd62"]
    assert "+0.0077" in cells["02510c50"] and "5w" in cells["02510c50"]  # volNEW-176k's five-window cell is badged
    assert "5w" in c["mde"] and c["five_total"] >= 3
    assert "fewer than ten windows" in page


def test_a_synthetic_positive_seven_window_cell_is_badged_and_never_counts_as_above_the_leader(data):
    """Codex on #414: the real 7w cell reached ten and left; keep a synthetic witness
    for the badge and the headline rule (an interval that clears zero at fewer than
    ten windows is an instrument reading, not a model above the leader)."""
    rows, table_only, series = data
    rows = [dict(r) for r in rows]
    victim = next(r for r in rows if r["ck"] == "eedf3139")
    victim["ten"] = "7w +0.0203 [+0.0013, +0.0393]"
    page, c = _render(rows, table_only, series)
    cells = _play_cells(page)
    assert "+0.0203" in cells["eedf3139"] and "7w" in cells["eedf3139"]
    assert "7w" in c["mde"]
    _, c0 = _render(*data)
    assert c["above_leader"] == c0["above_leader"] == 1   # the synthetic 7w cell adds nothing to the count


def test_an_interim_at_fewer_than_ten_windows_never_counts_as_above_the_leader(data):
    """v4-96k's seven-window interval cleared zero and its ten did not; only a ten-window
    interval that excludes zero counts (today: M1's outcome head, exactly one)."""
    rows, table_only, series = data
    page, c = _render(*data)
    assert c["above_leader"] == 1 and "One nominal interval clears zero; independent confirmation is pending." in page
    rows2 = copy.deepcopy(rows)
    next(x for x in rows2 if x["ck"] == "3cb9cd62")["ten"] = "5w +0.0174 [+0.0057, +0.0404]"
    page2, c2 = _render(rows2, table_only, series)   # the same interval at five windows counts for nothing
    assert c2["above_leader"] == 0 and "None beats the current one." in page2


def test_a_repeated_record_key_is_refused_and_the_interim_reaches_the_detail_text(data, tmp_path, monkeypatch):
    """Codex HOLD on #405: a second RECORD entry for eedf3139 silently replaced the first."""
    rows, table_only, series = data
    page, _ = _render(*data)
    rec = next(r for r in rows if r["ck"] == "eedf3139")["record"]
    assert rec.startswith("TEN WINDOWS (final") and "SEVEN-WINDOW INTERIM" in rec \
        and "Offline:" in rec  # one merged record: final, interim and offline history together
    assert "SEVEN-WINDOW INTERIM" in page  # and the interim still reaches the rendered detail text
    src = open(Path(__file__).with_name("models.py")).read()
    dup = src.replace('RECORD = {\n', 'RECORD = {\n    "eedf3139": "stray duplicate",\n', 1)
    bad = tmp_path / "models.py"; bad.write_text(dup)
    monkeypatch.setattr(build, "MODELS", bad)
    with pytest.raises(ValueError, match="RECORD repeats eedf3139"):
        build.load()
