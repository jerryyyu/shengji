"""The score runner must refuse a launch it cannot honestly aggregate.

Each test drives `preflight` to a REFUSAL on known-bad input. A preflight only
ever exercised on a good launch is not a preflight — it is a comment. The
dirty-tree and compiled-engine guards fire first and are stubbed out here so
the check under test is the one being proven.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import pilot_run as PR                                          # noqa: E402

from shengji.engine import combos, fast                         # noqa: E402

# The pilot REQUIRES the compiled engine, and `preflight` refuses without it —
# correctly, since a pure-Python scoring run is not the pinned experiment. So
# these cases are only meaningful under SHENGJI_FAST=1; skipping is honest,
# whereas relaxing the guard to make a pure run pass would delete the check.
pytestmark = pytest.mark.skipif(
    not fast.HAVE_FAST or combos.decompose is not fast.decompose,
    reason="compiled engine inactive; run with SHENGJI_FAST=1")

# Point at the newest artifact that SATISFIES the registered contract. v4 is
# superseded (its population followed corpus order and it fails the source
# marginals), so the runner correctly refuses it; these cases skip rather than
# pretend to pass until v5 is frozen from a clean commit.
import pilot_states as PS                                       # noqa: E402


def _gate(side):
    for ver in ("v5", "v4"):
        path = os.path.join(ROOT, "rl_data", f"pilot_{side}512.{ver}.json")
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        if not PS.check_contract(d["states"], d["requested"],
                                 d["replay_errors"]):
            return path
    return None


DEV, CALIB = _gate("dev"), _gate("calib")
pytestmark = [
    pytestmark,
    pytest.mark.skipif(DEV is None or CALIB is None,
                       reason="no contract-satisfying gate artifact yet "
                              "(v5 pending; v4 is superseded)"),
]


def _args(tmp_path, **over):
    a = dict(states=DEV, expected_states_sha256=PR.digest(DEV), limit=0,
             shard_index=0, shard_count=1,
             out=str(tmp_path / "shard.jsonl"))
    a.update(over)
    return argparse.Namespace(**a)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Neutralise the guards that precede the ones under test."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv("SHENGJI_FAST", "1")
    for f in PR.SAMPLER_FLAGS:
        monkeypatch.delenv(f, raising=False)
    monkeypatch.setattr(PR, "git_output", lambda *a, **k: "")


def test_refuses_a_wrong_state_digest(tmp_path):
    with pytest.raises(RuntimeError, match="digest mismatch"):
        PR.preflight(_args(tmp_path, expected_states_sha256="0" * 64))


def test_refuses_when_no_digest_is_pinned(tmp_path):
    with pytest.raises(RuntimeError, match="expected-states-sha256"):
        PR.preflight(_args(tmp_path, expected_states_sha256=""))


@pytest.mark.parametrize("flag", PR.SAMPLER_FLAGS)
def test_refuses_an_enabled_sampler_flag(tmp_path, monkeypatch, flag):
    """A flag would change the belief distribution every arm searches under."""
    monkeypatch.setenv(flag, "1")
    with pytest.raises(RuntimeError, match="sampler flag"):
        PR.preflight(_args(tmp_path))


def test_refuses_a_full_run_on_the_CALIB_side(tmp_path):
    with pytest.raises(RuntimeError, match="DEV side"):
        PR.preflight(_args(tmp_path, states=CALIB,
                           expected_states_sha256=PR.digest(CALIB)))


def test_refuses_a_full_run_whose_artifact_breaks_the_contract(tmp_path):
    """A short or unbalanced state set cannot be a full DEV result."""
    d = json.load(open(DEV))
    d["states"] = d["states"][:500]
    p = tmp_path / "short.json"
    p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match="registered contract"):
        PR.preflight(_args(tmp_path, states=str(p),
                           expected_states_sha256=PR.digest(str(p))))


def test_a_limited_run_is_labelled_smoke_and_a_full_run_is_not(tmp_path):
    """The label is what stops a smoke aggregating as a DEV verdict."""
    *_, phase, _ = PR.preflight(_args(tmp_path, limit=8))
    assert phase == "smoke"
    *_, phase, _ = PR.preflight(_args(tmp_path))
    assert phase == "full"


def test_the_good_launch_still_passes(tmp_path):
    """Guards against the refusals being unconditional."""
    spec, experiment, states, phase, sha = PR.preflight(_args(tmp_path))
    assert phase == "full"
    assert len(experiment) == 512 and len(states) == 512
    assert sha == PR.digest(DEV)
