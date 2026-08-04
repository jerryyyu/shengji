"""The ballot contract must catch the mismatch that bit us three times."""
from __future__ import annotations

import pytest

from shengji.engine.ballot import (MC_CANDIDATES_V1, MC_CANDIDATES_V3LEAD,
                                   RL_ACTIONS_V1, RL_ACTIONS_V2, BallotMismatch,
                                   BallotSpec, assert_compatible,
                                   spec_for_mcbot)


def test_the_two_generators_are_different_ballots():
    """mc_candidates and rl_actions are NOT interchangeable.

    v10res was trained on one and deployed on the other and looked like a
    failed idea rather than a mismatch.
    """
    assert MC_CANDIDATES_V1.digest != RL_ACTIONS_V1.digest
    with pytest.raises(BallotMismatch, match="Elo-798"):
        assert_compatible(MC_CANDIDATES_V1, RL_ACTIONS_V1)


def test_widening_at_play_time_is_refused():
    """The literal Elo-798 failure: train narrow, play wide."""
    with pytest.raises(BallotMismatch):
        assert_compatible(RL_ACTIONS_V1, RL_ACTIONS_V2)


def test_same_spec_passes():
    assert_compatible(MC_CANDIDATES_V1, MC_CANDIDATES_V1)


def test_a_flag_change_is_a_different_ballot():
    """V3 changes WHICH actions appear, so it must not pass as v1."""
    assert MC_CANDIDATES_V1.digest != MC_CANDIDATES_V3LEAD.digest
    with pytest.raises(BallotMismatch):
        assert_compatible(MC_CANDIDATES_V1, MC_CANDIDATES_V3LEAD)


def test_digest_ignores_prose_but_not_substance():
    a = BallotSpec(name="x", version=1, source="s", note="one wording")
    b = BallotSpec(name="x", version=1, source="s", note="quite another")
    assert a.digest == b.digest, "documentation must not change identity"
    c = BallotSpec(name="x", version=1, source="s", lead_cap=14)
    assert a.digest != c.digest, "a cap change IS a different action set"


def test_live_bot_reports_the_spec_it_enumerates():
    from shengji.ai.mcbot import MCBot

    bot = MCBot(seed=1)
    assert spec_for_mcbot(bot).digest == MC_CANDIDATES_V1.digest
    bot.V3_LEAD_SINGLES = True
    assert spec_for_mcbot(bot).digest == MC_CANDIDATES_V3LEAD.digest


def test_registry_keys_are_stable_identities():
    from shengji.engine.ballot import REGISTRY

    for key, spec in REGISTRY.items():
        assert key == str(spec)
        assert spec.digest in key
