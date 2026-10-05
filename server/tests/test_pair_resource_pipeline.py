"""Synthetic qualification of capture -> baseline -> repair -> saved values.

No real model, file reader, sampled world generation or value search. Unlike
manually assembled capture dictionaries this exercises the actual producer.
"""
import copy

import numpy as np
import pytest

from shengji.eval.fixed_tape_policy import capture_policy_ranks
from shengji.eval.pair_resource_admission import project_rank_repair
from shengji.harvest.legal import enumerate_legal
from shengji.train.pv_search_policy import PVSearchBot
from test_pv_admission_rules import _pair_preservation_follow, harness


@pytest.mark.parametrize('seed', range(4))
@pytest.mark.parametrize('k', [1, 8, 16])
def test_producer_to_consumer_on_complete_legal_pool(seed, k):
    root = _pair_preservation_follow()
    actions = list(enumerate_legal(root, 1, cap=4000).actions)
    worlds = [(copy.deepcopy(root.hands), list(root.buried)) for _ in range(2)]
    before = copy.deepcopy((root.hands, actions, worlds))
    bot = object.__new__(PVSearchBot)
    bot.version = 2
    logits = np.random.default_rng(seed).normal(size=(2, 54))
    calls = []
    bot.predict = lambda x: calls.append(x.copy()) or logits.copy()
    def forbidden(*args, **kwargs):
        raise AssertionError('no sampler, admission or value-search invocation')
    bot._worlds = bot._admit = bot._value_means = bot._leaf = forbidden
    capture = capture_policy_ranks(bot, root, 1, actions, worlds)
    anchor = [tuple(sorted(a)) for a in actions].index(('C2', 'D8', 'S6'))
    indices = harness(admission_diversity=True)._admit_diverse(
        root, actions, capture['ranked_indices'], anchor, k=k)
    baseline = [actions[i] for i in indices]
    # Distinct synthetic value labels, intentionally NOT policy preferences.
    values = np.random.default_rng(seed + 100).normal(size=len(actions)).tolist()
    result = project_rank_repair(root, 1, capture, baseline, actions, values)
    reordered = project_rank_repair(root, 1, capture, baseline,
                                   list(reversed(actions)), list(reversed(values)))
    assert result == reordered
    lookup = {tuple(sorted(a)): v for a, v in zip(actions, values)}
    for name in ('baseline', 'repaired'):
        ballot = result[name]['actions']
        assert len(ballot) == k
        assert ballot[0] == actions[anchor]
        best = max(lookup[tuple(sorted(a))] for a in ballot)
        assert result[name]['raw_value_max'] == best
        assert result[name]['gap_to_full_pool'] == max(values) - best
    assert len(calls) == 1
    assert (root.hands, actions, worlds) == before
    assert not result['provenance_verified']
    assert not result['serving_choice_assessed']
    assert not result['strategic_quality_assessed']
    if k == 1:
        assert result['swap'] is None
    if k == 8 and seed == 0:
        assert result['swap'] is not None
