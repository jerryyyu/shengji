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
    prod = mod.production_release(reg)
    page = mod.page                                               # a fresh build; the page is not tracked
    assert f"Screens against release {prod} (the current production)" in page
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
    prod = mod.production_release(reg)
    labels = [label for label, _, _ in mod.SECTIONS]
    assert labels[0].startswith(f"against release {prod} as served")
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
    """Promotion regression (36 -> 38): once another release is production, the reads against release 36
    become a closed comparator -- and v43cla (read against the combo) and the release-30 controls must
    still sit in their own sections, not in the 'as served' one."""
    mod = _load(); reg = json.loads((HERE / "registry.json").read_text())
    old = mod.production_release(reg)
    promoted = copy.deepcopy(reg)
    new = copy.deepcopy(next(b for b in promoted["baseline"] if b["release"] == old)); new["release"] = old + 2
    for b in promoted["baseline"]: b["status"] = "superseded"
    promoted["baseline"].append(new)
    assert mod.check_registry(promoted) == [] and mod.production_release(promoted) == old + 2
    secs = mod.comparator_sections(promoted)
    assert all(c["kind"] == "prev" and c["label"].endswith("closed comparator") for c in secs)   # nothing reads vs 38 yet
    def section_of(sid): return next(c for c in secs if any(s["id"] == sid for s in c["items"]))
    served = next(c for c in secs if c["release"] == old and c["group"] is None)
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
