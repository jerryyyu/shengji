import copy

import pytest
import numpy as np

from shengji.engine.cards import RANKS
from shengji.train.cwv_bury_diagnostic import (
    ALLRANK_NAMESPACE, capture_allrank_state, capture_state, reopen_state,
)


def test_natural_capture_reopens_at_actual_banker_bury():
    row = capture_state(0)
    assert capture_state(0) == row
    rnd = reopen_state(row)
    assert rnd.phase == "bury" and rnd.turn == rnd.banker
    assert len(rnd.hands[rnd.banker]) == 33
    assert [len(h) for i, h in enumerate(rnd.hands) if i != rnd.banker] == [25, 25, 25]
    assert rnd.buried == [] and rnd.trump_rank == "2"


def test_allrank_capture_balances_rank_and_banker_and_reopens():
    rows = [capture_allrank_state(i) for i in range(52)]
    assert {(row["setup"]["trump_rank"], row["initial_banker"])
            for row in rows} == {(rank, banker) for rank in RANKS for banker in range(4)}
    for row in rows:
        assert row == capture_allrank_state(row["index"])
        rnd = reopen_state(row)
        assert rnd.banker == row["initial_banker"]
        assert rnd.trump_rank == row["setup"]["trump_rank"]
        assert rnd.phase == "bury"
        assert not rnd.first_round
        assert row["seed"] != capture_state(row["index"])["seed"]


@pytest.mark.parametrize("field,message", [
    ("initial_banker", "all-rank derived banker binding mismatch"),
    ("namespace", "bury state schema/namespace mismatch"),
    ("deck", "bury state deck binding mismatch"),
    ("rank", "all-rank derived rank binding mismatch"),
])
def test_allrank_reopen_refuses_identity_drift(field, message):
    row = copy.deepcopy(capture_allrank_state(17))
    if field == "initial_banker":
        row[field] = (row[field] + 1) % 4
    elif field == "namespace":
        row[field] = ALLRANK_NAMESPACE + "-altered"
    elif field == "rank":
        row["setup"]["trump_rank"] = RANKS[(RANKS.index(row["setup"]["trump_rank"]) + 1) % len(RANKS)]
    else:
        row[field][0], row[field][-1] = row[field][-1], row[field][0]
    with pytest.raises(ValueError, match=f"^{message}$"):
        reopen_state(row)


def test_capture_refuses_changed_visible_hand():
    row = copy.deepcopy(capture_state(0))
    row["banker_hand"].pop()
    with pytest.raises(ValueError, match="^bury banker hand reconstruction mismatch$"):
        reopen_state(row)


def test_capture_refuses_seed_drift():
    row = copy.deepcopy(capture_state(0))
    row["seed"] += 1
    with pytest.raises(ValueError, match="^bury state seed binding mismatch$"):
        reopen_state(row)


def test_capture_refuses_deck_drift():
    row = capture_state(0)
    row["deck"][0], row["deck"][-1] = row["deck"][-1], row["deck"][0]
    with pytest.raises(ValueError, match="^bury state deck binding mismatch$"):
        reopen_state(row)


def test_mc_selection_preserves_points_margin_and_restricted_ballot():
    from shengji.ai.registry import make_bot
    from shengji.train.cwv_bury_diagnostic import pick_mc
    bot = make_bot("mc-s0-report-lcb", seed=0)
    assert pick_mc(np.array([[100, 99, 20], [100, 99, 20]]), bot, [0, 1]) == 0
    assert pick_mc(np.array([[100, 99, 20], [100, 99, 20]]), bot, [0, 1, 2]) == 2
    assert pick_mc(np.array([[100, 94, 94]]), bot, [0, 2, 1]) == 1


def test_hidden_opponent_twins_have_identical_pipeline_inputs():
    from shengji.ai.registry import make_bot
    from shengji.ai.cwv_policy import sample_worlds
    from shengji.train.cwv_bury import bury_candidates, score_bury_candidates
    from shengji.rl.value_afterstate import tensors_from_round
    rnd = reopen_state(capture_state(0))
    twin = copy.deepcopy(rnd)
    opponents = [s for s in range(4) if s != rnd.banker]
    a, b = opponents[:2]
    twin.hands[a], twin.hands[b] = twin.hands[b], twin.hands[a]
    assert twin.hands != rnd.hands

    class Recorder:
        max_batch = 3
        def __init__(self):
            self.rows = []
        def score(self, positions, seat):
            for pos in positions:
                self.rows.append(tensors_from_round(pos, seat))
            return np.arange(len(positions), dtype=float)

    records = []
    for root in (rnd, twin):
        bot = make_bot("mc-s0-report-lcb", seed=987)
        candidates = bury_candidates(root, bot)
        worlds, attempts = sample_worlds(bot, root, root.banker, 2)
        assert len(worlds) == 2
        recorder = Recorder()
        scores = score_bury_candidates(root, candidates[:2], worlds, recorder,
                                       first_trick_policy=bot.rollout_policy)
        records.append((candidates, worlds, attempts, recorder.rows, scores))
    assert records[0][:3] == records[1][:3]
    for x, y in zip(records[0][3], records[1][3]):
        for name in x.__dataclass_fields__:
            np.testing.assert_array_equal(getattr(x, name), getattr(y, name))
    np.testing.assert_array_equal(records[0][4], records[1][4])


def test_immediate_bury_refused_but_exactly_one_trick_is_valid():
    from shengji.ai.registry import make_bot
    from shengji.ai.cwv_policy import sample_worlds
    from shengji.train.cwv_bury import bury_candidates, score_bury_candidates, post_bury_world
    from shengji.rl.value_afterstate import tensors_from_round, ValueAfterstateError
    rnd = reopen_state(capture_state(1))
    bot = make_bot("mc-s0-report-lcb", seed=123)
    candidates = bury_candidates(rnd, bot)
    worlds, _ = sample_worlds(bot, rnd, rnd.banker, 1)
    with pytest.raises(ValueAfterstateError, match="^history tensor length drift$"):
        tensors_from_round(post_bury_world(rnd, worlds[0][0], candidates[0]), rnd.banker)

    class Evaluator:
        max_batch = 2
        def score(self, positions, seat):
            for position in positions:
                assert len(position.history) == 1
                assert len(position.trick.plays) == 0
                assert tensors_from_round(position, seat).history.shape[0] == 4
            return np.zeros(len(positions))
    score_bury_candidates(rnd, candidates[:2], worlds, Evaluator(),
                          first_trick_policy=bot.rollout_policy)
