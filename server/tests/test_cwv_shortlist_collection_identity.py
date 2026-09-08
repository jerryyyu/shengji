"""Two ways a generation run could record something untrue about itself.

Both found by Codex on PR299 (bus 767). Each is about GENERATED DATA, not about
whether the bot works: a run that mislabels its own teacher or its own reference
ballot produces a corpus nobody can later trust or reproduce.
"""
import json
from pathlib import Path

import pytest

from shengji.ai import cwv_policy
from shengji.ai.registry import REGISTRY, make_bot, register_cwv_shortlist_policies
from shengji.harvest import trajectory
from shengji.train.cwv_shortlist import (CWVShortlistBot, ShortlistPolicyError,
                                         resolved_recipe, shortlist_policy_name)
from tests.test_cwv_shortlist_registry import _load_script


def _dev_checkpoint(path: Path, width: int) -> str:
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(path), rounds=2, architecture="mlp", width=width, max_epochs=2, quiet=True)
    return str(path)


# ---------------------------------------------- 1: the checkpoint FILE may move

def test_replacing_the_checkpoint_file_under_a_registered_name_is_refused(tmp_path):
    """The name embeds the ckpt8 hashed AT REGISTRATION.

    The model is loaded lazily on the first ``make_bot``. If the file at that
    path is replaced in between, the old name would serve the new weights and a
    resume would continue a run with a different teacher, silently.
    """
    path = tmp_path / "teacher.pt"
    _dev_checkpoint(path, width=16)
    names = register_cwv_shortlist_policies(str(path), [32])
    try:
        _dev_checkpoint(path, width=24)          # same path, different weights
        with pytest.raises(ShortlistPolicyError) as excinfo:
            make_bot(names[0], seed=11)
        assert "checkpoint" in str(excinfo.value).lower()
    finally:
        for name in names:
            REGISTRY.pop(name, None)


def test_an_unchanged_checkpoint_file_still_builds(tmp_path):
    """The guard must not fire on the ordinary path."""
    path = tmp_path / "teacher.pt"
    _dev_checkpoint(path, width=16)
    names = register_cwv_shortlist_policies(str(path), [32])
    try:
        assert type(make_bot(names[0], seed=11)) is CWVShortlistBot
    finally:
        for name in names:
            REGISTRY.pop(name, None)


# ------------------------------- 2: --knob must not silently retarget the probe

def test_a_knob_run_still_probes_production_for_the_production_ballot(monkeypatch):
    """``production_ballot`` must be PRODUCTION's ballot, under --knob too.

    The probe branch for overrides builds an unmodified instance of the SAME
    policy, which is right for a production policy but wrong for one whose own
    candidate generator is not production's: the shortlist would stamp its own
    W32 ballot as ``production_ballot`` and every ballot-gap analysis reading
    that field would be comparing the shortlist against itself.
    """
    built = []

    class FakeShortlist(trajectory.MCBot):
        PRODUCTION_BALLOT_POLICY = "mc-s0-report-lcb"
        SOME_KNOB = 1

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)

    def fake_make_bot(name, **kw):
        built.append(name)
        return FakeShortlist(seed=kw.get("seed"))

    monkeypatch.setattr(trajectory, "make_bot", fake_make_bot)
    config = {"policy": "mc-shortlist-deadbeef-w32-r00000000",
              "knobs": {"SOME_KNOB": 2}, "explore_rate": 0.0, "explore_k": 0,
              "cap": 256, "widen": (), "work": {"select_worlds": None,
                                                "report_worlds": None}}
    import random
    trajectory.make_trajectory_bot(config, seed=11, explore_rng=random.Random(0))
    assert built[1] == "mc-s0-report-lcb", (
        f"under --knob the probe was built from {built[1]!r}; the declared "
        "PRODUCTION_BALLOT_POLICY must win, or the shortlist stamps its own "
        "ballot as production_ballot")
