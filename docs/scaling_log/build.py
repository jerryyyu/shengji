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
#: a screen cell: optional RES prefix (a one-window result that resolves), point
#: estimate and interval, optional " SUPERSEDED" suffix; nothing else
CELL = re.compile(r"(RES)?([+-]\d\.\d{4}) \[([+-]\d\.\d{3,4}), ([+-]\d\.\d{3,4})\]( SUPERSEDED)?")


def word(n):
    return WORDS.get(n, str(n))


def load():
    g = {}
    exec(open(MODELS).read(), g)
    return [dict(zip(FIELDS, m)) for m in g["M"]], g["TABLE_ONLY"], g["SERIES"]


def parse_cell(v):
    """``(m, lo, hi)`` for a numeric screen cell; None for a keyword; raises on junk."""
    if v in KEYWORDS:
        return None
    m = CELL.fullmatch(v)
    if not m:
        raise ValueError(f"screen cell {v!r} is neither a keyword nor 'm [lo, hi]' with a known suffix")
    mid, lo, hi = (float(m.group(i)) for i in (2, 3, 4))
    if not all(math.isfinite(x) for x in (mid, lo, hi)):
        raise ValueError(f"screen cell {v!r} is not finite")
    if not lo <= mid <= hi:
        raise ValueError(f"screen cell {v!r}: interval endpoints are not ordered around the point")
    return mid, lo, hi


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
        if r["ce"] and not re.fullmatch(r"0\.\d{4,5}", r["ce"]):
            errs.append(f"{r['ck']}: val_ce {r['ce']!r}")
        for key in ("mc", "w32", "ten"):
            if r[key]:
                try:
                    parse_cell(r[key])
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


def num_cell(v, bold=False):
    if not v:
        return '<td class="n null">&mdash;</td>'
    if v == "REF":
        return '<td class="n">&mdash; reference</td>'
    if v == "GAP":
        return '<td class="n null">never paired</td>'
    if v == "CONTROL":
        return '<td class="n ok">the control</td>'
    if v in ("QUEUED", "RUNNING", "SCREENING"):
        return f'<td class="n null">{v.lower()}</td>'
    if v == "CODEX":
        return '<td class="n null">codex 260&#8209;pair</td>'
    pill = ""
    if "RES" in v and "SUPERSEDED" not in v:
        pill = ' <span class="pill res">resolves</span>'
    if "SUPERSEDED" in v:
        pill = ' <span class="pill res">superseded</span>'
    core = v.replace("RES", "").replace(" SUPERSEDED", "").replace("-", "&#8209;")
    # negative and resolving = red; negative but crossing zero (or superseded) = grey
    cls = "pos" if core.startswith("+") else ("neg" if "resolves" in pill else "null")
    body = f"<b>{core}</b>" if bold else core
    return f'<td class="n {cls}">{body}{pill}</td>'


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
            f'<td class="n">{r["rg"] or "&mdash;"}</td>{num_cell(r["mc"])}{num_cell(r["w32"])}'
            f'{num_cell(r["ten"], bold=True)}<td class="null">{note}</td></tr>')
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
    subs = {
        "N_REGISTRY": len(rows), "N_MODELS": c["models"], "N_CE": c["with_ce"],
        "N_TABLE_ONLY": word(len(table_only)),
        "N_LEADER": c["with_leader"], "N_NOLEADER": c["without_leader"],
        "N_ABOVE_LEADER": c["above_leader"],
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
    return page, c


def main():
    page, c = render()
    summary = (f"{c['rows']} rows, {c['models']} charted, {c['with_ce']} with val_ce, "
               f"{c['ten_total']} ten-window results ({c['ten_cross']} cross zero)")
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
