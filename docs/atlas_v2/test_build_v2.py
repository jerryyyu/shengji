"""Atlas v2 invariants: the registry is the only source, the page rebuilds from it, and the checks refuse
the mixes the old page suffered (Codex HOLD on #603)."""
import copy, importlib.util, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("build_v2", HERE / "build_v2.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_check_builds_from_the_registry_and_reports_consistent():
    """The page is built, not tracked (#688): --check must pass with no atlas_v2.html on disk."""
    r = subprocess.run([sys.executable, str(HERE / "build_v2.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("CONSISTENT:") and "atlas_v2.html == registry.json" in r.stdout


def test_check_catches_a_stale_built_page_and_a_broken_registry(tmp_path):
    """A stale local page and a registry that breaks an invariant both fail --check."""
    import shutil
    for name in ("build_v2.py", "registry.json"):
        shutil.copy(HERE / name, tmp_path / name)
    (tmp_path / "atlas_v2.html").write_text("<title>stale</title>")
    r = subprocess.run([sys.executable, str(tmp_path / "build_v2.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 1 and "OUT OF DATE" in r.stdout, r.stdout + r.stderr
    (tmp_path / "atlas_v2.html").unlink()
    r = subprocess.run([sys.executable, str(tmp_path / "build_v2.py")], capture_output=True, text=True)
    assert r.returncode == 0 and (tmp_path / "atlas_v2.html").exists(), r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(tmp_path / "build_v2.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("CONSISTENT:"), r.stdout + r.stderr
    reg = json.loads((tmp_path / "registry.json").read_text()); reg["screens"][0]["vs"] = 99
    (tmp_path / "registry.json").write_text(json.dumps(reg))
    r = subprocess.run([sys.executable, str(tmp_path / "build_v2.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 1 and "REGISTRY ERRORS" in r.stdout, r.stdout + r.stderr


def test_registry_invariants_hold_and_the_checks_bite():
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    assert mod.check_registry(reg) == []
    bad = copy.deepcopy(reg); bad["screens"][0]["vs"] = 99
    assert any("not a registered baseline" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); bad["context_screens"][0]["lo"] = bad["context_screens"][0]["point"] + 1
    assert any("does not contain the point" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); bad["baseline"][0]["status"] = "production"
    assert any("exactly one production baseline" in e for e in mod.check_registry(bad))
    # instrument is an explicit typed field on every row, context rows included (Codex HOLD on #609)
    bad = copy.deepcopy(reg); bad["screens"][0]["instrument"] = ""
    assert any("non-empty instrument" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); del bad["screens"][0]["instrument_kind"]
    assert any("instrument_kind" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); bad["context_screens"][0]["instrument_kind"] = "matched-deals"
    assert any("served-bot read must use the 'windows' instrument" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); bad["context_screens"][0]["instrument_kind"] = "bogus"
    assert any("instrument_kind" in e for e in mod.check_registry(bad))
    # a bury screen is its own form, never rendered as card play (Codex HOLD on #731)
    bury = next(i for i, s in enumerate(reg["screens"]) if s["id"] == "v48bury")
    assert reg["screens"][bury]["form"] == "bury decision"
    bad = copy.deepcopy(reg); bad["screens"][bury]["instrument_kind"] = "windows"
    assert any("bury-decision read must use the 'matched-deals' instrument" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); bad["screens"][bury]["form"] = "bury"
    assert any("form must be one of" in e for e in mod.check_registry(bad))
    assert "bury decision · " in mod.page                         # rendered as its own form


def test_a_multi_arm_family_has_one_slot_per_arm_with_its_own_coverage():
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    fam = next(s for s in reg["screens"] if "results" in s)
    slots = mod.results_of(fam)
    assert [r["role"] for r in slots].count("primary") == 2 and all(r["confidence"] == 0.975 for r in slots if r["role"] == "primary")
    page = mod.page                                               # a fresh build; the page is not tracked
    for r in slots:
        assert f'{fam["id"]} · {r["arm"]}' in page                # one chart row and one table line per arm
    assert "point and 95% interval" not in page                    # no blanket coverage label
    # A family is populated as a whole and only once sealed (Codex HOLD on #609, narrowed).
    # Each state is built explicitly so the test does not depend on whether the committed
    # registry's family happens to be read yet.
    def family(reg_copy):
        return next(s for s in reg_copy["screens"] if "results" in s)

    def set_family(reg_copy, status, read_arms):
        f = family(reg_copy); f["status"] = status
        for r in f["results"]:
            if r["arm"] in read_arms: r.update(point=0.01, lo=-0.01, hi=0.03)
            else: r.update(point=None, lo=None, hi=None)
        return f

    all_arms = [r["arm"] for r in family(copy.deepcopy(reg))["results"]]
    bad = copy.deepcopy(reg); set_family(bad, "sealed", all_arms[:1])           # one slot read
    assert any("populated together" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); f = family(bad)
    primaries = [r["arm"] for r in f["results"] if r["role"] == "primary"]
    set_family(bad, "sealed", primaries)                                        # both primaries, diagnostic unread
    assert any("populated together" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); set_family(bad, "running", all_arms)              # all read, still running
    assert any("publishable only once the family is sealed" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); set_family(bad, "sealed", [])                     # sealed with nothing read
    assert any("sealed family with an unread arm" in e for e in mod.check_registry(bad))
    ok = copy.deepcopy(reg); set_family(ok, "sealed", all_arms)                 # the publishable state
    assert mod.check_registry(ok) == []
    bad = copy.deepcopy(reg); f = next(s for s in bad["screens"] if "results" in s); f["results"][0]["confidence"] = 0.9
    assert any("confidence must be declared" in e for e in mod.check_registry(bad))


def test_every_screen_reaches_the_chart_and_the_table():
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text()); page = mod.page
    for s in reg["screens"] + reg["context_screens"]:
        assert page.count(s["id"]) >= 2, s["id"]          # chart label + table cell
        assert s["instrument_kind"] in page


def test_the_page_splits_screens_by_comparator_release_and_carries_the_head_ladder():
    """After release 36 the page leads with the reads against the CURRENT production release and keeps
    the earlier comparators as closed sections; every model row carries its policy-head-alone read."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    prod = mod.comparator_release(reg)                           # the release NEW screens are read against
    page = mod.page                                               # a fresh build; the page is not tracked
    role = ("the current production" if prod == mod.production_release(reg)
            else f"the screen comparator; production is release {mod.production_release(reg)}")
    assert f"Screens against release {prod} ({role})" in page
    for rel in sorted({s["vs"] for s in reg["screens"] if s["vs"] != prod}):
        assert f"Screens against release {rel}" in page
    assert "policy head alone vs SmartBot" in page
    with_ladder = [m for m in reg["models"] if m.get("head_alone")]
    assert with_ladder, "no model carries a head_alone read"
    for m in with_ladder:
        assert mod.iv(m["head_alone"]["point"], m["head_alone"]["lo"], m["head_alone"]["hi"]) in page
    bad = copy.deepcopy(reg); bad["models"][-1]["head_alone"] = {"point": 0.3, "lo": 0.31, "hi": 0.32, "ref": "x"}
    assert any("head_alone" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg)
    for b in bad["baseline"]: b["status"] = "superseded"
    assert any("exactly one production baseline" in e for e in mod.check_registry(bad))


def test_the_chart_and_tables_carry_one_band_per_comparator():
    """Jerry 2026-10-03: a visual separator for each thing a screen is compared to.  Sections are keyed by
    (release, actual comparator) for the current AND the earlier releases (Codex HOLD on #697): the
    release as served first, then each named comparator (``vs_group``)."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text()); page = mod.page
    prod = mod.comparator_release(reg)                           # the band that leads is the screen comparator
    labels = [label for label, _, _ in mod.SECTIONS]
    if any(s["vs"] == prod for s in reg["screens"]):
        assert labels[0].startswith(f"against release {prod} as served")
    else:                                                          # just promoted: nothing reads vs prod yet
        assert all(c["kind"] == "prev" for c in mod.COMPARATORS)
        assert f"No screen has read against release {prod} yet" in page
    assert len(labels) == len(set(labels))
    named = [s for s in reg["screens"] if s.get("vs_group")]
    assert {"v43cla", "x36a", "x36c", "depth-screen"} <= {s["id"] for s in named}
    for s in named:
        sec = [c for c in mod.COMPARATORS if s in c["items"]]
        assert len(sec) == 1 and sec[0]["group"] == s["vs_group"] and sec[0]["release"] == s["vs"], s["id"]
        assert f'Screens against {mod.esc(sec[0]["label"])}' in page   # its own sub-table
    for rel in {s["vs"] for s in reg["screens"]}:
        assert any(c["release"] == rel and c["group"] is None for c in mod.COMPARATORS)
    assert page.count('class="sepband"') == len(mod.SECTIONS)
    assert sum(len(mod._chart_rows(items, kind)) for _, kind, items in mod.SECTIONS) == len(mod.rows)
    for c in mod.COMPARATORS:                                      # a section never mixes comparators
        assert len({(s["vs"], s.get("vs_group")) for s in c["items"]}) == 1, c["label"]
        if c["group"] is None:                                     # ... and "as served" means exactly that
            assert all(s["comparator"].startswith(f"release {c['release']} as served") for s in c["items"]), c["label"]
    bad = copy.deepcopy(reg); bad["screens"][0]["vs_group"] = " "
    assert any("vs_group" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); x = next(s for s in bad["screens"] if s["id"] == "x36a"); del x["vs_group"]
    assert any("x36a" in e and "vs_group" in e for e in mod.check_registry(bad))   # an untagged control is refused


def test_a_promotion_keeps_every_named_comparator_in_its_own_section():
    """Promotion regression (36 -> 38, and any later one): once another release is production, the reads
    against release 36 are a closed comparator -- and v43cla (read against the combo) and the release-30
    controls must still sit in their own sections, not in the 'as served' one.  ``old`` is the current
    production release, promoted once more here; ``read_vs`` is the release the combo screens were read
    against (36), which stays fixed whichever release is production."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    old = mod.production_release(reg)
    read_vs = next(s for s in reg["screens"] if s["id"] == "v43cla")["vs"]
    promoted = copy.deepcopy(reg)
    promoted.pop("screen_comparator", None)                       # a confirmed promotion: comparator == production
    new = copy.deepcopy(next(b for b in promoted["baseline"] if b["release"] == old)); new["release"] = old + 2
    for b in promoted["baseline"]: b["status"] = "superseded"
    promoted["baseline"].append(new)
    assert mod.check_registry(promoted) == [] and mod.production_release(promoted) == old + 2
    secs = mod.comparator_sections(promoted)
    assert all(c["kind"] == "prev" and c["label"].endswith("closed comparator") for c in secs)   # nothing reads vs old + 2
    def section_of(sid): return next(c for c in secs if any(s["id"] == sid for s in c["items"]))
    served = next(c for c in secs if c["release"] == read_vs and c["group"] is None)
    assert "v43cla" not in {s["id"] for s in served["items"]} and len(served["items"]) >= 12
    assert section_of("v43cla")["group"] and [s["id"] for s in section_of("v43cla")["items"]] == ["v43cla"]
    for sid in ("x36a", "x36c", "depth-screen"):
        c = section_of(sid); assert c["group"] and c["release"] == 30 and [s["id"] for s in c["items"]] == [sid]
    before = {(c["release"], c["group"]): [s["id"] for s in c["items"]] for c in mod.comparator_sections(reg)}
    after = {(c["release"], c["group"]): [s["id"] for s in c["items"]] for c in secs}
    assert before == after                                         # membership never depends on which release is production


def test_rows_lead_with_a_short_title_and_takeaway_and_production_is_one_card():
    """Jerry 2026-10-03: the long candidate/note text was hard to digest, and one production section is
    enough.  Every screen leads with a short title and a one-sentence takeaway (the full record sits in a
    closed toggle); the current release is one card and every earlier release is one line."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text()); page = mod.page
    for s in reg["screens"] + reg["context_screens"]:
        assert mod.esc(s["title"]) in page and mod.esc(s["takeaway"]) in page, s["id"]
        assert mod.esc(s["note"]) in page                           # the record is kept, behind the toggle
    assert page.count("<summary>full record</summary>") == len(reg["screens"]) + len(reg["context_screens"])
    assert page.count('<article class="card') == 1                  # one production card
    for b in reg["baseline"]:
        assert mod.esc(b["oneline"]) in page
        if b["status"] != "production":
            assert mod.esc(b["recipe"]) not in page                 # earlier releases are one line each
    for key, lst in (("title", "screens"), ("takeaway", "screens"), ("oneline", "baseline")):
        bad = copy.deepcopy(reg); del bad[lst][0][key]
        assert any(key in e for e in mod.check_registry(bad)), key
    bad = copy.deepcopy(reg); bad["screens"][0]["title"] = "x" * (mod.TITLE_MAX + 1)
    assert any("title" in e for e in mod.check_registry(bad))


def _unavailable_row(reg, rid="zz-unavail"):
    """A copy of a sealed single-read screen turned into a finished screen with no estimate."""
    s = copy.deepcopy(next(x for x in reg["screens"] if "results" not in x and x["status"] == "sealed"))
    s.update(id=rid, status="unavailable", point=None, lo=None, hi=None,
             note="the pinned reader refused: every window had SE = 0")
    return s


def test_an_unavailable_screen_carries_no_estimate_and_says_why():
    """`unavailable` is a finished state without a strength estimate (v52ec, #676): it passes only with
    point/lo/hi all null and a note; a numeric point is refused, and sealed-without-a-read still fails."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    ok = copy.deepcopy(reg); ok["screens"].append(_unavailable_row(ok))
    assert mod.check_registry(ok) == []                                        # (a)
    for point in ({"point": 0.0, "lo": -0.01, "hi": 0.01}, {"point": 0.02, "lo": 0.01, "hi": 0.03}):
        bad = copy.deepcopy(reg); row = _unavailable_row(bad); row.update(point); bad["screens"].append(row)
        assert any("unavailable screen carries no estimate" in e for e in mod.check_registry(bad))   # (b)
    bad = copy.deepcopy(reg); row = _unavailable_row(bad); row["note"] = "  "; bad["screens"].append(row)
    assert any("non-empty note" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); row = _unavailable_row(bad); row["status"] = "sealed"; bad["screens"].append(row)
    assert any("sealed without a read" in e for e in mod.check_registry(bad))   # (d)
    bad = copy.deepcopy(reg); row = _unavailable_row(bad); row["status"] = "bogus"; bad["screens"].append(row)
    assert any("unknown status" in e for e in mod.check_registry(bad))


def test_an_unavailable_screen_has_no_chart_mark_and_is_never_pending(tmp_path):
    """(c) an unavailable row draws no point, interval or pending diamond (nothing on the zero line) and
    its table row reads 'no estimate (unavailable)', never 'pending'."""
    import shutil
    shutil.copy(HERE / "build_v2.py", tmp_path / "build_v2.py")
    reg = json.loads((HERE / "registry.json").read_text())
    reg["screens"].append(_unavailable_row(reg, "zz-unavail"))
    (tmp_path / "registry.json").write_text(json.dumps(reg))
    spec = importlib.util.spec_from_file_location("build_v2_tmp", tmp_path / "build_v2.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.check_registry(reg) == []
    lines = mod.SVG.split("\n")
    start = next(i for i, l in enumerate(lines) if 'class="lab name' in l and ">zz-unavail · " in l)
    end = next(i for i in range(start + 1, len(lines)) if 'class="lab name' in lines[i] or "sepband" in lines[i] or lines[i] == "</svg>")
    row_svg = "\n".join(lines[start:end])
    assert 'class="pt' not in row_svg and 'class="ci' not in row_svg and "<rect" not in row_svg and "<circle" not in row_svg
    assert "pending" not in row_svg and "no estimate (unavailable)" in row_svg
    lead = next(l for l in mod.page.split("\n") if l.startswith('<tr class="lead"><td class="mono">zz-unavail<'))
    assert "pending" not in lead and "no estimate (unavailable)" in lead and "chip wait" not in lead
    # every unavailable row in the committed registry renders the same way
    for s in (x for x in mod.R["screens"] if x["status"] == "unavailable"):
        lead = next(l for l in mod.page.split("\n") if l.startswith(f'<tr class="lead"><td class="mono">{s["id"]}<'))
        assert "pending" not in lead and "no estimate (unavailable)" in lead


def test_seeds_are_an_explicit_window_list_never_a_range():
    """#707 2026-10-06: v35d's seeds "29960910..30360910" were read as two endpoints and an audit
    reported zero overlaps for its 30260910 window, which sat inside the run-C training span.  Seeds
    are the explicit window seed0s; the two non-window rows are allow-listed with a computed expansion."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    assert mod.check_registry(reg) == []
    v35d = next(s for s in reg["screens"] if s["id"] == "v35d")
    assert 30260910 in mod.seed_windows(v35d["seeds"]) and len(mod.seed_windows(v35d["seeds"])) == 5
    drt = next(s for s in reg["screens"] if s["id"] == "v38drt")
    assert mod.seed_windows(drt["seeds"]) == [39460910, 39560910, 39660910, 39760910, 39860910,
                                              39960910, 40060910, 40160910, 40360910, 40460910]
    for text in ("29960910..30360910", "1 2, 3", "1  2", "1 2 (Perf), 3 (cloud)", "five windows",
                 "1 2 (Perf);3", "", None, "1 2 (Perf) (cloud)"):
        bad = copy.deepcopy(reg); bad["screens"][0]["seeds"] = text
        assert any("explicit list of window seed0s" in e for e in mod.check_registry(bad)), text
    for text in ("1", "1 2 3", "1 2 (cloud)", "1 2 (Perf); 3 4 (cloud)", "7 8; 9"):
        ok = copy.deepcopy(reg); ok["screens"][0]["seeds"] = text
        assert mod.check_registry(ok) == [], text
    bad = copy.deepcopy(reg); bad["screens"][0]["seeds"] = "1 2 1"
    assert any("repeat a window seed0" in e for e in mod.check_registry(bad))
    # a legacy row keeps its exact allow-listed text, and its expansion is recomputed
    assert mod.legacy_expansion("626710000..626710259") == {"kind": "deal seeds", "first": 626710000, "count": 260}
    assert mod.legacy_expansion("deal indices 2080..4159 (all-ranks-known-banker-v1)") == {
        "kind": "deal indices", "first": 2080, "count": 2080}
    bad = copy.deepcopy(reg)
    next(s for s in bad["screens"] if s["id"] == "depth-screen")["seeds"] = "626710000..626710359"
    assert any("legacy seeds text changed" in e for e in mod.check_registry(bad))
    saved = dict(mod.LEGACY_SEEDS["depth-screen"])
    try:
        mod.LEGACY_SEEDS["depth-screen"]["count"] = 261
        assert any("legacy seeds expand to" in e for e in mod.check_registry(reg))
    finally:
        mod.LEGACY_SEEDS["depth-screen"] = saved
    # a planned or running row may not have its windows yet
    ok = copy.deepcopy(reg); ok["screens"][0].pop("seeds"); ok["screens"][0]["status"] = "running"
    ok["screens"][0].update(point=None, lo=None, hi=None)
    ok["screens"][0].pop("results", None)
    assert not any("seeds" in e for e in mod.check_registry(ok))


def test_production_and_screen_comparator_are_separate_and_a_pending_comparator_says_so():
    import copy, json
    from pathlib import Path
    import build_v2 as b
    reg = json.loads((Path(b.__file__).parent / "registry.json").read_text())
    assert b.production_release(reg) == 42
    # Pending: new screens stay on release 38 and the page says production is 42 and the switch is pending.
    assert reg["screen_comparator"]["status"] == "pending" and b.comparator_release(reg) == 38
    page = b.PAGE if hasattr(b, "PAGE") else (Path(b.__file__).parent / "atlas_v2.html").read_text()
    assert "read against <b>release 38 as served</b>" in page
    assert "Production is release 42" in page and "pending" in page
    assert "Screens against release 38 (the screen comparator; production is release 42)" in page
    # Without the field, the comparator falls back to production (the pre-existing behaviour).
    plain = copy.deepcopy(reg); plain.pop("screen_comparator")
    assert b.comparator_release(plain) == 42
