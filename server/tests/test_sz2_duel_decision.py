"""Exercise the S156 decision on the saved UTH reader format."""
import hashlib
import json
import math
from pathlib import Path

import pytest


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "server/scripts"))
    import sz2_duel_decision as reader

    medium, small = "a" * 64, "b" * 64
    predeclare = hashlib.sha256(reader.PREDECLARE.read_bytes()).hexdigest()
    arm = {"seed0": 2665000000, "deals": 1000}
    for tag, role, sha in (("ex", "exploiter", medium), ("def", "defender", small)):
        short = sha[:8]
        arm[f"{tag}_package_sha256"] = sha
        arm[f"{role}_name"] = f"pv-search-ft500-sc8-ushare{short}-uvalue{short}-ureply{short}"
    recipe = {"schema": "utd-h2h-recipe-r1", "duel": "UTH", "reader_sha256": reader.READER_SHA,
              "predeclare_sha256": predeclare, "arms": {"SZ2-A": arm}}
    recipe_path = tmp_path / "recipe.json"
    result_path = tmp_path / "SZ2-A.read.json"
    counts = {"decisions": 64000, "play_fallback": 0, "search": 64000, "belief_fallback": 0,
              "buries": 1000, "bury_fallback": 0, "declares": 3500, "declare_abandon": 0}
    checks = [{"check": name, "verdict": "VALID", "reasons": []} for name in (
        "completion", "names", "arm_fault_ceilings", "worlds_delivered", "served_belief_fallback",
        "completion_shape", "bbw_fallback_ceiling", "unified_prior", "unified_readout", "outcome_consistency")]
    checks[-1]["detail"] = {"rows": 2000, "inconsistent": 0}
    sums = "c" * 64
    result = {
        "schema": "uth-read-r1", "duel": "UTH", "arm": "SZ2-A", "reader_sha256": reader.READER_SHA,
        "exploiter": {"name": arm["exploiter_name"], "package_sha256": medium},
        "defender": {"name": arm["defender_name"], "package_sha256": small},
        "validity": {"verdict": "VALID", "checks": checks},
        "binding": {"predeclare_sha256": predeclare, "sums_sha256": sums, "duel_jsonl_sha256": "d" * 64},
        "counts": {"ex": counts.copy(), "r45": counts.copy()},
        "outcome": {
            "levels": {"n": 1000, "mean": 0.02, "lb80": 0.01, "lb95_one_sided": 0, "ci95": [-0.02, 0.07]},
            "points": {"n": 1000, "mean": 0.2, "lb80": 0.01, "lb95_one_sided": 0, "ci95": [-0.07, 1.8]},
            "bar": {"beats_mean": 0.02, "beats_lb80": 0, "ni_mean": -0.02, "ni_lb80": -0.04},
            "verdict": "BEATS",
        },
    }

    def argv():
        recipe_path.write_text(json.dumps(recipe))
        recipe_sha = hashlib.sha256(recipe_path.read_bytes()).hexdigest()
        result["binding"].update(recipe_sha256=recipe_sha,
                                 terminal=f"UTD DONE 2026-11-23T18:00:00Z recipe={recipe_sha} rows=2000 sums={sums} rc=0")
        result_path.write_text(json.dumps(result))
        result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
        return ["--result", str(result_path), "--result-sha256", result_sha,
                "--recipe", str(recipe_path), "--recipe-sha256", recipe_sha,
                "--medium-sha256", medium, "--small-sha256", small]

    return reader, result, recipe, argv


@pytest.mark.parametrize(("mean", "lb80", "expected_rc"), [
    (0.02, 0.01, 0),
    (0.02, math.nextafter(0.0, math.inf), 0),
    (math.nextafter(0.02, 0.0), 0.01, 3),
    (0.02, 0.0, 3),
    (0.03, -0.00001, 3),
])
def test_decision_uses_unrounded_paired_levels(saved, capsys, mean, lb80, expected_rc):
    reader, result, _, argv = saved
    result["outcome"]["levels"].update(mean=mean, lb80=lb80, lb95_one_sided=-0.01)
    result["outcome"]["verdict"] = "BEATS" if expected_rc == 0 else "NON-INFERIOR"
    assert reader.main(argv()) == expected_rc
    got = json.loads(capsys.readouterr().out)
    assert got["decision"] == ("SIZE-PAYS" if expected_rc == 0 else "MISSES-DEV-BAR")
    assert got["paired_deals"] == 1000 and got["mean_levels_per_round"] == mean and got["lb80_levels_per_round"] == lb80


@pytest.mark.parametrize(("edit", "message"), [
    (lambda r, p: r.update(arm="SZ2-B"), "not decision A"),
    (lambda r, p: r.update(reader_sha256="d" * 64), "frozen UTH reader"),
    (lambda r, p: p.update(predeclare_sha256="d" * 64), "S156 predeclaration"),
    (lambda r, p: p["arms"]["SZ2-A"].update(seed0=2665002000, deals=20), "registered 1,000-deal"),
    (lambda r, p: p["arms"]["SZ2-A"].update(def_package_sha256="c" * 64), "frozen readout"),
    (lambda r, p: r["defender"].update(name="another control"), "side identities"),
    (lambda r, p: r["validity"].update(verdict="DEV_INVALID"), "validity checks"),
    (lambda r, p: r["validity"]["checks"].pop(), "required reader validity checks"),
    (lambda r, p: r["validity"]["checks"][-1]["detail"].update(rows=1999), "outcome counts"),
    (lambda r, p: r["outcome"]["levels"].update(n=999), "invalid levels statistics"),
    (lambda r, p: r["outcome"]["levels"].pop("n"), "invalid levels statistics"),
    (lambda r, p: r["outcome"]["levels"].update(mean=float("nan")), "invalid levels statistics"),
    (lambda r, p: r["outcome"]["levels"].update(lb80=float("inf")), "invalid levels statistics"),
    (lambda r, p: r["outcome"].update(verdict="WORSE"), "disagrees with the S156 bar"),
])
def test_decision_refuses_misbound_and_invalid_saved_results(saved, capsys, edit, message):
    reader, result, recipe, argv = saved
    edit(result, recipe)
    assert reader.main(argv()) == 2
    output = capsys.readouterr()
    assert output.out == "" and message in output.err


@pytest.mark.parametrize("which", ["result", "recipe"])
def test_decision_refuses_content_drift_against_independent_sha(saved, capsys, which):
    reader, _, _, argv = saved
    args = argv()
    path = Path(args[args.index(f"--{which}") + 1])
    path.write_bytes(path.read_bytes() + b"\n")
    assert reader.main(args) == 2
    output = capsys.readouterr()
    assert output.out == "" and f"{which} differs from its independent SHA-256" in output.err


def test_decision_refuses_the_legacy_reader_even_when_the_recipe_agrees(saved, capsys):
    reader, result, recipe, argv = saved
    old = "d5de029245fa0b5e4f987bf5b0041cf654817d1f7f437ccbe469776f5fb18bf7"
    result["reader_sha256"] = recipe["reader_sha256"] = old
    assert reader.main(argv()) == 2
    output = capsys.readouterr()
    assert output.out == "" and "frozen UTH reader" in output.err
