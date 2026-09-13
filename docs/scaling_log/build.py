"""Build the scaling artifact from ONE source of truth.

    python build.py                 render models.py -> scaling.html (committed next to it)
    python build.py --publish PATH  also copy the page to PATH (the artifact's scratchpad file)
    python build.py --check         re-render in memory and compare with scaling.html;
                                    exit 1 on any difference or any data inconsistency

models.py is the only place a model or a screen result is entered.  Everything
else on the page is derived from it: the six charts (series are named by
checkpoint identity in SERIES and read their coordinates from the rows), the
by-day table, the checkpoint registry and every count or headline number in
the prose.  The corpus table (section 5) is static in template.html; it
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
    "09-12": "volNEW-176k and the search-mean arm",
}
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
         9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
MONTHS = {9: "September", 10: "October", 11: "November", 12: "December"}
FIELDS = ("n", "ck", "tr", "enc", "w", "lr", "cl", "rec", "ce", "rg", "mc", "w32", "ten", "note")
KEYWORDS = ("REF", "GAP", "CONTROL", "QUEUED", "RUNNING", "SCREENING", "CODEX")
#: a screen cell: optional instrument prefix ("5w " = a five-window readout; only
#: the ten-window field takes one), optional RES prefix (a one-window result that
#: resolves), point estimate and interval, optional " SUPERSEDED" suffix; nothing else
CELL = re.compile(r"(?:(5w) )?(RES)?([+-]\d\.\d{4}) \[([+-]\d\.\d{3,4}), ([+-]\d\.\d{3,4})\]( SUPERSEDED)?")
#: the instrument each field measures with (a five-window cell overrides "10w")
INSTRUMENT = {"ten": "10w", "w32": "1w", "mc": "mc"}
#: MDE80 = (z.975 + z.80) * SE while a 95% interval half-width is z.975 * SE
MDE_PER_HALFWIDTH = (1.95996 + 0.84162) / 1.95996


def word(n):
    return WORDS.get(n, str(n))


def load():
    g = {}
    exec(open(MODELS).read(), g)
    return [dict(zip(FIELDS, m)) for m in g["M"]], g["TABLE_ONLY"], g["SERIES"]


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


def check_data(rows, table_only, series):
    """Every row well-formed; refuse to render inconsistent data."""
    errs = []
    seen = set()
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
    g = {"MODELS": str(MODELS), "OUT": str(OUT_DIR),
         "M": [tuple(r[f] for f in FIELDS) for r in rows], "TABLE_ONLY": table_only, "SERIES": series}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(open(HERE / "charts.py").read(), g)
    svgs = [open(OUT_DIR / f"{n}.svg").read().strip() for n in ("g1", "h2", "g3", "h4", "g5", "g6")]
    counts = json.load(open(OUT_DIR / "_counts.json"))
    return svgs, counts


def signed(v, nd=4):
    return ("&minus;" if v < 0 else "+") + f"{abs(v):.{nd}f}"


BADGE = {"10w": "10w", "5w": "5w", "1w": "1w paired", "mc": "1w MC&#8209;LCB"}


def measure(v, field):
    """One measurement as html: signed point, interval, instrument badge, pills; plus its class."""
    mid, lo, hi, inst = parse_cell(v, field)
    core = re.sub(r"^5w ", "", v).replace("RES", "").replace(" SUPERSEDED", "").replace("-", "&#8209;")
    pill = ""
    if "RES" in v and "SUPERSEDED" not in v:
        pill = ' <span class="pill res">resolves</span>'
    if "SUPERSEDED" in v:
        pill = ' <span class="pill res">superseded</span>'
    # positive = green; negative and resolving = red; negative but crossing zero (or superseded) = grey
    cls = "pos" if mid > 0 else ("neg" if "resolves" in pill else "null")
    if "SUPERSEDED" in v:
        cls = "null"
    return f'{core} <span class="pill inst">{BADGE[inst]}</span>{pill}', cls


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
        note = r["note"].replace(" -- ", " &mdash; ")
        out.append(
            f'<tr class="{cls}"><td><b>{r["n"]}</b><br><span class="mono null">{r["ck"]}</span></td>'
            f'{tr}<td>{r["enc"]}</td><td class="n">{r["w"]}</td>'
            f'<td class="n">{r["lr"].replace("-", "&#8209;")}</td><td class="n">{r["cl"]}</td>'
            f'<td class="n">{r["rec"]}</td><td class="n">{r["ce"] or "&mdash;"}</td>'
            f'<td class="n">{r["rg"] or "&mdash;"}</td>{play_cell(r)}<td class="null">{note}</td></tr>')
    return "\n".join(out)


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
        out.append(f'<tr><td>{key[3:]} Sep</td><td class="n">{len(day)}</td>'
                   f'<td class="n">{day[0]["ce"]}<br><span class="small">{day[0]["n"]}</span></td>'
                   f'<td class="n">{run:.5f}</td><td class="n">{gained}</td><td>{WHAT_CHANGED.get(key, "")}</td></tr>')
    return "\n".join(out)


def long_day(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d} {MONTHS.get(d.month, d.strftime('%B'))}"


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
                    f"{word(above).capitalize()} {'beats' if above == 1 else 'beat'} the current one.")
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
    five_clause = (f" <b>5w</b> is the first five of those windows, MDE80 about {fmt('5w')}: "
                   f"a null there means not large, never no effect ({word(n_five)} arm{'s' if n_five != 1 else ''} so far)."
                   if n_five else " <b>5w</b> (the first five windows, the triage instrument) has no readout yet.")
    subs = {
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
        "BEST_DAY_LONG": long_day(c["best_day"]), "BIG_DAY_LONG": long_day(c["big_day"]),
        "BIG_DROP": signed(-c["big_drop"]),
        "BIG_CLAUSE": ", more than every day since combined" if c["big_beats_rest"] else "",
        "REGISTRY": registry_rows(rows), "DAYROWS": day_rows(rows, table_only),
    }
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
