import copy

import pytest
import numpy as np

from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state


def test_natural_capture_reopens_at_actual_banker_bury():
    row = capture_state(0)
    assert capture_state(0) == row
    rnd = reopen_state(row)
    assert rnd.phase == "bury" and rnd.turn == rnd.banker
    assert len(rnd.hands[rnd.banker]) == 33
    assert [len(h) for i, h in enumerate(rnd.hands) if i != rnd.banker] == [25, 25, 25]
    assert rnd.buried == [] and rnd.trump_rank == "2"


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
