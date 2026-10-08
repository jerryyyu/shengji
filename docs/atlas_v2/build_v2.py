"""Shengji Atlas v2 -- the release-29/30 era.  ONE source of truth: registry.json; this script renders
atlas_v2.html next to it.  The page is BUILT, not tracked (#688): publish from the built file.
`--check` refuses when the registry breaks an invariant or the page cannot be built, and -- when a
built atlas_v2.html is on disk -- when that stale page differs from a fresh build.  Never hand-edit
the HTML (Jerry 2026-09-22; #604)."""
import json, html, datetime, hashlib, re, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
R = json.loads((HERE / "registry.json").read_text())


INSTRUMENT_KINDS = {"windows", "matched-deals", "ladder"}
TITLE_MAX, TAKEAWAY_MAX, ONELINE_MAX = 60, 150, 170


def results_of(s):
    """A screen's result slots: one per arm for a family (``results``), else the row itself."""
    if "results" in s:
        return [dict(r, arm=r.get("arm", "?")) for r in s["results"]]
    return [{"arm": "-", "label": "", "role": "primary", "confidence": s.get("confidence", 0.95),
             "point": s.get("point"), "lo": s.get("lo"), "hi": s.get("hi")}]


# what the contrast varies: the whole served bot, the card-play search, or the bury chooser alone
FORMS = ("served bot", "card play", "bury decision")
# ``unavailable`` is a FINISHED state with no strength estimate (e.g. the pinned reader refused): it carries
# no point/lo/hi, must say why in its note, and is never drawn as a mark on the chart (v52ec, #676).
STATUSES = ("planned", "running", "restarting", "sealed", "stopped", "unavailable")
NO_ESTIMATE = "no estimate (unavailable)"


# A screen's ``seeds`` is the EXPLICIT list of its window seed0s: integers separated by single spaces,
# optionally followed by a parenthesized host label, groups joined by "; " -- e.g.
# "48060910 48160910 (Perf); 48560910 48660910 (cloud)".  Never a range: "29960910..30360910" was read
# as its two endpoints and an audit reported zero overlaps for a window (30260910) that sat inside a
# training span (v35d, #707 2026-10-06).  A row whose seeds are not window seed0s at all is a LEGACY row:
# allow-listed here by id with its exact text, and its expansion is recomputed from that text.
SEEDS_GROUP = r"\d+(?: \d+)*(?: \([A-Za-z0-9][A-Za-z0-9 _.-]*\))?"
SEEDS_RE = re.compile(rf"{SEEDS_GROUP}(?:; {SEEDS_GROUP})*")
LEGACY_SEEDS = {
    # one contiguous block of deal seeds, not window seed0s (launch-plan.json: RESERVED 626710000:626710260)
    "depth-screen": {"text": "626710000..626710259", "kind": "deal seeds", "first": 626710000, "count": 260},
    # generated-deal indices of a derived namespace, not deal seeds at all
    "v48bury": {"text": "deal indices 2080..4159 (all-ranks-known-banker-v1)", "kind": "deal indices",
                "first": 2080, "count": 2080},
}
LEGACY_RE = re.compile(r"(?P<kind>deal indices )?(?P<lo>\d+)\.\.(?P<hi>\d+)(?: \([^()]+\))?")


def seed_windows(seeds):
    """The window seed0s an explicit ``seeds`` text lists (``SEEDS_RE``), in order; None if not explicit."""
    if not isinstance(seeds, str) or not SEEDS_RE.fullmatch(seeds):
        return None
    return [int(t) for t in re.sub(r"\([^()]*\)", " ", seeds).replace(";", " ").split()]


def legacy_expansion(text):
    """``{"kind", "first", "count"}`` computed from a legacy inclusive ``lo..hi`` text, or None."""
    m = LEGACY_RE.fullmatch(text or "")
    if not m or int(m["hi"]) < int(m["lo"]):
        return None
    return {"kind": "deal indices" if m["kind"] else "deal seeds", "first": int(m["lo"]),
            "count": int(m["hi"]) - int(m["lo"]) + 1}


def check_seeds(s):
    """The seeds invariant for one screen row (``SEEDS_RE`` / ``LEGACY_SEEDS``)."""
    sid, seeds = s.get("id"), s.get("seeds")
    if sid in LEGACY_SEEDS:
        legacy = LEGACY_SEEDS[sid]
        if seeds != legacy["text"]:
            return [f"{sid}: legacy seeds text changed ({seeds!r} != allow-listed {legacy['text']!r}); "
                    "write an explicit window list or update LEGACY_SEEDS"]
        got = legacy_expansion(seeds)
        want = {k: legacy[k] for k in ("kind", "first", "count")}
        return [] if got == want else [f"{sid}: legacy seeds expand to {got}, allow-listed as {want}"]
    if seeds is None and s.get("status") in ("planned", "running", "restarting"):
        return []
    windows = seed_windows(seeds)
    if not windows:
        return [f"{sid}: seeds must be an explicit list of window seed0s ('A B C (host); D E (host)'), "
                f"never a range or prose; got {seeds!r}"]
    dup = sorted({w for w in windows if windows.count(w) > 1})
    return [f"{sid}: seeds repeat a window seed0 {dup}"] if dup else []


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
        if s.get("form") not in FORMS:
            errs.append(f"{s['id']}: form must be one of {sorted(FORMS)}")
        if s.get("status") not in STATUSES:
            errs.append(f"{s['id']}: unknown status {s.get('status')!r}")
    for s in reg["screens"] + reg["context_screens"]:
        # the page leads with these; the long candidate/note text is the record behind a toggle
        t, k = s.get("title"), s.get("takeaway")
        if not (isinstance(t, str) and 0 < len(t) <= TITLE_MAX):
            errs.append(f"{s['id']}: title (what was tested, plain words) is required, at most {TITLE_MAX} characters")
        if not (isinstance(k, str) and 0 < len(k) <= TAKEAWAY_MAX):
            errs.append(f"{s['id']}: takeaway (one sentence: what we learned) is required, at most {TAKEAWAY_MAX} characters")
    for b in reg["baseline"]:
        o = b.get("oneline")
        if not (isinstance(o, str) and 0 < len(o) <= ONELINE_MAX):
            errs.append(f"release {b.get('release')}: oneline (what changed, headline evidence) is required, at most {ONELINE_MAX} characters")
    for s in reg["screens"]:
        if "vs_group" in s and not (isinstance(s["vs_group"], str) and s["vs_group"].strip()):
            errs.append(f"{s['id']}: vs_group, when given, names the comparator that is not the release as served")
        if "vs_group" not in s and not str(s.get("comparator", "")).startswith(f"release {s.get('vs')} as served"):
            errs.append(f"{s['id']}: the comparator is not 'release {s.get('vs')} as served', so it needs a vs_group naming what it is compared to")
    for s in reg["screens"] + reg["context_screens"]:
        # the instrument is an explicit typed field on EVERY row (context rows included), never inferred
        if s.get("instrument_kind") not in INSTRUMENT_KINDS or not s.get("instrument"):
            errs.append(f"{s['id']}: instrument_kind must be one of {sorted(INSTRUMENT_KINDS)} with a non-empty instrument text")
        if s.get("form") == "served bot" and s.get("instrument_kind") != "windows":
            errs.append(f"{s['id']}: a served-bot read must use the 'windows' instrument")
        if s.get("form") == "bury decision" and s.get("instrument_kind") != "matched-deals":
            errs.append(f"{s['id']}: a bury-decision read must use the 'matched-deals' instrument")
        for r in results_of(s):
            p, lo, hi = r.get("point"), r.get("lo"), r.get("hi")
            if (p is None) != (lo is None) or (p is None) != (hi is None):
                errs.append(f"{s['id']}/{r['arm']}: point, lo and hi must be given together")
            elif p is not None and not (lo <= p <= hi):
                errs.append(f"{s['id']}/{r['arm']}: interval [{lo}, {hi}] does not contain the point {p}")
            if r.get("confidence") not in (0.95, 0.975, 0.9875):
                errs.append(f"{s['id']}/{r['arm']}: confidence must be declared (0.95, 0.975 or 0.9875)")
        if s.get("status") == "unavailable":
            if any(r.get(k) is not None for r in results_of(s) for k in ("point", "lo", "hi")):
                errs.append(f"{s['id']}: an unavailable screen carries no estimate; point, lo and hi must all be null")
            if not (isinstance(s.get("note"), str) and s["note"].strip()):
                errs.append(f"{s['id']}: an unavailable screen needs a non-empty note saying why there is no estimate")
            continue
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
    for s in reg["screens"] + [c for c in reg["context_screens"] if c.get("seeds") is not None]:
        errs.extend(check_seeds(s))
    for m in reg["models"]:
        if m.get("val_ce") is not None and not (0.3 < m["val_ce"] < 1.0):
            errs.append(f"{m['name']}: val_ce {m['val_ce']} out of range")
        for key in ("head_alone", "head_vs_prod"):
            h = m.get(key)
            if h is None:
                continue
            if not all(k in h for k in ("point", "lo", "hi", "ref")) or not (h["lo"] <= h["point"] <= h["hi"]):
                errs.append(f"{m['name']}: {key} must carry point, lo, hi (lo <= point <= hi) and a ref")
    return errs


def production_release(reg):
    """The one production baseline's release number (checked above)."""
    return [b for b in reg["baseline"] if b["status"] == "production"][0]["release"]

def comparator_release(reg):
    """The release NEW screens are read against. It equals production unless the registry's
    ``screen_comparator`` says otherwise (e.g. a new production release whose adoption as the
    screen comparator is still pending Jerry's ruling); the two are never conflated."""
    sc = reg.get("screen_comparator")
    if sc is None:
        return production_release(reg)
    assert set(sc) == {"release", "status", "note"} and sc["status"] in ("pending", "confirmed"), sc
    assert any(b["release"] == sc["release"] for b in reg["baseline"]), "comparator must be a baseline release"
    return sc["release"]

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
            out.append((tag, r["label"] or s.get("title") or s["candidate"], s["comparator"], r["point"], r["lo"], r["hi"], s["status"], kind, r["confidence"], r.get("role", "primary")))
    return out
PROD = production_release(R)
CMP = comparator_release(R)          # what new screens are read against (== PROD unless pending/confirmed otherwise)
PROD_SINCE = next(b["since"] for b in R["baseline"] if b["release"] == CMP).split(" ")[0]      # the date it took over
# The releases that screens were read against before the current one, in order ("29, then 30, then 36, ").
_COMPARATORS = sorted({s["vs"] for s in R["screens"] if s["vs"] != CMP} | {29})
EARLIER_PRODS = ", then ".join(str(r) for r in _COMPARATORS) + (", " if _COMPARATORS else "")
SCREENS_NOW = [s for s in R["screens"] if s.get("vs") == CMP]
CMP_ROLE = "the current production" if CMP == PROD else f"the screen comparator; production is release {PROD}"
_SC = R.get("screen_comparator")
COMPARATOR_NOTE = (f" <b>Production is release {PROD}</b>; {esc(_SC['note'])}" if _SC and CMP != PROD
                   else (f" {esc(_SC['note'])}" if _SC else ""))
SCREENS_EARLIER = [s for s in R["screens"] if s.get("vs") != CMP]
EARLIER_RELEASES = sorted({s["vs"] for s in SCREENS_EARLIER})
def _reads(n): return f"{n} read" + ("" if n == 1 else "s")
def comparator_sections(reg):
    """One section per (release, actual comparator): the production release first, then the earlier
    ones, newest first.  Within a release the reads against the release AS SERVED come first, then each
    named comparator (``vs_group``: a variant, a control, card play) in registry order.  Grouping never
    depends on which release is production, so a promotion keeps every named comparator apart."""
    prod = comparator_release(reg)
    live = production_release(reg)
    rels = [prod] + sorted({s["vs"] for s in reg["screens"] if s["vs"] != prod}, reverse=True)
    out = []
    for rel in rels:
        groups = {}
        for s in sorted((s for s in reg["screens"] if s["vs"] == rel), key=lambda s: bool(s.get("vs_group"))):
            groups.setdefault(s.get("vs_group"), []).append(s)
        for g, items in groups.items():
            tail = ((" · current production" if rel == live else " · current comparator") if g is None else "") if rel == prod else " · closed comparator"
            out.append({"release": rel, "group": g, "label": (f"release {rel} as served" if g is None else g) + tail,
                        "kind": "main" if rel == prod else "prev", "items": items})
    return out
COMPARATORS = comparator_sections(R)
# One chart band per comparator: every row under a band is compared to the thing the band names.
SECTIONS = [(f"against {c['label']}", c["kind"], c["items"]) for c in COMPARATORS]
if R["context_screens"]:
    SECTIONS.append(("context · against release 28", "ctx", R["context_screens"]))
rows = [r for _, kind, items in SECTIONS for r in _chart_rows(items, kind)]
W, LEFT, RIGHT, ROWH, TOP, SEPH = 980, 330, 200, 44, 46, 34
H = TOP + ROWH * len(rows) + SEPH * len(SECTIONS) + 40
lo_all = min([r[4] for r in rows if r[4] is not None] + [-0.05]); hi_all = max([r[5] for r in rows if r[5] is not None] + [0.10])
lo_all, hi_all = min(lo_all, -0.02) - 0.01, hi_all + 0.01
def X(v): return LEFT + (v - lo_all) / (hi_all - lo_all) * (W - LEFT - RIGHT)
svg = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Screens against the current production release: point and interval at the confidence each row declares (95% single reads, 97.5% per primary in a multi-arm family)">']
svg.append(f'<line x1="{X(0):.1f}" y1="{TOP-18}" x2="{X(0):.1f}" y2="{H-30}" class="zero"/>')
svg.append(f'<text x="{X(0):.1f}" y="{TOP-24}" class="lab" text-anchor="middle">production parity</text>')
STEP = 0.02 if hi_all - lo_all <= 0.25 else 0.05                      # keep the tick labels apart on a wide axis
for t in [round(STEP * i, 2) for i in range(int(lo_all / STEP) - 1, int(hi_all / STEP) + 2) if lo_all <= STEP * i <= hi_all]:
    if abs(t) < 1e-9: continue
    svg.append(f'<line x1="{X(t):.1f}" y1="{H-30}" x2="{X(t):.1f}" y2="{H-24}" class="tick"/><text x="{X(t):.1f}" y="{H-10}" class="lab" text-anchor="middle">{t:+.2f}</text>')
layout, _y = [], TOP
for label, kind, items in SECTIONS:
    sec_rows = _chart_rows(items, kind)
    layout.append(("sep", _y, f"{label} · {_reads(len(sec_rows))}")); _y += SEPH
    for r in sec_rows:
        layout.append(("row", _y, r)); _y += ROWH
for what, top, item in layout:
    if what == "sep":
        svg.append(f'<rect x="0" y="{top+6}" width="{W}" height="{SEPH-12}" class="sepband"/>')
        svg.append(f'<text x="12" y="{top+SEPH/2+4}" class="sep">{esc(item)}</text>')
        continue
    rid, cand, comp, p, lo, hi, st, kind, conf, role = item
    y = top + ROWH/2
    name = f"{rid} · {cand}"
    name = name if len(name) <= 52 else name[:51] + "…"            # the label column is LEFT px wide
    svg.append(f'<text x="{LEFT-10}" y="{y+4}" class="lab name {kind}" text-anchor="end">{esc(name)}</text>')
    svg.append(f'<text x="{LEFT-10}" y="{y+18}" class="sub" text-anchor="end">vs {esc(comp[:34])} · {conf*100:g}% {esc(role)}</text>')
    if st == "unavailable":                                       # finished without an estimate: no mark at all
        svg.append(f'<text x="{W-RIGHT+8}" y="{y+4}" class="lab sub">{esc(NO_ESTIMATE)}</text>')
        continue
    if p is None:
        svg.append(f'<rect x="{X(0)-5:.1f}" y="{y-5}" width="10" height="10" class="pt pending" transform="rotate(45 {X(0):.1f} {y})"/>')
        svg.append(f'<text x="{W-RIGHT+8}" y="{y+4}" class="lab">{esc(st)} · {conf*100:g}%</text>')
        continue
    cls = "good" if lo > 0 else ("bad" if hi < 0 else "null")
    if kind == "ctx": cls += " ctx"
    if kind == "prev": cls += " prev"
    svg.append(f'<line x1="{X(lo):.1f}" y1="{y}" x2="{X(hi):.1f}" y2="{y}" class="ci {cls}"/>')
    svg.append(f'<circle cx="{X(p):.1f}" cy="{y}" r="5" class="pt {cls}"/>')
    svg.append(f'<text x="{W-RIGHT+8}" y="{y+4}" class="lab num">{esc(iv(p, lo, hi))} ({conf*100:g}%)</text>')
svg.append("</svg>")
SVG = "\n".join(svg)

# ---------- tables ----------
def screens_table(items, ctx=False):
    """One short row per screen (what was tested, the read, what we learned); the full registry text --
    candidate, comparator, instrument, seeds and note -- sits in a closed toggle under the row."""
    out = ['<div class="tablewrap"><table class="screens"><thead><tr><th>lane</th><th>what was tested</th><th class="num">read</th><th>what we learned</th><th>status</th></tr></thead><tbody>']
    for s in items:
        cells = []
        for r in results_of(s):
            v, cls = (NO_ESTIMATE, "chip unavailable") if s.get("status") == "unavailable" else verdict(r["lo"], r["hi"])
            lab = "" if r["arm"] == "-" else f'<span class="sub">{esc(r["arm"])} · {r["confidence"]*100:g}% {esc(r.get("role",""))}</span><br>'
            cells.append(f'{lab}{esc(iv(r["point"], r["lo"], r["hi"]))}<br><span class="{cls}">{v}</span>')
        fam = f'<dt>family</dt><dd>{esc(s["family"])}</dd>' if s.get("family") else ""
        ref = f'<dt>ref</dt><dd>{esc(s["ref"])}</dd>' if s.get("ref") else ""
        out.append(f'<tr class="lead"><td class="mono">{esc(s["id"])}<br><span class="sub">{esc(s.get("date", ""))}</span></td><td>{esc(s["title"])}</td>'
                   f'<td class="num">{"<br>".join(cells)}</td><td>{esc(s["takeaway"])}</td>'
                   f'<td><span class="chip {esc(s["status"])}">{esc(s["status"])}</span>{("<br><small>" + esc(s.get("eta","")) + "</small>") if s.get("eta") else ""}</td></tr>')
        out.append(f'<tr class="more"><td></td><td colspan="4"><details><summary>full record</summary><dl>'
                   f'<dt>candidate</dt><dd>{esc(s["candidate"])}</dd><dt>compared to</dt><dd>{esc(s["comparator"])}</dd>'
                   f'<dt>instrument</dt><dd>{esc(s["form"])} · {esc(s["instrument"])} <span class="sub">[{esc(s["instrument_kind"])}]</span></dd>'
                   f'<dt>seeds</dt><dd class="mono">{esc(s.get("seeds","")) or "—"}</dd>{fam}<dt>note</dt><dd>{esc(s["note"])}</dd>{ref}</dl></details></td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)
def _head(h):
    if not h: return "—"
    return f'<span title="{esc(h["ref"])}">{esc(iv(h["point"], h["lo"], h["hi"]))}</span>'
def models_table():
    out = ['<div class="tablewrap"><table><thead><tr><th>model</th><th>checkpoint</th><th>date</th><th>recipe</th><th class="num">val_ce</th><th class="num">rank regret</th><th class="num">policy head alone vs SmartBot</th><th class="num">vs production head</th><th>status</th></tr></thead><tbody>']
    for m in R["models"]:
        out.append(f'<tr><td>{esc(m["name"])}</td><td class="mono">{esc(m["ck"]) or "—"}</td><td class="mono">{esc(m["date"]) or "—"}</td><td>{esc(m["recipe"])}</td>'
                   f'<td class="num">{("%.4f" % m["val_ce"]) if m["val_ce"] is not None else "—"}</td><td class="num">{("%.4f" % m["regret"]) if m["regret"] is not None else "—"}</td>'
                   f'<td class="num">{_head(m.get("head_alone"))}</td><td class="num">{_head(m.get("head_vs_prod"))}</td><td>{esc(m["status"])}</td></tr>')
    out.append("</tbody></table></div>"); return "\n".join(out)
def baseline_cards():
    """The current production release as one card (caveats behind a toggle); every earlier release of the
    era as one line.  The full evidence for the earlier ones stays in registry.json."""
    b = [x for x in R["baseline"] if x["status"] == "production"][0]
    ev = "".join(f'<li>{esc(e["what"])}: <b class="num">{esc(iv(e["point"], e["lo"], e["hi"])) if e["point"] is not None else "PASS"}</b> <span class="sub">({esc(e["ref"])})</span></li>' for e in b["evidence"])
    cv = "".join(f"<li>{esc(c)}</li>" for c in b["caveats"])
    card = (f'<article class="card production"><header><span class="chip production">release {b["release"]} · production</span> <span class="sub">since {esc(b["since"])}</span></header>'
            f'<p>{esc(b["oneline"])}</p><p class="mono small">{esc(b["bot"])}</p>'
            f'<details><summary>recipe, evidence and caveats</summary><p>{esc(b["recipe"])}</p><p class="sub">head {esc(b["head"])} · package {esc(b["package"])}</p>'
            f'<h4>Evidence</h4><ul>{ev}</ul><h4>Caveats</h4><ul class="sub">{cv}</ul></details></article>')
    earlier = [x for x in R["baseline"] if x["status"] != "production"]
    lines = "".join(f'<li><b>release {x["release"]}</b> <span class="sub">{esc(x["since"])}</span> — {esc(x["oneline"])}</li>'
                    for x in sorted(earlier, key=lambda x: x["release"], reverse=True))
    return card + (f'<ul class="releases">{lines}</ul>' if lines else "")
models_note = ('<p class="lede small">' + esc(R["models_note"]) + "</p>") if R.get("models_note") else ""
head_note = ('<p class="sub small">' + esc(R["head_ladder_note"]) + "</p>") if R.get("head_ladder_note") else ""
def comparator_tables(sections):
    return "\n".join(f'<h4>Screens against {esc(c["label"])} · {_reads(len(c["items"]))}</h4>' + screens_table(c["items"]) for c in sections)
now_block = (comparator_tables([c for c in COMPARATORS if c["release"] == CMP]) if SCREENS_NOW
             else f'<p class="sub">No screen has read against release {CMP} yet; every new candidate from {esc(PROD_SINCE)} is read here.</p>')
def earlier_sections():
    return comparator_tables([c for c in COMPARATORS if c["release"] != CMP])

data_rows = "".join(f'<tr><td class="mono">{esc(d["name"])}</td><td>{esc(d["box"])}</td>'
                    f'<td class="mono">{esc(d["seed0"]) if d.get("seed0") else "&#8212;"}</td>'
                    f'<td class="mono">{esc(d.get("clusters", ""))}</td><td>{esc(d["status"])}</td></tr>'
                    for d in R["data"])
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
.chip.production,.chip.sealed{{color:var(--good)}} .chip.running,.chip.pending{{color:var(--wait)}} .chip.planned,.chip.unavailable{{color:var(--sub)}}
.good{{color:var(--good)}} .bad{{color:var(--bad)}} .null{{color:var(--null)}} .wait{{color:var(--wait)}}
.tablewrap{{overflow-x:auto;border:1px solid var(--rule);background:var(--card)}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--rule)}} th{{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--sub)}} td.num,th.num{{text-align:right;white-space:nowrap}}
table.screens td:first-child{{white-space:nowrap}} table.screens tr.lead td{{border-bottom:0;padding-bottom:4px}} table.screens tr.more td{{padding-top:0;padding-bottom:8px}}
details summary{{cursor:pointer;color:var(--sub);font-size:12px;letter-spacing:.04em}} details summary:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
details dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:8px 0 4px;font-size:13px;max-width:92ch}} details dt{{color:var(--sub);font-size:12px;letter-spacing:.04em;text-transform:uppercase}} details dd{{margin:0}}
ul.releases{{list-style:none;margin:12px 0 0;padding:0;max-width:92ch}} ul.releases li{{padding:6px 0;border-bottom:1px solid var(--rule)}}
.figure{{background:var(--card);border:1px solid var(--rule);padding:12px}}
svg .zero{{stroke:var(--accent);stroke-width:1.5;stroke-dasharray:4 3}} svg .tick{{stroke:var(--rule)}} svg .lab{{fill:var(--ink);font:12px "IBM Plex Sans",sans-serif}} svg .sub{{fill:var(--sub);font:11px "IBM Plex Sans",sans-serif}} svg .name{{font-weight:500}} svg .name.ctx{{fill:var(--sub)}}
svg .sepband{{fill:var(--chipbg)}} svg .sep{{fill:var(--accent);font:600 11px "IBM Plex Sans",sans-serif;letter-spacing:.08em;text-transform:uppercase}}
svg .ci{{stroke-width:3}} svg .ci.good{{stroke:var(--good)}} svg .ci.null{{stroke:var(--null)}} svg .ci.bad{{stroke:var(--bad)}} svg .ci.ctx{{opacity:.55}}
svg .ci.prev{{opacity:.8}} svg .pt.prev{{opacity:.8}}
svg .pt.good{{fill:var(--good)}} svg .pt.null{{fill:var(--null)}} svg .pt.bad{{fill:var(--bad)}} svg .pt.ctx{{opacity:.55}} svg .pt.pending{{fill:none;stroke:var(--wait);stroke-width:1.5}}
.foot{{margin-top:40px;color:var(--sub);font-size:13px;border-top:1px solid var(--rule);padding-top:12px}}
a{{color:var(--accent)}}
</style>
<main>
<h1>Shengji Atlas v2</h1>
<p class="lede">The release-29 era. Every new model and every search screen is read against <b>release {CMP} as served</b> ({esc(EARLIER_PRODS)}now <b>{CMP}</b>).{COMPARATOR_NOTE} One registry file feeds this page; nothing here is typed twice. Rows 1–55 and the pre-release-29 models stay in the <a href="{esc(R["history"]["atlas"])}">old atlas</a> and the <a href="{esc(R["history"]["page"])}">old scaling page</a>, frozen.</p>

<h2>Production</h2>
{baseline_cards()}

<h2>Screens against release {CMP} ({CMP_ROLE})</h2>
<p class="sub">Green clears zero, grey crosses it, hollow marks are waiting for their seal, and a row marked {esc(NO_ESTIMATE)} finished without a strength estimate and has no mark. Each row states its own coverage: single reads at 95%, the two primaries of a multi-arm family at 97.5% each (Bonferroni), its diagnostic arm at 95%. A family is read as a whole; no partial results are shown. The chart has one labelled band per comparator: the reads against release {CMP} first, then the reads against the era's earlier releases (a closed comparator, kept as the record of how {CMP} was chosen), then the context rows against release 28 (lighter).</p>
<div class="figure">{SVG}</div>
{now_block}
{earlier_sections()}
<h4>Context · how the baseline was established (vs release 28)</h4>
{screens_table(R["context_screens"], ctx=True)}

<h2>Models of the era</h2>
<p class="sub">val_ce is calibration; the search consumes ranking, so rank regret and the screens above are what decide.</p>
{models_note}
{head_note}
{models_table()}

<h2>Data generation on the search</h2>
<div class="tablewrap"><table><thead><tr><th>store</th><th>box</th><th>seed0</th><th>clusters</th><th>status</th></tr></thead><tbody>{data_rows}</tbody></table></div>

<p class="foot">Built {esc(built)} from registry.json by build_v2.py · {len(SCREENS_NOW)} screens vs release {CMP}, {len(SCREENS_EARLIER)} vs the era's earlier releases, {len(R["context_screens"])} context reads, {len(R["models"])} models · {esc(R["history"]["note"])}</p>
</main>
'''
def _stable(p):
    """The page without its build timestamp, for the --check comparison."""
    import re as _re
    return _re.sub(r"Built [^<]* from registry.json", "Built <t> from registry.json", p)


ARCHIVE = Path.home() / "shengji-archive" / "2026-09-13" / "readouts"
_SHA = re.compile(r"\b[0-9a-f]{64}\b")
_ARCHIVE_DIR = re.compile(r"readouts/([A-Za-z0-9._-]+)/")


def check_archive_shas(reg, archive=ARCHIVE):
    """Every full sha256 a row cites must exist in the archive the row names, when that archive is on
    this disk: a hand-copied sha that appears nowhere in the archive (a typo, or a sibling lane's file)
    is refused.  Known hashes are every 64-hex token in the archive's top-level files of at most 8 MB
    (SHA256SUMS, receipt.json, result.json, the predeclaration) plus each such file's own sha256.  Rows with no archive path, or whose archive is not on
    this machine, are skipped and counted, so a CI box without the archive still builds."""
    errs, checked, skipped = [], 0, 0
    known_by_dir = {}
    for s in reg["screens"]:
        text = json.dumps({k: v for k, v in s.items() if k != "ref"})
        dirs = sorted(set(_ARCHIVE_DIR.findall(text)))
        cited = set(_SHA.findall(text))
        if not dirs or not cited:
            continue
        present = [archive / d for d in dirs if (archive / d).is_dir()]
        if not present:
            skipped += 1
            continue
        known = set()
        for d in present:
            if d not in known_by_dir:
                # top-level files only (raw output stays unread): every 64-hex token in a small
                # file -- SHA256SUMS lists the archived files, receipt/result cite the rest --
                # plus each small file's own sha256 (SHA256SUMS's included)
                k = set()
                for f in d.iterdir():
                    if not f.is_file() or f.stat().st_size > 8 << 20:
                        continue
                    data = f.read_bytes()
                    k.add(hashlib.sha256(data).hexdigest())
                    k.update(_SHA.findall(data.decode("utf-8", "replace")))
                known_by_dir[d] = k
            known |= known_by_dir[d]
        missing = sorted(cited - known)
        checked += 1
        if missing:
            errs.append(f"{s['id']}: cites sha256 not found in its archive {', '.join(dirs)}: "
                        + ", ".join(m[:16] + "..." for m in missing))
    return errs, checked, skipped


if __name__ == "__main__":
    errs = check_registry(R)
    if errs:
        print("REGISTRY ERRORS:\n  " + "\n  ".join(errs)); sys.exit(1)
    out = HERE / "atlas_v2.html"
    if "--check" in sys.argv:
        # The page is not tracked: prove it BUILDS (a real write, to a temp file), and if a built
        # page is lying next to the registry it must match, so a stale local page is still caught.
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=True) as tmp:
            tmp.write(page); tmp.flush()
            if Path(tmp.name).stat().st_size != len(page.encode()):
                print("BUILD FAILED: temp page size mismatch"); sys.exit(1)
        if out.exists() and _stable(out.read_text()) != _stable(page):
            print("OUT OF DATE: atlas_v2.html differs from registry.json; run build_v2.py"); sys.exit(1)
        sha_errs, sha_checked, sha_skipped = check_archive_shas(R)
        if sha_errs:
            print("ARCHIVE SHA ERRORS:\n  " + "\n  ".join(sha_errs)); sys.exit(1)
        print(f"CONSISTENT: {len(SCREENS_NOW)} screens vs release {CMP}, {len(SCREENS_EARLIER)} vs earlier releases, {len(R['context_screens'])} context reads, {len(R['models'])} models; atlas_v2.html == registry.json")
        print(f"archive shas: {sha_checked} rows verified against their archives, {sha_skipped} archives not on this machine")
    else:
        out.write_text(page)
        print("built", out, len(page), "bytes;", len(rows), "chart rows")
