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

# PINNED to the tracked v6 gate artifacts. The previous version searched for
# "the newest artifact that satisfies the contract" and skipped if none did —
# so a missing or broken gate set produced a green suite instead of a failure
# (Codex). If these files are absent the tests MUST fail.
DEV = os.path.join(ROOT, "rl_data", "pilot_dev512.v6.json")
CALIB = os.path.join(ROOT, "rl_data", "pilot_calib512.v6.json")


def _args(tmp_path, **over):
    a = dict(states=DEV, expected_states_sha256=PR.digest(DEV), limit=0,
             shard_index=0, shard_count=8,
             out=str(tmp_path / "shard.json"),
             **{k: v for k, v in PR.FULL_DEV_PROTOCOL.items()
                if k in ("budget", "band", "salt")},
             work=PR.FULL_DEV_PROTOCOL["work_target"],
             full_proposal_worlds=12, oracle_worlds=12, report_worlds=12)
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
    # 512 experiment states striped over the registered 8 shards
    assert len(experiment) == 512 and len(states) == 64
    assert sha == PR.digest(DEV)


# --- D: a typo must not launch a valid-looking wrong experiment -------------
# Recording a CLI value is not checking it: mistyped shards carry a manifest
# consistent with themselves, so eight of them aggregate cleanly as long as
# they share the typo (Codex). Every registered field is compared.

@pytest.mark.parametrize("field,bad", [
    ("budget", 13),
    ("work", 160),
    ("band", 0.10),
    ("full_proposal_worlds", 11),
    ("oracle_worlds", 24),
    ("report_worlds", 6),
    ("salt", "pilot-run-v2"),
    ("shard_count", 4),
])
def test_full_run_refuses_any_off_protocol_value(tmp_path, field, bad):
    with pytest.raises(RuntimeError, match="registered protocol"):
        PR.preflight(_args(tmp_path, **{field: bad}))


def test_full_run_refuses_a_different_but_contract_valid_artifact(tmp_path):
    """CALIB satisfies the contract yet is NOT the registered DEV set."""
    with pytest.raises(RuntimeError, match="DEV side|registered protocol"):
        PR.preflight(_args(tmp_path, states=CALIB,
                           expected_states_sha256=PR.digest(CALIB)))


def test_the_registered_launch_still_passes(tmp_path):
    """Guards against the protocol check rejecting everything."""
    spec, experiment, states, phase, sha = PR.preflight(_args(tmp_path))
    assert phase == "full" and len(experiment) == 512
    assert sha == PR.FULL_DEV_PROTOCOL["states_sha256"]


def test_full_run_refuses_an_altered_arms_tuple(monkeypatch, tmp_path):
    """The ballot arms are part of the registered protocol.

    Swapping an arm keeps every numeric parameter valid, so without this the
    shards would agree with each other and aggregate cleanly while scoring a
    different experiment.
    """
    monkeypatch.setattr(PR, "ARMS", ("current", "v3", "random_fill", "quota",
                                     "mc_more_full_work", "SOMETHING_ELSE"))
    with pytest.raises(RuntimeError, match="required_arms"):
        PR.preflight(_args(tmp_path))


def test_the_gate_artifacts_exist_and_are_tracked():
    """A missing gate artifact must fail, never skip."""
    for p in (DEV, CALIB):
        assert os.path.exists(p), f"{p} missing — gate artifacts are tracked"


def test_refuses_when_a_replay_corpus_is_missing(tmp_path, monkeypatch):
    """Identity of the CODE is not presence of the DATA.

    Air had matching HEAD, artifact hash, ballot and compiled binary, and still
    lacked the gitignored corpora — discovered only after launching (Codex G5).
    """
    import json as _json
    d = _json.load(open(DEV))
    name = next(iter(d["sources"]))
    d["sources"][name]["corpus"] = "rl_data/does_not_exist.jsonl"
    p = tmp_path / "art.json"
    p.write_text(_json.dumps(d))
    with pytest.raises(RuntimeError, match="missing replay corpus"):
        PR.preflight(_args(tmp_path, states=str(p),
                           expected_states_sha256=PR.digest(str(p))))


def test_refuses_when_a_replay_corpus_digest_drifted(tmp_path):
    import json as _json
    d = _json.load(open(DEV))
    name = next(iter(d["sources"]))
    d["sources"][name]["corpus_sha256_16"] = "0" * 16
    p = tmp_path / "art2.json"
    p.write_text(_json.dumps(d))
    with pytest.raises(RuntimeError, match="does not match the artifact"):
        PR.preflight(_args(tmp_path, states=str(p),
                           expected_states_sha256=PR.digest(str(p))))
