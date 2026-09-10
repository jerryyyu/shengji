import numpy as np
import pytest

from shengji.train.r4_w32_mc import nominate, finalize
from shengji.train.world_mixture_mc import mixture_decision, reduce_mixture_arms


def test_uniform_exact_parity_at_actual_final_consumer():
    actions = [["S2"], ["H5"], ["C3"]]
    selection = [[float(i%7)/3, float(i%7)/3, float(i%11)] for i in range(30)]
    report = [[float(i%3)/7, float(i%3)/7, float(i%13)] for i in range(300)]
    raw, challenger, values = nominate(actions, [0, 1, 2], selection)
    expected = {**finalize(0, challenger, report), "raw_winner": raw,
                "challenger": challenger, "selection_means": values, "admitted": [0, 1, 2]}
    assert mixture_decision(actions, [0, 1, 2], selection, report,
                            np.full(30, 1/30), np.full(300, 1/300)) == expected


def test_real_arm_wiring_separates_rank_and_mc_changes():
    actions = [["S2"], ["H3"], ["C4"]]
    selection = [[0, 10, 20]]*30
    report = [[0, -20, 10]]*150 + [[0, 20, 10]]*150
    ranked = {"primary": [0, 2], "control": [0, 1]}
    weights = {"selection": {n: np.full(30, 1/30) for n in ranked},
               "report": {"primary": [0]*150+[1/150]*150,
                          "control": np.full(300, 1/300)}}
    result = reduce_mixture_arms(actions, [0, 1], ranked, selection, report, weights)
    assert result["ordinary"]["played"] == 0
    assert result["primary:rank-only"]["played"] == 2
    assert result["primary:mc-only"]["played"] == 1
    assert result["primary:rank+mc"]["played"] == 2
    assert result["control:rank+mc"] == result["ordinary"]
    assert result["primary:mc-only"]["gap"] == pytest.approx(20)
    assert result["primary:mc-only"]["se"] == pytest.approx(0, abs=1e-12)


def test_selection_weights_reach_nomination_not_just_report():
    actions = [["S2"], ["H3"], ["C4"]]
    selection = [[0, 20, -30]]*15+[[0, -10, 30]]*15
    report = [[0, 10, 20]]*300
    ordinary = mixture_decision(actions, [0, 1, 2], selection, report)
    weighted = mixture_decision(actions, [0, 1, 2], selection, report, [0]*15+[1/15]*15)
    assert ordinary["challenger"] == 1
    assert weighted["challenger"] == 2
    assert ordinary["played"] == 1
    assert weighted["played"] == 2


@pytest.mark.parametrize("weights", [[-.1, 1.1], [0, 0], [float('nan'), 1], [1, 0], [.5]])
def test_invalid_mixtures_refused(weights):
    with pytest.raises(ValueError):
        mixture_decision([["S2"], ["H3"]], [0, 1], [[0, 1]]*2, [[0, 1]]*2, weights)
