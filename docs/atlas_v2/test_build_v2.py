"""Atlas v2 invariants: the registry is the only source, the page rebuilds from it, and the checks refuse
the mixes the old page suffered (Codex HOLD on #603)."""
import copy, importlib.util, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("build_v2", HERE / "build_v2.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_committed_page_matches_the_registry():
    r = subprocess.run([sys.executable, str(HERE / "build_v2.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


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
    page = (HERE / "atlas_v2.html").read_text()
    for r in slots:
        assert f'{fam["id"]} · {r["arm"]}' in page                # one chart row and one table line per arm
    assert "point and 95% interval" not in page                    # no blanket coverage label
    # partial primaries are refused; a mis-declared confidence is refused
    bad = copy.deepcopy(reg); f = next(s for s in bad["screens"] if "results" in s)
    f["results"][0].update(point=0.01, lo=-0.01, hi=0.03)
    assert any("no partial primary results" in e for e in mod.check_registry(bad))
    bad = copy.deepcopy(reg); f = next(s for s in bad["screens"] if "results" in s); f["results"][0]["confidence"] = 0.9
    assert any("confidence must be declared" in e for e in mod.check_registry(bad))


def test_every_screen_reaches_the_chart_and_the_table():
    reg = json.loads((HERE / "registry.json").read_text()); page = (HERE / "atlas_v2.html").read_text()
    for s in reg["screens"] + reg["context_screens"]:
        assert page.count(s["id"]) >= 2, s["id"]          # chart label + table cell
        assert s["instrument_kind"] in page
