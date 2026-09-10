import random
import hashlib
import json
from types import SimpleNamespace

import pytest

from shengji.engine.round import Round
from shengji.train.r4_w32_mc import BASE, finalize, moments, nominate, reduce, collect
from shengji.train.r4_w32_proper_scores import brier, debiased_reference_brier


@pytest.mark.parametrize("report_gap", [-4.0, 20.0])
def test_matrix_finalizer_matches_actual_mc_decide_play(report_gap):
    rnd = Round("2", 0, random.Random(4))
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(0, rnd.hands[0][:8])
    actions = [[c] for c in sorted(set(rnd.hands[0]))[:3]]
    selection = [[0, 10+(i%3), -20] for i in range(30)]
    report = [[0, report_gap+(-3 if i%2 else 3), -20] for i in range(300)]

    class Replay(BASE):
        N_DETERMINIZATIONS = 30
        TRACTOR_LOCK = False
        def __init__(self):
            super().__init__(seed=0)
            self.used = 0
        def _candidates(self, rnd, seat):
            return actions
        def _sample_hands(self, rnd, seat, mem):
            self.used += 1
            return ({"row": self.used-1}, [])
        def _new_exact_world_session(self, *args):
            return None
        def _rollout(self, rnd, seat, sampled, buried, candidate, **kwargs):
            row = sampled["row"]
            matrix = selection if row < 30 else report
            value = matrix[row if row < 30 else row-30][actions.index(candidate)]
            return value if rnd.is_attacker(seat) else -value
        def _score(self, value):
            return value

    bot = Replay()
    played = bot.decide_play(rnd, 0)
    raw, challenger, _ = nominate(actions, [0, 1, 2], selection)
    result = finalize(0, challenger, report)
    assert played == actions[result["played"]]
    assert result["reason"] == bot.last_decision_record["reason"]
    assert result["statistic"] == bot.last_decision_record["report_fold"]["statistic"]
    assert bot.used == 330
    assert raw == bot.last_decision_record["raw_winner_index"]
    assert result["played"] == (0 if report_gap < 0 else 1)


def test_weighted_moments_pairing_and_uniform_reduction():
    values = [float(i%7) for i in range(100)]
    assert moments(values, [10000000]*100) == pytest.approx(moments(values), abs=1e-12)
    weights = [1000000]*50 + [19000000]*50
    expected = moments(values, weights)
    assert moments(list(reversed(values)), list(reversed(weights))) == pytest.approx(expected)
    assert moments(list(reversed(values)), weights) != pytest.approx(expected)


def test_mc_weighting_can_change_nomination_with_same_actions():
    actions = [["S2"], ["H2"]]
    values = [[0, -20], [0, 10]]
    assert nominate(actions, [0, 1], values)[0] == 0
    assert nominate(actions, [0, 1], values, [100000000, 900000000])[0] == 1


def test_weighted_report_can_change_final_decision():
    matrix = [[0, -20]]*50 + [[0, 20]]*50
    assert finalize(0, 1, matrix)["played"] == 0
    assert finalize(0, 1, matrix, [1000000]*50+[19000000]*50)["played"] == 1


def test_reference_brier_correction_removes_finite_sample_bias():
    samples = [[2, 0, 0], [1, 1, 0], [1, 1, 0], [0, 2, 0]]
    raw = sum(brier([c/2 for c in row], 0) for row in samples)/4
    corrected = sum(debiased_reference_brier(row, 0) for row in samples)/4
    assert raw == .75
    assert corrected == brier([.5, .5, 0], 0) == .5
    assert brier([0, 1, 0], 1) == 0


@pytest.mark.parametrize("corruption", ["rank", "weights", "worlds", "multiplier", "missing",
                                        "stale-final", "all-energy1"])
def test_real_mc_reducer_refuses_same_actor_cross_capture_mix(tmp_path, corruption):
    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    root = tmp_path / "position"
    root.mkdir()
    capture_path = root/"private-world-values.json"
    put(capture_path, {"actor_sha256": "a"*64})
    pred = root/"r4-marginals.json"
    put(pred, {"actor_sha256": "a"*64})
    names = ("synthetic-primary", "hard-geometry-label-permutation")
    rank = {"actor_sha256": "a"*64, "baseline_shortlist": [0, 1],
            "arms": {n: {"shortlist": [0, 1]} for n in names},
            "capture_file_sha256": digest(capture_path), "predictions_file_sha256": digest(pred)}
    rank_path = root/"rank-comparison-typed-v2.json"
    put(rank_path, rank)
    for fold, n in (("selection", 30), ("report", 300)):
        data = {"actor_sha256": "a"*64, "union_indices": [0, 1], "fold": fold,
                "actions": [["S2"], ["H2"]], "worlds": ["world"]*n,
                "values_world_major": [[0, 20]]*n}
        path = root/"mc"/fold/"private-world-values.json"
        put(path, data)
        weights = [10**9//n]*n
        for i in range(10**9-sum(weights)):
            weights[i] += 1
        put(root/"mc"/fold/"weights-v2.json", {"actor_sha256": "a"*64,
            "capture_file_sha256": digest(path), "predictions_file_sha256": digest(pred),
            "arms": {name: {"world_weights_ppb": weights} for name in names}})
    args = SimpleNamespace(capture_root=root, out=root/"mc")
    reduce(args)
    assert (root/"mc"/"final-decisions-v2.json").exists()
    # Reopening valid completed output uses the actual reducer and preserves it.
    assert reduce(args, emit=False)["energy_multiplier"] == 1
    if corruption == "rank":
        rank["capture_file_sha256"] = "b"*64
        put(rank_path, rank)
        with pytest.raises(ValueError, match="^weight/rank source capture bytes differ$"):
            collect(args)
    elif corruption == "weights":
        path = root/"mc"/"report"/"weights-v2.json"
        weights = json.loads(path.read_text())
        weights["capture_file_sha256"] = "b"*64
        put(path, weights)
    elif corruption == "worlds":
        path = root/"mc"/"report"/"private-world-values.json"
        data = json.loads(path.read_text())
        data["worlds"][0] = "different world, same actor and population"
        put(path, data)
    elif corruption == "multiplier":
        path = root/"mc"/"report"/"weights-v2.json"
        weights = json.loads(path.read_text())
        weights["energy_multiplier"] = 4
        put(path, weights)
    elif corruption == "missing":
        rank["arms"][names[0]]["shortlist"] = [0, 2]
        put(rank_path, rank)
    elif corruption == "all-energy1":
        args.expected_energy_multiplier = 4
    else:
        path = root/"mc"/"final-decisions-v2.json"
        saved = json.loads(path.read_text())
        saved["decisions"]["ordinary"]["played"] = 0
        put(path, saved)
    message = {"multiplier": "ranking and MC energy multipliers differ",
               "missing": r"missing admitted actions in retained MC tensor: \[2\]",
               "all-energy1": "ranking energy multiplier differs from requested experiment",
               "stale-final": "completed MC reduction differs from current inputs"}.get(
                   corruption, "weight/rank source capture bytes differ")
    with pytest.raises(ValueError, match="^"+message+"$"):
        reduce(args)


def test_extension_preserves_columns_and_only_scores_missing_actions():
    from shengji.train.r4_w32_extend import extend_matrix
    matrix = [[1.5, -2], [3, 4]]
    calls = []
    def score(world, action):
        calls.append((world, action))
        return world*10+action
    indices, result = extend_matrix([4, 1], matrix, [1, 4, 9, 2], score)
    assert indices == [4, 1, 2, 9]
    assert result == [[1.5, -2, 2, 9], [3, 4, 12, 19]]
    assert calls == [(0, 2), (0, 9), (1, 2), (1, 9)]
    assert matrix == [[1.5, -2], [3, 4]]
    calls.clear()
    assert extend_matrix(indices, result, indices, score) == (indices, result)
    assert calls == []


def test_energy4_saved_selection_shift_crosses_real_point_shy_band():
    # The only changed play in the 26-position DEV panel: a score shift admits
    # S5 to the two-point tie band, rather than making S5 the score argmax.
    actions = [["C2"], ["H10"], ["HK"], ["S5"], ["C9"]]
    ordinary = [-89.83333333333333, -85.16666666666667, -85.83333333333333,
                -87.83333333333333, -90.33333333333333]
    weighted = [-91.159779255, -86.464691695, -87.076459555, -87.88248433, -91.648600955]
    assert max(range(5), key=lambda i: ordinary[i]) == 1
    assert max(range(5), key=lambda i: weighted[i]) == 1
    assert BASE(seed=0)._pick_index(actions, ordinary, range(1, 5)) == 1
    assert BASE(seed=0)._pick_index(actions, weighted, range(1, 5)) == 3
