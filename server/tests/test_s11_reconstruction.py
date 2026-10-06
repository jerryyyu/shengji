import copy

import pytest
from shengji.eval import s11_reconstruction as reconstruction

from shengji.engine.round import actual_play_after
from shengji.eval.s11_reconstruction import (
    S11ReconstructionError,
    reconstruct_s11_trajectory,
)
from shengji.harvest.legal import enumerate_legal
from shengji.harvest.rebuild import deck_from_seed, round_from_setup


def _trajectory(first_action=None):
    deck = deck_from_seed("2", 0, 17)
    setup = {"trump_rank": "2", "banker": 0, "declarations": [],
             "trump_suit": "C", "trump_is_nt": False, "buried": deck[-8:]}
    rnd = round_from_setup(deck, setup)
    rows, prefix = [], []
    for ply in range(100):
        seat = rnd.turn
        action = first_action if ply == 0 and first_action is not None else \
            enumerate_legal(rnd, seat, cap=1).actions[0]
        previous_last = rnd.last_trick
        rnd.play(seat, action)
        committed = actual_play_after(rnd, seat, previous_last)
        rows.append({"ply": ply, "deck": list(deck), "round_seed": 17,
                     "setup": copy.deepcopy(setup), "source_ref": f"run:0:0:{seat}:{ply}",
                     "decision_kind": "play", "seat": seat,
                     "action": list(action), "engine_play": committed,
                     "plays_prefix": copy.deepcopy(prefix)})
        prefix.append({"seat": seat, "cards": committed})
    return rows


def test_failed_throw_uses_committed_cards_and_preserves_submitted_action():
    rows = _trajectory(["S10", "S4"])
    assert rows[0]["action"] != rows[0]["engine_play"]
    selected = next(i for i, row in enumerate(rows[1:], 1) if row["seat"] == 0)
    result = reconstruct_s11_trajectory(rows, selected, actor_seat=0)
    assert result["root"].phase == "play"
    assert result["root"].history or result["root"].trick


def test_actor_turn_observation_cadence_is_bounded_to_selected_root():
    rows = _trajectory(["S10", "S4"])
    selected = next(i for i, row in enumerate(rows[1:], 1) if row["seat"] == 0)
    seen = []
    original = reconstruction.RefusalLedger.observe
    def observe(self, rnd):
        seen.append(rnd.turn)
        return original(self, rnd)
    reconstruction.RefusalLedger.observe = observe
    try:
        result = reconstruct_s11_trajectory(rows, selected, actor_seat=0)
    finally:
        reconstruction.RefusalLedger.observe = original
    assert result["actor_seat"] == 0
    assert result["history_primed"] is True
    assert result["live_rng_state_reconstructed"] is False
    assert seen == [row["seat"] for row in rows[:selected + 1] if row["seat"] == 0]
    assert len(result["ledger"].refusals) == 1


def test_selected_root_matches_independent_prefix_replay():
    rows = _trajectory(["S10", "S4"])
    selected = next(i for i, row in enumerate(rows[1:], 1) if row["seat"] == 0)
    result = reconstruct_s11_trajectory(rows, selected, actor_seat=0)
    independent = round_from_setup(rows[0]["deck"], rows[0]["setup"])
    for play in rows[selected]["plays_prefix"]:
        independent.play(play["seat"], play["cards"])
    root = result["root"]
    assert (root.phase, root.turn, root.hands,
            root.attacker_points, root.history, root.trick) == (
                independent.phase, independent.turn, independent.hands,
                independent.attacker_points,
                independent.history, independent.trick)


@pytest.mark.parametrize("change", [
    lambda r: r[1].update(engine_play=["S2"]),
    lambda r: r[1].update(decision_kind="bury"),
    lambda r: r[1].update(source_ref="not-canonical"),
    lambda r: r[1].update(deck=list(reversed(r[1]["deck"]))),
    lambda r: r[1].update(source_ref="run:1:0:1:1"),
    lambda r: r[1].update(ply=3),
    lambda r: r[1].update(ply=True),
    lambda r: r[1].update(ply=0),
    lambda r: r.__setitem__(1, None),
    lambda r: r.pop(),
])
def test_malformed_commit_identity_plies_or_terminal_truncation_refuse(change):
    rows = _trajectory()
    change(rows)
    with pytest.raises(S11ReconstructionError):
        reconstruct_s11_trajectory(rows, 0)


def test_prefix_must_be_exact_and_contiguous():
    rows = _trajectory()
    rows[3]["plays_prefix"] = copy.deepcopy(rows[2]["plays_prefix"])
    with pytest.raises(S11ReconstructionError, match="plays_prefix"):
        reconstruct_s11_trajectory(rows, 0)


def test_seed_and_deck_must_not_disagree():
    rows = _trajectory()
    rows[0]["round_seed"] = 18
    with pytest.raises(S11ReconstructionError, match="deck and round_seed"):
        reconstruct_s11_trajectory(rows, 0)


def test_selected_mapping_and_invalid_mirror_refuse():
    rows = _trajectory()
    rows[1] = None
    with pytest.raises(S11ReconstructionError, match="selected row"):
        reconstruct_s11_trajectory(rows, 1)
    rows = _trajectory()
    for row in rows:
        row["source_ref"] = row["source_ref"].replace(":0:0:", ":0:2:")
    with pytest.raises(S11ReconstructionError, match="mirror"):
        reconstruct_s11_trajectory(rows, 0)


def test_input_unchanged_and_unrelated_labels_ignored():
    rows = _trajectory(["S10", "S4"])
    for row in rows:
        row["outcome"] = {"do_not_use": True}
        row["action_values"] = ["not model data"]
    before = copy.deepcopy(rows)
    result = reconstruct_s11_trajectory(rows, 1)
    assert rows == before
    assert result["actor_seat"] == rows[1]["seat"]
    assert not result["provenance_verified"]


def test_normal_play_without_engine_play_is_accepted():
    rows = _trajectory()
    for row in rows:
        if row["action"] == row["engine_play"]:
            del row["engine_play"]
    assert reconstruct_s11_trajectory(rows, 99)["root"].phase == "play"
