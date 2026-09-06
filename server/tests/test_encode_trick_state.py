"""The v2 observation must state who is winning, and state it correctly.

`Round` resolves a trick's winner only when the trick completes, and keeps a
running incumbent solely inside a trusted rollout. `trick_state` recomputes
it on the ordinary path, so the check that matters is agreement with the
engine's own resolution rather than with a reimplementation of it.
"""
import pytest

from shengji.harvest import trajectory
from shengji.rl.encode import ENC_VERSION, OBS_DIM, encode_obs, trick_state

SEED0 = 5_100_000
WORK = {"select_worlds": 2, "report_worlds": 30}


@pytest.fixture(scope="module")
def rounds(tmp_path_factory):
    """Real played rounds, so the states are ones the engine actually reaches."""
    out = tmp_path_factory.mktemp("enc-traj") / "run"
    trajectory.generate(rounds=4, seed0=SEED0, out_dir=out, workers=1, merge=False,
                        allow_seed_overlap=True, explore_rate=0.0, explore_k=2, **WORK)
    import json
    from shengji.harvest.rebuild import state_for_record
    recs = []
    for path in sorted((out / "shards").glob("*.jsonl")):
        recs += [json.loads(line) for line in path.read_text().splitlines()]
    plays = [r for r in recs if r.get("decision_kind") == "play"]
    assert plays, "the fixture must produce play decisions"
    return [(r, state_for_record(r)) for r in plays]


def test_version_and_width_moved_together(rounds):
    assert ENC_VERSION == 2
    for _rec, rnd in rounds[:20]:
        assert len(encode_obs(rnd, rnd.turn)) == OBS_DIM


def test_winner_agrees_with_the_engine_on_completed_tricks(rounds):
    """Replay each trick to completion and compare with Round's own winner."""
    checked = 0
    for _rec, rnd in rounds:
        for trick in rnd.history:
            if len(trick.plays) < 2 or trick.winner is None:
                continue

            class _Partial:
                pass
            stub = _Partial()
            stub.trick = trick
            stub.ordering = rnd.ordering
            stub.hands = rnd.hands
            got, lead_suit, points = trick_state(stub, trick.plays[0].seat)
            assert got == trick.winner, (got, trick.winner)
            assert lead_suit is not None
            assert points == trick.points
            checked += 1
    assert checked >= 5, f"only {checked} completed tricks compared"


def test_leading_seat_has_no_winner_and_no_lead_suit(rounds):
    seen = 0
    for _rec, rnd in rounds:
        if rnd.trick is not None and not rnd.trick.plays:
            winner, lead_suit, points = trick_state(rnd, rnd.turn)
            assert (winner, lead_suit, points) == (None, None, 0)
            seen += 1
    if not seen:
        pytest.skip("no lead decision in this fixture")


def test_the_winner_check_can_fail(rounds, monkeypatch):
    """Mutation test: break the comparison and the agreement assertion must fire.

    Asserting that a shifted seat differs from the true one would prove
    nothing, so this disables the actual `beats` call instead. With it
    always losing, `trick_state` can only ever return the leader, and any
    trick a later seat won must now mismatch.
    """
    from shengji.rl import encode as enc

    monkeypatch.setattr(enc, "beats", lambda *a, **k: (False, 0))
    caught = 0
    for _rec, rnd in rounds:
        for trick in rnd.history:
            if len(trick.plays) < 2 or trick.winner is None:
                continue
            if trick.winner == trick.plays[0].seat:
                continue          # the leader won anyway; the break is invisible here

            class _Partial:
                pass
            stub = _Partial()
            stub.trick, stub.ordering, stub.hands = trick, rnd.ordering, rnd.hands
            got, _suit, _pts = enc.trick_state(stub, trick.plays[0].seat)
            assert got != trick.winner, "the broken version still agreed"
            caught += 1
    assert caught >= 1, "no trick was won by a follower, so the mutation was untestable"
