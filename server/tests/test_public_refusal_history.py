import copy
from pathlib import Path

import pytest

from shengji.eval import tactical
from shengji.eval.public_refusal_history import public_root_with_ledger


@pytest.fixture(scope="module")
def fixtures():
    return tactical.load_fixtures(Path(__file__).parent / "tactical/public_observations.jsonl")


@pytest.mark.parametrize("fixture_id,fresh,primed", [
    ("pvr8-c1-m0-p23-pair-preservation", 0, 1),
    ("pvr8-c2-m0-p62-joker-control", 0, 10),
    ("pvr8-c3-m0-p47-ace-control", 1, 5),
    ("pvr8-c2-m0-p43-partner-overtake-control", 1, 6),
])
@pytest.mark.parametrize("fill_seed", [0, 1])
def test_explicit_modes_preserve_root_and_reproduce_actor_ledger_census(
        fixtures, fixture_id, fresh, primed, fill_seed):
    fixture = next(fx for fx in fixtures if fx.id == fixture_id)
    before = copy.deepcopy(fixture.to_json())
    root, ledger, receipt = public_root_with_ledger(fixture, mode="fresh-root", fill_seed=fill_seed)
    primed_root, primed_ledger, primed_receipt = public_root_with_ledger(
        fixture, mode="history-primed", fill_seed=fill_seed)
    assert len(receipt["retained_refusals"]) == fresh
    assert len(primed_receipt["retained_refusals"]) == primed
    assert len(ledger.observe(root)) == fresh
    # The returned root's exact deck key must not reset the reconstructed ledger.
    assert len(primed_ledger.observe(primed_root)) == primed
    assert primed_ledger.key == tuple(primed_root.deck)
    assert root.hands == primed_root.hands and root.history == primed_root.history
    assert root.trick == primed_root.trick and root.notice == primed_root.notice
    assert fixture.to_json() == before
    assert receipt["actor_turn_observations"] == 1
    assert primed_receipt["actor_turn_observations"] > 1
    assert primed_receipt["hidden_hands_are_placeholders"]
    assert not primed_receipt["live_rng_state_reconstructed"]
    assert not primed_receipt["provenance_verified"]


@pytest.mark.parametrize("mode", [None, "auto", "", True])
def test_no_implicit_mode(fixtures, mode):
    with pytest.raises(ValueError):
        public_root_with_ledger(fixtures[0], mode=mode)


def test_mode_cannot_be_omitted(fixtures):
    with pytest.raises(TypeError):
        public_root_with_ledger(fixtures[0])


def test_replay_drift_refused(fixtures, monkeypatch):
    original = tactical.round_from_setup
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        root = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            root.attacker_points += 1
        return root
    monkeypatch.setattr(tactical, "round_from_setup", changed)
    with pytest.raises(ValueError, match="differs"):
        public_root_with_ledger(fixtures[0], mode="history-primed")
