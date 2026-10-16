import copy
import json

import numpy as np
import pytest

from shengji.train.horizon_generalization import held_out_horizon


def capture(shallow, deep):
    actions = [["C2"], ["C3"]]
    return dict(replay=dict(decision=dict(admitted=actions)), paired_horizon=dict(
        status="complete", actions=actions, worlds=len(shallow),
        arms=dict(trick=dict(values=shallow), policy=dict(values=deep))))


def test_selected_winner_optimism_can_reverse_on_held_out_worlds():
    row = capture([[1, 0]] * 4, [[0, 10], [0, -9], [0, 10], [0, -9]])
    deep = np.asarray(row["paired_horizon"]["arms"]["policy"]["values"])
    assert deep.mean(axis=0)[1] > deep.mean(axis=0)[0]
    result = held_out_horizon(json.loads(json.dumps(row)))
    assert result["held_out_gap_mean"] == -4.5
    assert [f["held_out_gap_mean"] for f in result["folds"]] == [-9, 0]


def test_persistent_signal_and_unequal_fold_sizes():
    row = capture([[1, 0]] * 5, [[0, 2], [0, 4], [0, 2], [0, 4], [0, 2]])
    before = copy.deepcopy(row)
    result = held_out_horizon(row)
    assert result["held_out_gap_mean"] == pytest.approx(2.8)
    assert [f["evaluation_worlds"] for f in result["folds"]] == [2, 3]
    assert row == before
    assert json.loads(json.dumps(result)) == result


def test_ties_keep_first_ballot_action():
    result = held_out_horizon(capture([[1, 1]] * 4, [[2, 2]] * 4))
    assert result["held_out_gap_mean"] == 0
    assert all(f["trick_index"] == f["policy_index"] == 0 for f in result["folds"])


def test_evaluation_rows_do_not_select_their_own_moves():
    row = capture([[1, 0]] * 4, [[0, 2]] * 4)
    before = held_out_horizon(row)["folds"][0]
    row["decision"] = row.pop("replay")["decision"]
    for name in ("trick", "policy"):
        row["paired_horizon"]["arms"][name]["values"] = copy.deepcopy(
            row["paired_horizon"]["arms"][name]["values"])
    row["paired_horizon"]["arms"]["trick"]["values"][1] = [0, 100]
    row["paired_horizon"]["arms"]["policy"]["values"][1] = [100, 0]
    after = held_out_horizon(row)["folds"][0]
    assert (after["trick_index"], after["policy_index"]) == (
        before["trick_index"], before["policy_index"])
    assert after["held_out_gap_mean"] != before["held_out_gap_mean"]


@pytest.mark.parametrize("mutation", [
    lambda r: r["paired_horizon"].update(status="abandoned"),
    lambda r: r["paired_horizon"].update(worlds=3),
    lambda r: r["paired_horizon"].update(worlds=True),
    lambda r: r["replay"]["decision"].update(admitted=[["C4"]]),
    lambda r: r["paired_horizon"]["arms"]["policy"].update(values=[[0, 1]]),
    lambda r: r["paired_horizon"]["arms"]["policy"].update(values=[[0, float("nan")]] * 4),
])
def test_incomplete_or_mismatched_captures_refuse(mutation):
    row = capture([[1, 0]] * 4, [[0, 2]] * 4)
    mutation(row)
    with pytest.raises(ValueError):
        held_out_horizon(row)
