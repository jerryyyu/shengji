"""Build the scaling artifact from ONE source of truth.

    python build.py                 render models.py -> scaling.html (committed next to it)
    python build.py --publish PATH  also copy the page to PATH (the artifact's scratchpad file)
    python build.py --check         re-render in memory and compare with scaling.html;
                                    exit 1 on any difference or any data inconsistency

models.py is the only place a model or a screen result is entered.  Everything
else on the page is derived from it: the six charts, the by-day table, the
checkpoint registry and every count quoted in the prose.  The corpus table
(section 5) is static in template.html; it changes only when a corpus is
generated.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models.py"
TEMPLATE = HERE / "template.html"
OUT_DIR = HERE / "out"
PAGE = HERE / "scaling.html"
# The rendered page is committed next to its data; --publish PATH also copies it
# to the scratchpad that the artifact is published from.
PUBLISHED = PAGE
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
FIELDS = ("n", "ck", "tr", "enc", "w", "lr", "cl", "rec", "ce", "rg", "mc", "w32", "ten", "note")


def load():
    g = {}
    exec(open(MODELS).read(), g)
    rows = [dict(zip(FIELDS, m)) for m in g["M"]]
    return rows, g["TABLE_ONLY"]


def check_data(rows, table_only):
    """Every row well-formed; refuse to render inconsistent data."""
    errs = []
    seen = set()
    for r in rows:
        if r["ck"] in seen:
            errs.append(f"duplicate checkpoint {r['ck']}")
        seen.add(r["ck"])
        if not re.fullmatch(r"[0-9a-f]{8}|arm[IJ]", r["ck"]):
            errs.append(f"{r['ck']}: not an 8-hex checkpoint prefix")
        if not re.fullmatch(r"~?2026-\d\d-\d\d", r["tr"]):
            errs.append(f"{r['ck']}: trained date {r['tr']!r} is not ISO")
        if r["enc"] not in ("v1", "v2", "v3", "v4"):
            errs.append(f"{r['ck']}: encoder {r['enc']!r}")
        if r["ce"] and not re.fullmatch(r"0\.\d{4,5}", r["ce"]):
            errs.append(f"{r['ck']}: val_ce {r['ce']!r}")
        for key in ("mc", "w32", "ten"):
            v = r[key]
            if v and v not in ("REF", "GAP", "CONTROL", "QUEUED", "RUNNING", "SCREENING", "CODEX") \
                    and not re.match(r"[+-]\d\.\d{4} \[[+-]\d\.\d{3,4}, [+-]\d\.\d{3,4}\]", v.replace("RES", "").replace(" SUPERSEDED", "")):
                errs.append(f"{r['ck']}: {key} {v!r} is neither a keyword nor 'm [lo, hi]'")
    for ck in table_only:
        if ck not in seen:
            errs.append(f"TABLE_ONLY {ck} is not a row")
    return errs


def render_charts(rows):
    OUT_DIR.mkdir(exist_ok=True)
    g = {"MODELS": str(MODELS), "OUT": str(OUT_DIR)}
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        exec(open(HERE / "charts.py").read(), g)
    svgs = [open(OUT_DIR / f"{n}.svg").read().strip() for n in ("g1", "h2", "g3", "h4", "g5", "g6")]
    counts = json.load(open(OUT_DIR / "_counts.json"))
    return svgs, counts


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


def render():
    rows, table_only = load()
    errs = check_data(rows, table_only)
    if errs:
        print("DATA ERRORS:\n  " + "\n  ".join(errs))
        sys.exit(1)
    svgs, c = render_charts(rows)
    n_ten = sum(1 for r in rows if re.match(r"[+-]\d", r["ten"] or ""))
    page = open(TEMPLATE).read()
    subs = {
        "N_REGISTRY": len(rows), "N_MODELS": c["models"], "N_CE": c["with_ce"],
        "N_TABLE_ONLY": WORDS.get(len(table_only), len(table_only)),
        "N_LEADER": c["with_leader"], "N_NOLEADER": c["without_leader"],
        "N_SINCE_BEST": c["since_best"], "N_BEAT_MC": c["beat_mc"],
        "N_TEN_WORD": WORDS.get(n_ten, n_ten),
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
    return page, rows, c, n_ten


def main():
    page, rows, c, n_ten = render()
    if "--check" in sys.argv:
        pub = open(PAGE).read() if PAGE.exists() else ""
        if pub != page:
            import difflib
            diff = list(difflib.unified_diff(pub.splitlines(), page.splitlines(), "published", "rendered", lineterm="", n=0))
            print(f"OUT OF DATE: scaling.html differs from models.py in {sum(1 for l in diff if l[:1] in '+-')} lines")
            for l in diff[:20]:
                print("  " + l[:160])
            sys.exit(1)
        print(f"CONSISTENT: {len(rows)} rows, {c['models']} charted, {c['with_ce']} with val_ce, "
              f"{n_ten} ten-window results, scaling.html == models.py")
        return
    open(PAGE, "w").write(page)
    print(f"rendered {len(rows)} rows, {c['models']} charted, {n_ten} ten-window results -> {PAGE}")
    if "--publish" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--publish") + 1])
        shutil.copyfile(PAGE, dest)
        print(f"copied to {dest}")


if __name__ == "__main__":
    main()
