"""Shengji Atlas v2 -- the release-29/30 era.  ONE source of truth: registry.json; this script renders
atlas_v2.html and `--check` refuses to build when the committed page differs from the registry or the
registry breaks an invariant.  Never hand-edit the HTML (Jerry 2026-09-22; #604)."""
import json, html, datetime, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
R = json.loads((HERE / "registry.json").read_text())


INSTRUMENT_KINDS = {"windows", "matched-deals", "ladder"}


def results_of(s):
    """A screen's result slots: one per arm for a family (``results``), else the row itself."""
    if "results" in s:
        return [dict(r, arm=r.get("arm", "?")) for r in s["results"]]
    return [{"arm": "-", "label": "", "role": "primary", "confidence": s.get("confidence", 0.95),
             "point": s.get("point"), "lo": s.get("lo"), "hi": s.get("hi")}]


def check_registry(reg):
    """Invariants: one production baseline; every screen names a comparator that is a baseline release
    and a form; every read is a proper interval around its point; a served-bot read never carries a
    deal-count instrument (the instrument is a field, never a cell; Codex HOLD on #603)."""
    errs = []
    prod = [b for b in reg["baseline"] if b["status"] == "production"]
    if len(prod) != 1:
        errs.append(f"exactly one production baseline required, found {len(prod)}")
    releases = {b["release"] for b in reg["baseline"]}
    for s in reg["screens"]:
        if s.get("vs") not in releases:
            errs.append(f"{s['id']}: comparator release {s.get('vs')!r} is not a registered baseline")
        if s.get("form") not in ("served bot", "card play"):
            errs.append(f"{s['id']}: form must be 'served bot' or 'card play'")
        if s.get("status") not in ("planned", "running", "restarting", "sealed", "stopped"):
            errs.append(f"{s['id']}: unknown status {s.get('status')!r}")
    for s in reg["screens"] + reg["context_screens"]:
        # the instrument is an explicit typed field on EVERY row (context rows included), never inferred
        if s.get("instrument_kind") not in INSTRUMENT_KINDS or not s.get("instrument"):
            errs.append(f"{s['id']}: instrument_kind must be one of {sorted(INSTRUMENT_KINDS)} with a non-empty instrument text")
        if s.get("form") == "served bot" and s.get("instrument_kind") != "windows":
            errs.append(f"{s['id']}: a served-bot read must use the 'windows' instrument")
        for r in results_of(s):
            p, lo, hi = r.get("point"), r.get("lo"), r.get("hi")
            if (p is None) != (lo is None) or (p is None) != (hi is None):
                errs.append(f"{s['id']}/{r['arm']}: point, lo and hi must be given together")
            elif p is not None and not (lo <= p <= hi):
                errs.append(f"{s['id']}/{r['arm']}: interval [{lo}, {hi}] does not contain the point {p}")
            if r.get("confidence") not in (0.95, 0.975, 0.9875):
                errs.append(f"{s['id']}/{r['arm']}: confidence must be declared (0.95, 0.975 or 0.9875)")
        if "results" in s:
            rs = s["results"]
            read = [r.get("point") is not None for r in rs]
            if any(read) and not all(read):
                errs.append(f"{s['id']}: a multi-arm family is read as a whole; every declared slot (primaries and diagnostics) is populated together or not at all")
            if any(read) and s.get("status") != "sealed":
                errs.append(f"{s['id']}: a family's strength reads are publishable only once the family is sealed (status is {s.get('status')!r})")
            if s.get("status") == "sealed" and not all(read):
                errs.append(f"{s['id']}: sealed family with an unread arm")
        elif s.get("status") == "sealed" and s.get("point") is None:
            errs.append(f"{s['id']}: sealed without a read")
    for m in reg["models"]:
        if m.get("val_ce") is not None and not (0.3 < m["val_ce"] < 1.0):
            errs.append(f"{m['name']}: val_ce {m['val_ce']} out of range")
    return errs

esc = lambda s: html.escape(str(s if s is not None else ""))
def iv(p, lo, hi):
    if p is None: return "—"
    return f"{p:+.3f} [{lo:+.3f}, {hi:+.3f}]".replace("-", "−")
def verdict(lo, hi):
    if lo is None: return ("pending", "chip wait")
    if lo > 0: return ("clears zero", "chip good")
    if hi < 0: return ("below zero", "chip bad")
    return ("crosses zero", "chip null")

# ---------- forest chart (screens vs 29/30 + context vs 28, one row each) ----------
def _chart_rows(items, kind):
    out = []
    for s in items:
        for r in results_of(s):
            tag = s["id"] if r["arm"] == "-" else f"{s['id']} · {r['arm']}"
            out.append((tag, r["label"] or s["candidate"], s["comparator"], r["point"], r["lo"], r["hi"], s["status"], kind, r["confidence"], r.get("role", "primary")))
    return out
rows = _chart_rows(R["screens"], "main") + _chart_rows(R["context_screens"], "ctx")
W, LEFT, RIGHT, ROWH, TOP = 980, 330, 150, 44, 46
H = TOP + ROWH * len(rows) + 40
lo_all = min([r[4] for r in rows if r[4] is not None] + [-0.05]); hi_all = max([r[5] for r in rows if r[5] is not None] + [0.10])
lo_all, hi_all = min(lo_all, -0.02) - 0.01, hi_all + 0.01
def X(v): return LEFT + (v - lo_all) / (hi_all - lo_all) * (W - LEFT - RIGHT)
svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Screens against the current production release: point and interval at the confidence each row declares (95% single reads, 97.5% per primary in a multi-arm family)">']
svg.append(f'<line x1="{X(0):.1f}" y1="{TOP-18}" x2="{X(0):.1f}" y2="{H-30}" class="zero"/>')
svg.append(f'<text x="{X(0):.1f}" y="{TOP-24}" class="lab" text-anchor="middle">production parity</text>')
for t in [round(lo_all + i*0.02, 2) for i in range(int((hi_all-lo_all)/0.02)+1)]:
    if abs(t) < 1e-9: continue
    svg.append(f'<line x1="{X(t):.1f}" y1="{H-30}" x2="{X(t):.1f}" y2="{H-24}" class="tick"/><text x="{X(t):.1f}" y="{H-10}" class="lab" text-anchor="middle">{t:+.2f}</text>')
for i, (rid, cand, comp, p, lo, hi, st, kind, conf, role) in enumerate(rows):
    y = TOP + i * ROWH + ROWH/2
    name = f"{rid} · {cand[:34]}{'…' if len(cand) > 34 else ''}"
    svg.append(f'<text x="{LEFT-10}" y="{y+4}" class="lab name {kind}" text-anchor="end">{esc(name)}</text>')
    svg.append(f'<text x="{LEFT-10}" y="{y+18}" class="sub" text-anchor="end">vs {esc(comp[:34])} · {conf*100:g}% {esc(role)}</text>')
    if p is None:
        svg.append(f'<rect x="{X(0)-5:.1f}" y="{y-5}" width="10" height="10" class="pt pending" transform="rotate(45 {X(0):.1f} {y})"/>')
        svg.append(f'<text x="{W-RIGHT+8}" y="{y+4}" class="lab">{esc(st)} · {conf*100:g}%</text>')
        continue
    cls = "good" if lo > 0 else ("bad" if hi < 0 else "null")
    if kind == "ctx": cls += " ctx"
    svg.append(f'<line x1="{X(lo):.1f}" y1="{y}" x2="{X(hi):.1f}" y2="{y}" class="ci {cls}"/>')
    svg.append(f'<circle cx="{X(p):.1f}" cy="{y}" r="5" class="pt {cls}"/>')
    svg.append(f'<text x="{W-RIGHT+8}" y="{y+4}" class="lab num">{esc(iv(p, lo, hi))} ({conf*100:g}%)</text>')
svg.append("</svg>")
SVG = "\n".join(svg)

# ---------- tables ----------
def screens_table(items, ctx=False):
    out = ['<div class="tablewrap"><table><thead><tr><th>lane</th><th>candidate</th><th>comparator</th><th>form · instrument</th><th>seeds</th><th class="num">read</th><th>status</th><th>note</th></tr></thead><tbody>']
    for s in items:
        cells = []
        for r in results_of(s):
            v, cls = verdict(r["lo"], r["hi"])
            lab = "" if r["arm"] == "-" else f'<span class="sub">{esc(r["arm"])} · {r["confidence"]*100:g}% {esc(r.get("role",""))}</span><br>'
            cells.append(f'{lab}{esc(iv(r["point"], r["lo"], r["hi"]))} <span class="{cls}">{v}</span>')
        fam = f'<br><small>{esc(s["family"])}</small>' if s.get("family") else ""
        out.append(f'<tr><td class="mono">{esc(s["id"])}</td><td>{esc(s["candidate"])}</td><td>{esc(s["comparator"])}</td>'
                   f'<td>{esc(s["form"])} · {esc(s["instrument"])} <span class="sub">[{esc(s["instrument_kind"])}]</span>{fam}</td><td class="mono">{esc(s.get("seeds",""))}</td>'
                   f'<td class="num">{"<br>".join(cells)}</td>'
                   f'<td><span class="chip {esc(s["status"])}">{esc(s["status"])}</span>{("<br><small>" + esc(s.get("eta","")) + "</small>") if s.get("eta") else ""}</td>'
                   f'<td>{esc(s["note"])}{(" · " + esc(s["ref"])) if s.get("ref") else ""}</td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)
def models_table():
    out = ['<div class="tablewrap"><table><thead><tr><th>model</th><th>checkpoint</th><th>date</th><th>recipe</th><th class="num">val_ce</th><th class="num">rank regret</th><th>status</th></tr></thead><tbody>']
    for m in R["models"]:
        out.append(f'<tr><td>{esc(m["name"])}</td><td class="mono">{esc(m["ck"]) or "—"}</td><td class="mono">{esc(m["date"]) or "—"}</td><td>{esc(m["recipe"])}</td>'
                   f'<td class="num">{("%.4f" % m["val_ce"]) if m["val_ce"] is not None else "—"}</td><td class="num">{("%.4f" % m["regret"]) if m["regret"] is not None else "—"}</td><td>{esc(m["status"])}</td></tr>')
    out.append("</tbody></table></div>"); return "\n".join(out)
def baseline_cards():
    out = []
    for b in R["baseline"]:
        ev = "".join(f'<li>{esc(e["what"])}: <b class="num">{esc(iv(e["point"], e["lo"], e["hi"])) if e["point"] is not None else "PASS"}</b> <span class="sub">({esc(e["ref"])})</span></li>' for e in b["evidence"])
        cv = "".join(f"<li>{esc(c)}</li>" for c in b["caveats"])
        out.append(f'<article class="card {b["status"]}"><header><span class="chip {b["status"]}">release {b["release"]} · {b["status"]}</span> <span class="sub">{esc(b["since"])}</span></header>'
                   f'<p class="mono small">{esc(b["bot"])}</p><p>{esc(b["recipe"])}</p><p class="sub">head {esc(b["head"])} · package {esc(b["package"])}</p>'
                   f'<h4>Evidence</h4><ul>{ev}</ul><h4>Caveats</h4><ul class="sub">{cv}</ul></article>')
    return "\n".join(out)
data_rows = "".join(f'<tr><td class="mono">{esc(d["name"])}</td><td>{esc(d["box"])}</td><td class="mono">{d["seed0"]}</td><td>{esc(d["status"])}</td></tr>' for d in R["data"])
built = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

page = f'''<title>Shengji Atlas v2</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,600&display=swap">
<style>
:root{{--bg:#f6f4ee;--ink:#1c1b18;--sub:#6a665b;--rule:#d9d4c7;--card:#fffdf8;--accent:#8a3d2a;--good:#2f6b3a;--bad:#a23b2c;--null:#7a7468;--wait:#4d5f8a;--chipbg:#eee9dd}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#161512;--ink:#ebe6da;--sub:#a49e90;--rule:#3a372f;--card:#1f1d18;--accent:#e0866c;--good:#7cc287;--bad:#e08a7a;--null:#9b958a;--wait:#9fb0dc;--chipbg:#2a2721}}}}
:root[data-theme="dark"]{{--bg:#161512;--ink:#ebe6da;--sub:#a49e90;--rule:#3a372f;--card:#1f1d18;--accent:#e0866c;--good:#7cc287;--bad:#e08a7a;--null:#9b958a;--wait:#9fb0dc;--chipbg:#2a2721}}
body{{background:var(--bg);color:var(--ink);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif;margin:0}}
main{{max-width:1120px;margin:0 auto;padding:32px 24px 64px}}
h1{{font:600 40px/1.1 Fraunces,Georgia,serif;margin:0 0 6px;text-wrap:balance}}
h2{{font:600 22px/1.2 Fraunces,Georgia,serif;margin:40px 0 12px;text-wrap:balance}}
h4{{margin:12px 0 4px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--sub)}}
.lede{{color:var(--sub);max-width:70ch}}
.sub,small{{color:var(--sub)}} .small{{font-size:13px}}
.mono,.num{{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--rule);padding:16px 18px}} .card.production{{border-left:4px solid var(--accent)}}
.card ul{{margin:4px 0 0 18px;padding:0}} .card header{{display:flex;gap:10px;align-items:center;margin-bottom:6px}}
.chip{{display:inline-block;padding:2px 8px;border-radius:999px;background:var(--chipbg);font-size:12px;letter-spacing:.03em}}
.chip.production,.chip.sealed{{color:var(--good)}} .chip.running,.chip.pending{{color:var(--wait)}} .chip.planned{{color:var(--sub)}}
.good{{color:var(--good)}} .bad{{color:var(--bad)}} .null{{color:var(--null)}} .wait{{color:var(--wait)}}
.tablewrap{{overflow-x:auto;border:1px solid var(--rule);background:var(--card)}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--rule)}} th{{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--sub)}} td.num,th.num{{text-align:right;white-space:nowrap}}
.figure{{background:var(--card);border:1px solid var(--rule);padding:12px}}
svg .zero{{stroke:var(--accent);stroke-width:1.5;stroke-dasharray:4 3}} svg .tick{{stroke:var(--rule)}} svg .lab{{fill:var(--ink);font:12px "IBM Plex Sans",sans-serif}} svg .sub{{fill:var(--sub);font:11px "IBM Plex Sans",sans-serif}} svg .name{{font-weight:500}} svg .name.ctx{{fill:var(--sub)}}
svg .ci{{stroke-width:3}} svg .ci.good{{stroke:var(--good)}} svg .ci.null{{stroke:var(--null)}} svg .ci.bad{{stroke:var(--bad)}} svg .ci.ctx{{opacity:.55}}
svg .pt.good{{fill:var(--good)}} svg .pt.null{{fill:var(--null)}} svg .pt.bad{{fill:var(--bad)}} svg .pt.ctx{{opacity:.55}} svg .pt.pending{{fill:none;stroke:var(--wait);stroke-width:1.5}}
.foot{{margin-top:40px;color:var(--sub);font-size:13px;border-top:1px solid var(--rule);padding-top:12px}}
a{{color:var(--accent)}}
</style>
<main>
<h1>Shengji Atlas v2</h1>
<p class="lede">The release-29 era. Every new model and every search screen is read against the <b>current production release</b> (29, then 30). One registry file feeds this page; nothing here is typed twice. Rows 1–55 and the pre-release-29 models stay in the <a href="{esc(R["history"]["atlas"])}">old atlas</a> and the <a href="{esc(R["history"]["page"])}">old scaling page</a>, frozen.</p>

<h2>Production baseline</h2>
<div class="cards">{baseline_cards()}</div>

<h2>Screens against the current release</h2>
<p class="sub">Green clears zero, grey crosses it, hollow marks are waiting for their seal. Each row states its own coverage: single reads at 95%, the two primaries of a multi-arm family at 97.5% each (Bonferroni), its diagnostic arm at 95%. A family is read as a whole; no partial results are shown. Context rows (lighter) are reads against release 28, kept so the baseline's own margin stays visible next to the new contrasts.</p>
<div class="figure">{SVG}</div>
{screens_table(R["screens"])}
<h4>Context · how the baseline was established (vs release 28)</h4>
{screens_table(R["context_screens"], ctx=True)}

<h2>Models of the era</h2>
<p class="sub">val_ce is calibration; the search consumes ranking, so rank regret and the screens above are what decide.</p>
{models_table()}

<h2>Data generation on the search</h2>
<div class="tablewrap"><table><thead><tr><th>store</th><th>box</th><th>seed0</th><th>status</th></tr></thead><tbody>{data_rows}</tbody></table></div>

<p class="foot">Built {esc(built)} from registry.json by build_v2.py · {len(R["screens"])} screens vs the current release, {len(R["context_screens"])} context reads, {len(R["models"])} models · {esc(R["history"]["note"])}</p>
</main>
'''
def _stable(p):
    """The page without its build timestamp, for the --check comparison."""
    import re as _re
    return _re.sub(r"Built [^<]* from registry.json", "Built <t> from registry.json", p)


if __name__ == "__main__":
    errs = check_registry(R)
    if errs:
        print("REGISTRY ERRORS:\n  " + "\n  ".join(errs)); sys.exit(1)
    out = HERE / "atlas_v2.html"
    if "--check" in sys.argv:
        if not out.exists() or _stable(out.read_text()) != _stable(page):
            print("OUT OF DATE: atlas_v2.html differs from registry.json; run build_v2.py"); sys.exit(1)
        print(f"CONSISTENT: {len(R['screens'])} screens vs the current release, {len(R['context_screens'])} context reads, {len(R['models'])} models; atlas_v2.html == registry.json")
    else:
        out.write_text(page)
        print("built", out, len(page), "bytes;", len(rows), "chart rows")
