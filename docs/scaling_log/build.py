"""Build the scaling artifact from ONE source of truth.

    python build.py                 render models.py -> scaling.html (committed next to it)
    python build.py --publish PATH  also copy the page to PATH (the artifact's scratchpad file)
    python build.py --check         re-render in memory and compare with scaling.html;
                                    exit 1 on any difference or any data inconsistency

models.py is the only place a model or a screen result is entered.  Everything
else on the page is derived from it: the six charts (series are named by
checkpoint identity in SERIES and read their coordinates from the rows), the
by-day table, the checkpoint registry and every count or headline number in
the prose.  The corpus table (section 6) is static in template.html; it
changes only when a corpus is generated.  Two KPI figures come from analyses
outside this file and are labelled as such in the template: the +0.41
loss-vs-search correlation and Codex's 50.0% v3 win rate.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import math
import html
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models.py"
TEMPLATE = HERE / "template.html"
OUT_DIR = HERE / "out"
PAGE = HERE / "scaling.html"
WHAT_CHANGED = {
    "09-05": "first corpora, encoder v1",
    "09-06": "more data, still v1",
    "09-07": "encoder v2 and the learning-rate sweep",
    "09-08": "the width sweep at lr 1e-4",
    "09-09": "the I/J teacher contrast",
    "09-10": "the data-volume arms, 96k to 144k",
    "09-11": "the width sweep at maximum data (h256, h1024, h2048) and Codex&#8217;s encoder v3",
    "09-12": "volNEW-176k, the search-mean arm and the depth row (S-d4, S-d8, S-d4-plain)",
    "09-13": "the depth row closes (S-d2); encoder v4 at 96k",
}
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
         9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
MONTHS = {9: "September", 10: "October", 11: "November", 12: "December"}
NOTE_LIMIT = 150  # a table note is one line; longer history goes in RECORD
FIELDS = ("n", "ck", "tr", "enc", "w", "lr", "cl", "rec", "ce", "rg", "mc", "w32", "ten", "note")
KEYWORDS = ("REF", "GAP", "CONTROL", "QUEUED", "RUNNING", "SCREENING", "CODEX")
#: a screen cell: optional window-count prefix ("5w " = a five-window readout, "7w " = seven; only
#: the ten-window field takes one), optional RES prefix (a one-window result that
#: resolves), point estimate and interval, optional " SUPERSEDED" suffix; nothing else
CELL = re.compile(r"(?:([1-9]w) )?(RES)?([+-]\d\.\d{4}) \[([+-]\d\.\d{3,4}), ([+-]\d\.\d{3,4})\]( SUPERSEDED)?")
#: the instrument each field measures with (a five-window cell overrides "10w")
INSTRUMENT = {"ten": "10w", "w32": "1w", "mc": "mc"}
#: MDE80 = (z.975 + z.80) * SE while a 95% interval half-width is z.975 * SE
MDE_PER_HALFWIDTH = (1.95996 + 0.84162) / 1.95996


def word(n):
    return WORDS.get(n, str(n))


def _duplicate_literal_keys(src, name):
    """Keys repeated inside the ``name = {...}`` literal of models.py (a dict literal keeps
    only the last, so a repeated checkpoint would silently drop a history)."""
    import ast
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets) \
                and isinstance(node.value, ast.Dict):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            return sorted({k for k in keys if keys.count(k) > 1})
    return []


def load():
    g = {}
    src = open(MODELS).read()
    for name in ("RECORD", "PARAMS"):
        dup = _duplicate_literal_keys(src, name)
        if dup:
            raise ValueError(f"{name} repeats {', '.join(dup)}: merge into one entry")
    exec(src, g)
    record = g.get("RECORD", {})
    params = g.get("PARAMS", {})
    own_split = set(g.get("OWN_SPLIT", ()))
    rows = [dict(zip(FIELDS, m)) for m in g["M"]]
    known = {r["ck"] for r in rows}
    for ck in params:
        if ck not in known:
            raise ValueError(f"PARAMS names {ck}, which is not a row")
    for ck in g.get("POLICY_VS_SMART", {}):
        if ck not in known:
            raise ValueError(f"POLICY_VS_SMART names {ck}, which is not a row")
    for ck in own_split:
        if ck not in known:
            raise ValueError(f"OWN_SPLIT names {ck}, which is not a row")
        if not next(r["ce"] for r in rows if r["ck"] == ck):
            raise ValueError(f"OWN_SPLIT names {ck}, which has no val_ce to qualify")
    for r in rows:
        r["record"] = record.get(r["ck"], "")
        r["params"] = params.get(r["ck"])
        r["own_split"] = r["ck"] in own_split
    global NOTE_LIMIT
    NOTE_LIMIT = g.get("NOTE_LIMIT", NOTE_LIMIT)
    return rows, g["TABLE_ONLY"], g["SERIES"]


def parse_cell(v, field="ten"):
    """``(m, lo, hi, instrument)`` for a numeric screen cell; None for a keyword; raises on junk."""
    if v in KEYWORDS:
        return None
    m = CELL.fullmatch(v)
    if not m:
        raise ValueError(f"screen cell {v!r} is neither a keyword nor 'm [lo, hi]' with a known suffix")
    if m.group(1) and field != "ten":
        raise ValueError(f"screen cell {v!r}: a window-count prefix belongs only in the ten-window field")
    mid, lo, hi = (float(m.group(i)) for i in (3, 4, 5))
    if not all(math.isfinite(x) for x in (mid, lo, hi)):
        raise ValueError(f"screen cell {v!r} is not finite")
    if not lo <= mid <= hi:
        raise ValueError(f"screen cell {v!r}: interval endpoints are not ordered around the point")
    return mid, lo, hi, (m.group(1) or INSTRUMENT[field])


def mde80(rows):
    """Median MDE80 per instrument, derived from the intervals actually on the page."""
    hw = {}
    for r in rows:
        for key in ("mc", "w32", "ten"):
            parsed = parse_cell(r[key], key) if r[key] else None
            if parsed:
                hw.setdefault(parsed[3], []).append((parsed[2] - parsed[1]) / 2)
    out = {}
    for inst, xs in hw.items():
        xs = sorted(xs)
        med = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
        out[inst] = med * MDE_PER_HALFWIDTH
    return out


def known_widths():
    """The hidden widths charts.py can place on the parameter axis (its PAR map)."""
    src = open(HERE / "charts.py").read()
    par = re.search(r"^PAR=\{([^}]*)\}", src, re.M).group(1)
    return {int(k) for k in re.findall(r"(\d+)\s*:", par)}


def check_data(rows, table_only, series):
    """Every row well-formed; refuse to render inconsistent data."""
    errs = []
    for r in rows:
        if len(r["note"]) > NOTE_LIMIT:
            errs.append(f"{r['ck']}: note is {len(r['note'])} chars (> {NOTE_LIMIT}); move the history into RECORD")
    seen = set()
    widths = known_widths()
    for r in rows:
        if r["ck"] in seen:
            errs.append(f"duplicate checkpoint {r['ck']}")
        seen.add(r["ck"])
        if not re.fullmatch(r"[0-9a-f]{8}|arm[IJ]", r["ck"]):
            errs.append(f"{r['ck']}: not an 8-hex checkpoint prefix")
        try:
            dt.date.fromisoformat(r["tr"].lstrip("~"))
        except ValueError:
            errs.append(f"{r['ck']}: trained date {r['tr']!r} is not a calendar date")
        if r["enc"] not in ("v1", "v2", "v3", "v4"):
            errs.append(f"{r['ck']}: encoder {r['enc']!r}")
        if r["w"] not in widths:
            errs.append(f"{r['ck']}: width {r['w']} has no parameter count in charts.py PAR")
        if r["ce"] and not re.fullmatch(r"\d\.\d{4,5}", r["ce"]):  # a soft-target head can sit above 1.0
            errs.append(f"{r['ck']}: val_ce {r['ce']!r}")
        for key in ("mc", "w32", "ten"):
            if r[key]:
                try:
                    parse_cell(r[key], key)
                except ValueError as e:
                    errs.append(f"{r['ck']}: {key}: {e}")
    for ck in table_only:
        if ck not in seen:
            errs.append(f"TABLE_ONLY {ck} is not a row")
    for key, cks in series.items():
        for ck in cks:
            if ck not in seen:
                errs.append(f"SERIES[{key!r}] names {ck}, which is not a row")
            elif ck in table_only:
                errs.append(f"SERIES[{key!r}] names {ck}, which is table-only")
    return errs


def render_charts(rows, table_only, series):
    OUT_DIR.mkdir(exist_ok=True)
    g_models = {}
    exec(compile(open(MODELS).read(), str(MODELS), "exec"), g_models)
    g = {"MODELS": str(MODELS), "OUT": str(OUT_DIR),
         "M": [tuple(r[f] for f in FIELDS) for r in rows], "TABLE_ONLY": table_only, "SERIES": series,
         "OWN_SPLIT": {r["ck"] for r in rows if r.get("own_split")},
         "POLICY_VS_SMART": g_models.get("POLICY_VS_SMART", {}),
         "RECORD": {r["ck"]: r.get("record", "") for r in rows if r.get("record")},
         "PARAMS": {r["ck"]: r["params"] for r in rows if r.get("params")}}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(open(HERE / "charts.py").read(), g)
    svgs = [open(OUT_DIR / f"{n}.svg").read().strip() for n in ("g1", "h2", "g3", "h4", "g5", "g6", "g7")]
    counts = json.load(open(OUT_DIR / "_counts.json"))
    return svgs, counts


def signed(v, nd=4):
    return ("&minus;" if v < 0 else "+") + f"{abs(v):.{nd}f}"


BADGE = {"10w": "10w", "5w": "5w", "1w": "1w paired", "mc": "1w MC&#8209;LCB"}


def measure(v, field):
    """One measurement as html: signed point, interval, instrument badge, pills; plus its class."""
    mid, lo, hi, inst = parse_cell(v, field)
    core = re.sub(r"^\d+w ", "", v).replace("RES", "").replace(" SUPERSEDED", "").replace("-", "&#8209;")
    pill = ""
    if "RES" in v and "SUPERSEDED" not in v:
        pill = ' <span class="pill res">resolves</span>'
    if "SUPERSEDED" in v:
        pill = ' <span class="pill res">superseded</span>'
    # positive = green; negative and resolving = red; negative but crossing zero (or superseded) = grey
    cls = "pos" if mid > 0 else ("neg" if "resolves" in pill else "null")
    if "SUPERSEDED" in v:
        cls = "null"
    return f'{core} <span class="pill inst">{BADGE.get(inst, inst)}</span>{pill}', cls


def play_cell(r):
    """The consolidated play column: the best available comparison against the
    leader first (ten or five windows, else the one-window pairing), the other
    measurements underneath in small type, every one labelled with its
    instrument so the interval is read with the right MDE."""
    ten, w32, mc = r["ten"], r["w32"], r["mc"]
    main, cls, rest = "", "n null", []
    if "REF" in (ten, w32):
        main, cls = "&mdash; reference", "n"
    elif ten == "CONTROL":
        main, cls = "the control", "n ok"
    elif ten and ten not in KEYWORDS:
        body, c = measure(ten, "ten")
        main, cls = f"<b>{body}</b>", "n " + c
        if w32 and w32 not in KEYWORDS:
            rest.append(measure(w32, "w32")[0])
    elif w32 and w32 not in KEYWORDS:
        body, c = measure(w32, "w32")
        main, cls = body, "n " + c
    elif ten == "CODEX":
        main = 'codex 260&#8209;pair <span class="pill inst">260p</span>'
    elif w32 == "GAP" and ten not in ("QUEUED", "RUNNING", "SCREENING"):
        main = "never paired"
    if ten in ("QUEUED", "RUNNING", "SCREENING"):
        main = (main + " " if main else "") + f'<span class="pill live">{ten.lower()}</span>'
    if mc:
        rest.append(measure(mc, "mc")[0])
    if not main and not rest:
        return '<td class="n null">&mdash;</td>'
    tail = "".join(f'<br><span class="small null">{x}</span>' for x in rest)
    return f'<td class="{cls}">{main}{tail}</td>'


def registry_rows(rows):
    out = []
    for r in rows:
        cls = "ref" if r["ck"] == "3cd27716" else ""
        tr = (f'<td class="n null">{r["tr"][1:]} <span class="pill">approx</span></td>' if r["tr"].startswith("~")
              else f'<td class="n">{r["tr"]}</td>')
        trd = r["tr"].lstrip("~")
        note = r["note"].replace(" -- ", " &mdash; ")
        rec = r.get("record", "")
        if rec:
            body = html.escape(f'{r["n"]}  {r["ck"]}\n{r["note"]}\n\n{rec}', quote=True).replace("\n", "&#10;")
            cls = f'{cls} hit'.strip()
            open_tr = f'<tr class="{cls}" tabindex="0" data-tr="{trd}" data-t="{body}" title="tap for the full record">'
        else:
            open_tr = f'<tr class="{cls}" data-tr="{trd}">'
        out.append(
            open_tr + f'<td><b>{r["n"]}</b><br><span class="mono null">{r["ck"]}</span></td>'
            f'{tr}<td>{r["enc"]}</td><td class="n">{r["w"]}</td>'
            f'<td class="n">{r["lr"].replace("-", "&#8209;")}</td><td class="n">{r["cl"]}</td>'
            f'<td class="n">{r["rec"]}</td><td class="n">{r["ce"] or "&mdash;"}</td>'
            f'<td class="n">{r["rg"] or "&mdash;"}</td>{play_cell(r)}<td class="null note">{note}</td></tr>')
    return "\n".join(out)


def policy_rows(g=None):
    """Section 8: one row per policy head (models.POLICY_HEADS), blanks rendered as an em dash."""
    if g is None:
        src = open(MODELS).read()
        g = {}
        exec(compile(src, MODELS, "exec"), g)
    heads = [dict(zip(g["POLICY_FIELDS"], row)) for row in g["POLICY_HEADS"]]
    vs_smart = g.get("POLICY_VS_SMART", {})
    # A measured head need NOT have a POLICY_HEADS row: that table stops at JS-G1 and the
    # generation nets (gen-1/2/3) are not in it, though they all carry policy heads. The
    # chart draws from the MODEL rows, and load() already refuses a checkpoint that is not
    # a row at all, so a table row is not required to record the measurement.
    _unlisted = sorted(ck for ck in vs_smart if ck not in {h["ck"] for h in heads})
    for h in heads:
        if len(h) != len(g["POLICY_FIELDS"]):
            raise SystemExit(f"policy head {h.get('name')}: wrong field count")
    cell = lambda v, cls="n": f'<td class="{cls}">{html.escape(str(v)) if v else "&mdash;"}</td>'
    out = []
    for h in heads:
        ck = f'<br><span class="mono null">{h["ck"]}</span>' if h["ck"] else ""
        out.append(
            f'<tr><td><b>{html.escape(h["name"])}</b>{ck}</td><td>{html.escape(h["kind"])}</td><td>{html.escape(h["trunk"])}</td>'
            + cell(h["rows"]) + cell(h["split"]) + cell(h["epochs"]) + cell(h["weight"]) + f'<td>{html.escape(h["eval"])}</td>'
            + cell(h["listwise"]) + cell(h["bce"]) + cell(h["top1"]) + cell(h["top64"]) + cell(h["strata"])
            + cell(vs_smart.get(h["ck"], ""), "n pos" if str(vs_smart.get(h["ck"], "")).startswith("+") else "n")
            + cell(h["value_cost"])
            + f'<td class="null note">{html.escape(h["note"])}</td></tr>')
    return "\n".join(out), heads


def day_rows(rows, table_only):
    charted = [r for r in rows if r["ck"] not in table_only and r["ce"]]
    days = sorted({r["tr"].lstrip("~") for r in charted})
    out, run = [], None
    for d in days:
        day = sorted((r for r in charted if r["tr"].lstrip("~") == d), key=lambda r: float(r["ce"]))
        best = float(day[0]["ce"])
        if run is None:
            gained, run = "start", best
        elif best < run:
            gained, run = "&minus;%.4f" % (run - best), best
        else:
            gained = "&mdash;"
        key = d[5:]
        label = dt.date.fromisoformat(d).strftime("%d %b")
        out.append(f'<tr><td>{label}</td><td class="n">{len(day)}</td>'
                   f'<td class="n">{day[0]["ce"]}<br><span class="small">{day[0]["n"]}</span></td>'
                   f'<td class="n">{run:.5f}</td><td class="n">{gained}</td><td>{WHAT_CHANGED.get(key, "")}</td></tr>')
    return "\n".join(out)


def long_day(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d} {MONTHS.get(d.month, d.strftime('%B'))}"


CHART_NAMES = ("1 data vs CE", "1b data vs leader", "2 width vs CE", "2b width vs leader",
               "3 by training day", "4 leader effect by day", "5 policy vs SmartBot by day")


def leader_chart_eligible(r):
    """The rows the leader-axis charts (1b, 2b, 4) plot: the leader itself as the
    reference mark, any numeric ten-/five-window cell, or a numeric one-window
    pairing (charts.py ``eff``; ``RES``/``SUPERSEDED`` prefixes are still numbers).
    Codex HOLD on #393: the first version guarded only ten-window rows, so a
    one-window-only row (d84b5183) could vanish from all three leader charts unseen."""
    if r["ck"] == "3cd27716":
        return True
    if r["ten"] and parse_cell(r["ten"]) is not None:
        return True
    return bool(r["w32"]) and r["w32"] not in KEYWORDS


def coverage_report(page, rows, table_only, c):
    """Every row must reach every surface it qualifies for; the list of misses.

    A row with a val_ce on the CE scale must be a dot on charts 1, 2 and 3; a row
    with a numeric ten-/five-window cell must be a dot on charts 1b, 2b and 4;
    every row must be a registry line with its note; every history in RECORD must
    reach the detail text.  Jerry 2026-09-13: three models trained that day were
    missing from charts 3 and 4 because a typed day list ended the day before, and
    nothing noticed.  This runs on every build and fails it."""
    svgs = re.findall(r"<svg viewBox[^>]*>.*?</svg>", page, re.S)
    if len(svgs) != len(CHART_NAMES):
        return [("page", f"{len(svgs)} charts rendered, {len(CHART_NAMES)} expected")]
    charts = dict(zip(CHART_NAMES, svgs))
    off_scale = {n for n, _ in c.get("off_scale", [])}
    misses = []
    for r in rows:
        ck, tag = r["ck"], f"({r['ck']})"
        if f'<span class="mono null">{ck}</span>' not in page:
            misses.append((ck, "registry table"))
        if r["note"] and r["note"].replace(" -- ", " &mdash; ") not in page:
            misses.append((ck, "registry note (complete text)"))
        if r.get("record") and html.escape(r["record"], quote=True).replace("\n", "&#10;") not in page:
            misses.append((ck, "RECORD history in the detail text (complete text)"))
        if ck in table_only:
            continue
        if r["ce"] and r["n"] not in off_scale:
            for name in ("1 data vs CE", "2 width vs CE", "3 by training day"):
                if tag not in charts[name]:
                    misses.append((ck, f"chart {name}"))
        if leader_chart_eligible(r):
            for name in ("1b data vs leader", "2b width vs leader", "4 leader effect by day"):
                if tag not in charts[name]:
                    misses.append((ck, f"chart {name}"))
    return misses


def render(rows=None, table_only=None, series=None):
    """The page as a string plus the derived numbers; raises SystemExit on bad data."""
    if rows is None:
        rows, table_only, series = load()
    errs = check_data(rows, table_only, series)
    if errs:
        print("DATA ERRORS:\n  " + "\n  ".join(errs))
        sys.exit(1)
    svgs, c = render_charts(rows, table_only, series)
    page = open(TEMPLATE).read()
    n_ten, cross = c["ten_total"], c["ten_cross"]
    if cross == n_ten:
        ten_clause = f"all {word(n_ten)} cross zero"
    else:
        ten_clause = (f"{word(cross)} cross zero and {word(n_ten - cross)} "
                      f"{'resolves' if n_ten - cross == 1 else 'resolve'}")
    paired_clause = (f"all {word(c['paired_one'])} paired arms" if c["paired_exact"] == c["paired_one"]
                     else f"{c['paired_exact']} of the {c['paired_one']} paired arms")
    above = c["above_leader"]
    above_clause = ("None beats the current one." if above == 0 else
                    ("One nominal interval clears zero; independent confirmation is pending." if above == 1 else
                     f"{word(above).capitalize()} nominal intervals clear zero; independent confirmation is pending."))
    corpus_clause = (f"Only {word(c['sizes_with_leader'])} of {word(c['sizes_all'])} corpus sizes have any "
                     f"leader comparison, and nothing below {c['min_leader_records'] / 1e6:.1f}M records has one.")
    w = c
    if w["w144_monotone"]:
        w144_clause = (f"At maximum data and the deployed rate, smaller is monotonically better: "
                       f"h256 beats the deployed h512 by {w['w144_gap_256_vs_512']:.4f} on "
                       f"{w['w144_256_param_frac'] * 100:.0f}% of the weights, and h{w['w144_worst_w']} is worst on "
                       f"{w['w144_worst_over_best_params']:.1f}&times; the weights.")
    else:
        w144_clause = (f"At maximum data and the deployed rate the ordering is not monotone in width: "
                       f"h{w['w144_best_w']} is best and h{w['w144_worst_w']} is worst, "
                       f"{w['w144_span']:.4f} apart.")
    # the lr 1e-4 sweep (red) has its best at h1024; "opposite" only if the 144k line falls with width
    gold_vs_red = ("The gold line runs opposite to the red. " if w["w144_monotone"] and w["lr14_best_w"] > 256 else "")
    cell_vs_width = ("Second-order hyperparameters are worth nearly as much as every width change at maximum data."
                     if 0.5 * w["w144_span"] <= w["cell_spread"] <= 1.5 * w["w144_span"] else
                     f"That spread is {w['cell_spread'] / w['w144_span']:.1f}&times; the whole 144k width sweep.")
    ratio = abs(w["w144_span"] / w["last_doubling"]) if w["last_doubling"] else float("inf")
    span_vs_doubling = ("twice" if 1.75 <= ratio <= 2.25 else ("about equal to" if 0.8 <= ratio <= 1.25 else f"{ratio:.1f}&times;"))
    mde = mde80(rows)
    fmt = lambda k: f"{mde[k]:.3f}" if k in mde else "n/a"
    n_five = c.get("five_total", 0)
    few = sorted((k for k in mde if k.endswith("w") and k not in ("10w", "1w")), key=lambda k: int(k[:-1]))
    five_clause = (" A cell badged <b>" + "</b>/<b>".join(few) + "</b> is a readout at that many windows, fewer than ten "
                   f"(MDE80 about {', '.join(fmt(k) for k in few)}): a null there means not large, never no effect "
                   f"({word(n_five)} arm{'s' if n_five != 1 else ''} so far)."
                   if n_five else " <b>5w</b> (the first five windows, the triage instrument) has no readout yet.")
    present = [e for e in ("v1", "v2", "v3", "v4") if c["enc_counts"].get(e)]
    enc_list = "encoder " + (", ".join(present[:-1]) + " and " + present[-1] if len(present) > 1 else present[0])
    subs = {
        "ENC_LIST": enc_list,
        "MDE_TEN": fmt("10w"), "MDE_ONE": fmt("1w"), "MDE_MC": fmt("mc"), "FIVE_CLAUSE": five_clause,
        "N_REGISTRY": len(rows), "N_MODELS": c["models"], "N_CE": c["with_ce"],
        "OFFSCALE_CLAUSE": ("" if not c["off_scale"] else
                            " " + ", ".join(f"{n} (CE {v:.3f})" for n, v in c["off_scale"])
                            + (" is" if len(c["off_scale"]) == 1 else " are")
                            + " above the CE axis and listed on each chart instead of drawn; "
                              "the registry carries the full row."),
        "N_TABLE_ONLY": word(len(table_only)),
        "N_LEADER": c["with_leader"], "N_NOLEADER": c["without_leader"],
        "N_ABOVE_LEADER": c["above_leader"], "ABOVE_CLAUSE": above_clause,
        "CORPUS_LEADER_CLAUSE": corpus_clause, "W144_CLAUSE": w144_clause, "GOLD_VS_RED": gold_vs_red,
        "CELL_VS_WIDTH": cell_vs_width, "SPAN_VS_DOUBLING": span_vs_doubling,
        "W144_N_WORD": word(c["w144_n"]), "W144_REC": f"{c['w144_rec'] / 1e6:.1f}M", "W144_SPAN": f"{c['w144_span']:.4f}",
        "N_SINCE_BEST": c["since_best"], "N_BEAT_MC": c["beat_mc"],
        "N_TEN_WORD": word(n_ten), "TEN_CROSS_CLAUSE": ten_clause,
        "PAIRED_CLAUSE": paired_clause,
        "ENC_GAP": signed(c["enc_gap"]), "LAST_DOUBLING": signed(c["last_doubling"]),
        "N_CELL_WORD": word(c["cell_n"]), "CELL_SPREAD": f"{c['cell_spread']:.4f}",
        "LAST_DAY_LONG": long_day(max(c["days"])),
        "BEST_DAY_LONG": long_day(c["best_day"]), "BIG_DAY_LONG": long_day(c["big_day"]),
        "BIG_DROP": signed(-c["big_drop"]),
        "BIG_CLAUSE": ", more than every day since combined" if c["big_beats_rest"] else "",
        "REGISTRY": registry_rows(rows), "DAYROWS": day_rows(rows, table_only),
    }
    policy_html, policy_heads = policy_rows()
    subs["POLICYROWS"] = policy_html
    subs["N_POLICY"] = len(policy_heads)
    subs["N_POLICY_COMMON"] = sum(1 for h in policy_heads if h["listwise"])
    for i, svg in enumerate(svgs, 1):
        subs[f"SVG{i}"] = svg
    for k, v in subs.items():
        page = page.replace("{{%s}}" % k, str(v))
    left = re.findall(r"\{\{[A-Z0-9_]+\}\}", page)
    if left:
        print("UNFILLED placeholders:", left)
        sys.exit(1)
    c["rows"] = len(rows)
    c["mde"] = mde
    misses = coverage_report(page, rows, table_only, c)
    if misses:
        print("COVERAGE ERRORS (a row did not reach a surface it qualifies for):\n  "
              + "\n  ".join(f"{ck}: missing from {where}" for ck, where in misses))
        sys.exit(1)
    return page, c


def main():
    page, c = render()
    summary = (f"{c['rows']} rows, {c['models']} charted, {c['with_ce']} with val_ce, "
               f"{c['ten_total']} ten-window results ({c['ten_cross']} cross zero), "
               f"{c['five_total']} five-window")
    if "--check" in sys.argv:
        pub = open(PAGE).read() if PAGE.exists() else ""
        if pub != page:
            import difflib
            diff = list(difflib.unified_diff(pub.splitlines(), page.splitlines(), "scaling.html", "rendered", lineterm="", n=0))
            print(f"OUT OF DATE: scaling.html differs from models.py in {sum(1 for l in diff if l[:1] in '+-')} lines")
            for l in diff[:20]:
                print("  " + l[:160])
            sys.exit(1)
        print(f"CONSISTENT: {summary}, scaling.html == models.py")
        return
    open(PAGE, "w").write(page)
    print(f"rendered {summary} -> {PAGE}")
    if "--publish" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--publish") + 1])
        shutil.copyfile(PAGE, dest)
        print(f"copied to {dest}")


if __name__ == "__main__":
    main()
