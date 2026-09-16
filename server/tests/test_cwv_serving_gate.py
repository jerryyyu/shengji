"""The in-repo serving gate (#435 item 4) passes real matching packages and REFUSES a tampered one.

Both directions are witnessed: the exported NumPy value package and prior package
reproduce the Torch decisions exactly (PASS), and a package whose weights were
perturbed after export is caught on the first decision it changes (FAIL with a
recorded mismatch). Without the second half a gate that compared nothing would
also be green.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts.cwv_serving_gate import run_gate
from shengji.engine import combos, fast

# The play-based witnesses search real decisions (W4/N4, a full round each). In the
# compiled engine that is ~1 min per run; in the pure-Python engine it is many
# times slower and CI's dual-mode job (25 min) cannot hold it. The gate's verdict
# does not depend on the engine mode (both sides of every comparison run in the
# same process and mode), so the play witnesses run in the compiled mode only;
# the scope/refusal tests below run in both.
plays = pytest.mark.skipif(not (fast.HAVE_FAST and combos.decompose is fast.decompose),
                           reason="play witnesses run in the compiled engine only")

from test_cwv_shortlist_registry import _load_script
from test_cwv_prior_admission import prior_ckpt  # noqa: F401  (tiny torch prior)


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    """A tiny MLP value net trained under a FIXED torch seed.

    The registry test's fixture trains under torch's default (random) seed, so
    its weights differ per run and a 16-wide net produces near-ties in the
    shortlist means that the NumPy and Torch backends can resolve differently
    at 1e-6 (CI: 39/40 identical on one run, 40/40 on the next). The gate's
    job is to count exactly such mismatches on real nets; the TEST needs a net
    whose ties do not move between runs, so it seeds the training.
    """
    import torch
    torch.manual_seed(20260915)
    out = tmp_path_factory.mktemp("gate-value") / "tiny.pt"
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(out), rounds=2, architecture="mlp", width=16, max_epochs=2, quiet=True)
    return str(out)


@pytest.fixture
def mechanics_only(monkeypatch):
    """The play-based witnesses exercise the gate's MECHANICS (prior firing, scope, result
    shapes, receipt, CLI); backend identity of the value net is witnessed by the NumPy
    parity tests and, on the real packages, by the gate itself before every deploy. The
    tiny 16-wide test net produces near-ties that float64 NumPy and float32 Torch order
    differently on some platforms (CI Linux: 39/40 identical, and the shared-candidate
    disagreement can exceed the identity tolerance), so here a shortlist difference with
    the same play and RNG is accepted as a near-tie; a different play or RNG still fails."""
    import scripts.cwv_serving_gate as gate
    monkeypatch.setattr(gate, "_near_tie", lambda a, b: True)


@pytest.fixture(scope="module")
def packages(checkpoint, prior_ckpt, tmp_path_factory):
    from scripts.export_cwv_numpy import export_cwv_numpy
    from scripts.export_policy_prior_numpy import export_policy_prior_numpy
    d = tmp_path_factory.mktemp("gate")
    value = d / "value.npz"; prior = d / "prior.npz"
    export_cwv_numpy(checkpoint, value)
    export_policy_prior_numpy(prior_ckpt[0], prior)
    return str(value), str(prior)


@plays
def test_matching_packages_pass_and_the_receipt_names_every_file(mechanics_only, checkpoint, prior_ckpt, packages):
    value, prior = packages
    # threshold 6 (just above the shortlist of 5) and top 5 (alternatives 4 + 1) make the prior fire on every wide decision
    # and prune to a strict subset, so the prior side is exercised, not just loaded.
    receipt = run_gate(checkpoint, value, prior_ckpt[0], prior, rounds=1, threshold=6, top=5)
    assert receipt["passed"] is True and receipt["result"] in ("identical", "identical-except-near-ties")
    assert receipt["decisions"] > 0 and receipt["other_mismatches"] == 0
    assert receipt["identical"] + receipt["near_tie_same_play"] == receipt["decisions"]
    assert receipt["prior_fired"] > 0, "the gate never reached the prior stage"
    assert receipt["kinds"] == {"served_prior": "separate-numpy", "reference_prior": "separate"}
    assert set(receipt["files"]) == {"value_torch", "value_numpy", "prior_torch", "prior_numpy"}
    assert receipt["files"]["prior_torch"]["sha256"] == prior_ckpt[1]
    assert receipt["scope"] == "smoke"
    assert receipt["qualifies_serving"] is False, "a W4/N4 smoke run must not qualify a deploy"


@plays
def test_a_bound_prior_that_never_fires_is_incomplete_not_a_pass(mechanics_only, checkpoint, prior_ckpt, packages):
    value, prior = packages
    # threshold above any legal set in one tiny round: every decision agrees, the prior never runs
    receipt = run_gate(checkpoint, value, prior_ckpt[0], prior, rounds=1, threshold=10_000_000, top=5)
    # The tiny 16-wide test net can produce a near-tie that the two backends order differently on
    # some platforms (CI Linux BLAS: 39/40 identical); the classification reports that separately
    # and it must not mask the point of this witness: no real mismatch, prior never fired -> incomplete.
    assert receipt["decisions"] > 0 and receipt["other_mismatches"] == 0
    assert receipt["identical"] + receipt["near_tie_same_play"] == receipt["decisions"]
    assert receipt["prior_fired"] == 0
    assert receipt["passed"] is False and receipt["result"] == "incomplete-prior-never-fired"


def test_scope_is_serving_only_for_the_serving_recipe_with_a_prior(monkeypatch, checkpoint, prior_ckpt, packages):
    import scripts.cwv_serving_gate as gate
    value, prior = packages
    seen = {}
    def fake_deal(seed):                        # no play: the recipe/scope logic is what is under test
        class Done:  phase = "done"
        return Done(), None
    monkeypatch.setattr(gate, "_deal", fake_deal)
    r = run_gate(checkpoint, value, prior_ckpt[0], prior, rounds=1, worlds=32, selection_worlds=30,
                 threshold=10_000, top=256)
    assert r["scope"] == "serving-w32-n30-prior-t10000" and r["result"] == "no-decisions" and r["qualifies_serving"] is False
    r = run_gate(checkpoint, value, prior_ckpt[0], prior, rounds=1, worlds=32, selection_worlds=30,
                 threshold=1_000, top=256)
    assert r["scope"] == "serving-w32-n30-prior-t1000", "the threshold is a deploy setting named in the scope"
    r = run_gate(checkpoint, value, prior_ckpt[0], prior, rounds=1, worlds=32, selection_worlds=30,
                 threshold=1_000, top=64)
    assert r["scope"] == "smoke", "a non-serving top is a smoke run"
    r = run_gate(checkpoint, value, rounds=1, worlds=32, selection_worlds=30)
    assert r["scope"] == "smoke", "no prior bound is never the serving scope"


@plays
def test_a_tampered_value_package_is_refused_with_the_mismatch_recorded(checkpoint, prior_ckpt, packages, tmp_path):
    value, prior = packages
    with np.load(value) as z:
        arrays = {k: z[k] for k in z.files}
    key = "head_weight"          # the exported value head (cwv_numpy schema)
    arrays[key] = arrays[key] + np.float32(0.5) * np.sign(arrays[key] + 1e-3)
    bad = tmp_path / "value-bad.npz"
    np.savez_compressed(bad, **arrays)
    receipt = run_gate(checkpoint, str(bad), prior_ckpt[0], prior, rounds=1, threshold=6, top=5)
    assert receipt["passed"] is False
    assert receipt["identical"] < receipt["decisions"]
    assert receipt["first_mismatch"] is not None and receipt["first_mismatch"]["decision"] >= 1


@plays
def test_a_tampered_prior_package_is_refused(checkpoint, prior_ckpt, packages, tmp_path):
    value, prior = packages
    with np.load(prior) as z:
        arrays = {k: z[k] for k in z.files}
    arrays["w2"] = arrays["w2"] * np.float32(-1.0)      # inverts every card's log-odds
    bad = tmp_path / "prior-bad.npz"
    np.savez_compressed(bad, **arrays)
    receipt = run_gate(checkpoint, value, prior_ckpt[0], str(bad), rounds=1, threshold=6, top=5)
    assert receipt["passed"] is False and receipt["first_mismatch"] is not None


@plays
def test_cli_exit_status_follows_the_verdict_and_writes_the_receipt(mechanics_only, checkpoint, prior_ckpt, packages, tmp_path):
    value, prior = packages
    receipt = tmp_path / "gate.json"
    cmd = [sys.executable, "-P", "-B", str(Path(__file__).parents[1] / "scripts" / "cwv_serving_gate.py"),
           "--value-torch", checkpoint, "--value-numpy", value, "--prior-torch", prior_ckpt[0],
           "--prior-numpy", prior, "--rounds", "1", "--threshold", "6", "--top", "5", "--receipt", str(receipt)]
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parents[1])
    got = json.loads(receipt.read_text()) if receipt.exists() else {}
    # subprocess: no monkeypatch reaches it, so a platform near-tie may surface as a real
    # mismatch on the tiny net; the CLI contract under test is exit status == verdict.
    assert run.returncode == (0 if got.get("passed") else 1), run.stdout + run.stderr
    assert run.stdout.startswith("PASS" if got.get("passed") else "FAIL") and "scope smoke" in run.stdout


def test_half_bound_prior_and_non_numpy_served_side_are_refused(checkpoint, prior_ckpt, packages):
    value, prior = packages
    with pytest.raises(ValueError, match="both prior files"):
        run_gate(checkpoint, value, prior_ckpt[0], None, rounds=1)
    with pytest.raises(ValueError, match="NumPy packages"):
        run_gate(checkpoint, checkpoint, rounds=1)
