"""Outer-path witnesses for DEV bury, independent of the running screen."""
import copy
from collections import Counter

import numpy as np
import pytest

from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state
from shengji.train.cwv_bury_policy import CWVBuryConfig, make_cwv_bury_bot


class RecordingEvaluator:
    max_batch = 64

    def __init__(self):
        self.inputs = []

    def score(self, positions, seat, **kwargs):
        # Record actual complete-world inputs at the model boundary. A final
        # action alone could match despite hidden data entering the model.
        for rnd in positions:
            self.inputs.append((seat, tuple(tuple(h) for h in rnd.hands),
                                tuple(rnd.buried), rnd.attacker_points,
                                tuple((p.seat, tuple(p.cards))
                                      for t in rnd.history for p in t.plays)))
        return np.asarray([-float(rnd.attacker_points) for rnd in positions])


class HiddenHand(list):
    def __iter__(self):
        raise AssertionError("bury read a true hidden hand")

    def __getitem__(self, key):
        raise AssertionError("bury read a true hidden hand")


def semantic_record(record):
    return {key: value for key, value in record.items()
            if key not in {"elapsed_seconds", "model_seconds", "rollout_seconds"}}


@pytest.mark.parametrize("arm", ["heuristic", "mc", "hybrid"])
def test_full_bury_path_cannot_read_hidden_cards_and_preserves_play_rng(arm):
    rnd = reopen_state(capture_state(65))
    banker = rnd.banker
    protected = copy.deepcopy(rnd)
    for seat in range(4):
        if seat != banker:
            protected.hands[seat] = HiddenHand(protected.hands[seat])
    with pytest.raises(AssertionError, match="^bury read a true hidden hand$"):
        list(protected.hands[(banker + 1) % 4])
    outputs = []
    evaluators = []
    for root in (rnd, protected):
        evaluator = RecordingEvaluator()
        bot = make_cwv_bury_bot(evaluator, seed=71, arm=arm)
        before = bot.rng.getstate()
        picked = bot.decide_bury(root, banker)
        assert bot.rng.getstate() == before
        assert len(picked) == 8 and not Counter(picked) - Counter(root.hands[banker])
        assert root.phase == "bury" and root.buried == []
        outputs.append((picked, semantic_record(bot.last_bury_record)))
        evaluators.append(evaluator.inputs)
    assert outputs[0] == outputs[1]
    assert evaluators[0] == evaluators[1]
    if arm == "hybrid":
        assert evaluators[0]  # non-vacuous model boundary check


def test_hidden_twin_changes_true_deal_but_not_model_inputs_or_bury():
    rnd = reopen_state(capture_state(66))
    twin = copy.deepcopy(rnd)
    a, b = [seat for seat in range(4) if seat != rnd.banker][:2]
    # Find unlike copies so the hidden world really changes. Declaration pins
    # remain untouched by excluding publicly shown cards from the swap.
    shown = set((rnd.declaration or {}).get("cards", []))
    pair = next((i, j) for i, x in enumerate(twin.hands[a])
                for j, y in enumerate(twin.hands[b])
                if x != y and x not in shown and y not in shown)
    i, j = pair
    twin.hands[a][i], twin.hands[b][j] = twin.hands[b][j], twin.hands[a][i]
    assert Counter(twin.hands[a]) != Counter(rnd.hands[a])
    results = []
    inputs = []
    for root in (rnd, twin):
        evaluator = RecordingEvaluator()
        bot = make_cwv_bury_bot(evaluator, seed=73, arm="hybrid")
        results.append((bot.decide_bury(root, root.banker),
                        semantic_record(bot.last_bury_record)))
        inputs.append(evaluator.inputs)
    assert inputs[0] and inputs[0] == inputs[1]
    assert results[0] == results[1]


def test_explicit_default_config_preserves_real_default_decision_and_inputs():
    rnd = reopen_state(capture_state(67))
    results, inputs = [], []
    for kwargs in ({}, {"bury_config": CWVBuryConfig()}):
        evaluator = RecordingEvaluator()
        bot = make_cwv_bury_bot(evaluator, seed=79, arm="hybrid", **kwargs)
        before = bot.rng.getstate()
        results.append((bot.decide_bury(rnd, rnd.banker),
                        semantic_record(bot.last_bury_record)))
        assert bot.rng.getstate() == before
        inputs.append(evaluator.inputs)
    assert inputs[0] and inputs[0] == inputs[1]
    assert results[0] == results[1]
