"""S18's two opt-in variants (OFF BY DEFAULT; each requires ``exact_lead_endgame``).

``exact_lead_tie_baseline`` (``elt``): the exact pass replaces the finalized
baseline lead only on a STRICTLY higher exact mean.  ``exact_lead_policy_first``
(``elp``): the policy head, encoded on each responder's own view, completes the
first trick before the exact solve (`exact_lead_policy_first`).

Correctness and identity witnesses only, not a strength or latency claim.
"""
import copy
import json
import random
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai.cwv_policy import afterstate, default_finisher, sample_worlds
from shengji.ai.memory import Memory
from shengji.train import exact_lead_policy_first as elp
from shengji.train import pv_exact_endgame as exact
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_prior_admission import root_clone
from shengji.train.leaf_first_trick import best_follow
from shengji.train.policy_prior import CARD_INDEX, flat_input, root_tensors
from test_pv_admission_rules import predict
from test_pv_finish_lead import bot, root
from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA  # noqa: F401
from optional_stage_contract import Deadline

TIE = 'SHENGJI_PV_EXACT_LEAD_TIE_BASELINE'
POLICY = 'SHENGJI_PV_EXACT_LEAD_POLICY_FIRST'
VARIANT_NAMES = {
    (True, False): 'pv-search-491ee4bf-w64-k8-div-rc-tb-ele-elt-la-dtr-vd-r941bee4b-bury-hybrid-bwv-d6be69630533',
    (False, True): 'pv-search-491ee4bf-w64-k8-div-rc-tb-ele-elp-la-dtr-vd-re99a4f09-bury-hybrid-bwv-bcea00ef9a3f',
    (True, True): 'pv-search-491ee4bf-w64-k8-div-rc-tb-ele-elt-elp-la-dtr-vd-rdb8efc40-bury-hybrid-bwv-559bef8bf82f',
}


def variant_bot(**flags):
    return bot(False, exact_lead_endgame=True, **flags)


# ------------------------------------------------------------------ identity

def test_release45_and_s18_names_are_unchanged_and_variants_pinned(pinned_production_package):
    from scripts.qualify_exact_lead import qualification_env, R45_NAMES
    env = qualification_env(pinned_production_package, 45)

    def built(**extra):
        entries = pv.pv_registry_entries(**pv.pv_env_recipe({**env, **extra}))
        name, = entries
        return name, entries[name](seed=3)

    for off in ({}, {TIE: '0', POLICY: '0'}, {TIE: '', POLICY: ''}):
        for ele, expected in (('0', R45_NAMES[0]), ('1', R45_NAMES[1])):
            name, policy = built(SHENGJI_PV_EXACT_LEAD_ENDGAME=ele, **off)
            assert name == expected
            # flag-off instance state is exactly S18's / release 45's
            assert not {'exact_lead_tie_baseline', 'exact_lead_policy_first'} & set(vars(policy))
    for (tie, first), expected in VARIANT_NAMES.items():
        name, policy = built(SHENGJI_PV_EXACT_LEAD_ENDGAME='1', **{TIE: str(int(tie)),
                                                                  POLICY: str(int(first))})
        assert name == expected
        assert policy.exact_lead_tie_baseline is tie and policy.exact_lead_policy_first is first
        with pytest.raises(pv.PVSearchPolicyError, match='require exact_lead_endgame'):
            built(**{TIE: str(int(tie)), POLICY: str(int(first))})


def test_recipe_payload_carries_variants_only_when_on():
    sha = 'f' * 64
    s18 = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha, exact_lead_endgame=True))
    assert not {'exact_lead_tie_baseline', 'exact_lead_policy_first', 'exact_lead_tie_rule',
                'exact_lead_policy_first_limits'} & set(s18)
    tie = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha, exact_lead_endgame=True,
                                              exact_lead_tie_baseline=True))
    assert tie == {**s18, 'exact_lead_tie_baseline': True,
                   'exact_lead_tie_rule': pv.EXACT_LEAD_TIE_RULE}
    first = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha, exact_lead_endgame=True,
                                                exact_lead_policy_first=True))
    assert first == {**s18, 'exact_lead_policy_first': True,
                     'exact_lead_policy_first_limits': elp.LIMITS}
    for key in ('exact_lead_tie_baseline', 'exact_lead_policy_first'):
        config = pv.PVSearchConfig(checkpoint_sha256=sha, **{key: True})
        with pytest.raises(pv.PVSearchPolicyError, match='require exact_lead_endgame'):
            pv.recipe_payload(config)
        with pytest.raises(pv.PVSearchPolicyError, match='require exact_lead_endgame'):
            bot(False, **{key: True})
        with pytest.raises(pv.PVSearchPolicyError, match='must be a bool'):
            variant_bot(**{key: 1})
    env = dict(SHENGJI_PV_CKPT='x.npz', SHENGJI_PV_SHA256=sha)
    with pytest.raises(pv.PVSearchPolicyError, match='must be 0 or 1'):
        pv.pv_env_recipe({**env, TIE: 'yes'})
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index('elt') == tokens.index('ele') + 1 == tokens.index('elp') - 1


# ------------------------------------------------------------- tie to baseline

@pytest.mark.parametrize('tie_rule', [False, True])
@pytest.mark.parametrize('delta,kind', [(0.25, 'higher'), (0.0, 'tie'), (-0.25, 'lower')])
def test_tie_baseline_replaces_only_on_strict_exact_improvement(monkeypatch, tie_rule, delta, kind):
    rnd = root(2)
    policy = variant_bot(exact_lead_tie_baseline=True) if tie_rule else variant_bot()
    actions = [['C3'], ['C4'], ['C5']]
    means = np.array([1.0, 1.0 + delta, 0.0])
    base = (np.array([5.0, 4.0, 3.0]), 1, 0, actions[0], 3)
    policy._tiebreak = {'base': True}
    monkeypatch.setattr(exact, 'exact_lead_means', lambda *a, **kw:
                        (means, dict(worlds_completed=2, nodes=9, cache_hits=0)))

    def select(*a, **kw):
        policy._tiebreak = {'exact': True}   # the exact pass's own selection records
        return 1
    monkeypatch.setattr(policy, '_select', select)
    monkeypatch.setattr(policy, '_swap_doomed_throw', lambda r, s, action, *a: action)
    result = policy._exact_lead_decision(rnd, rnd.turn, actions, [], time.perf_counter(),
                                         None, [0.0] * 3, base)
    state = policy._exact_lead
    assert state['exact_lead_status'] == 'complete'
    assert result[0] is means and result[1] == 1 and result[4] == 3   # exact means published
    kept = tie_rule and delta <= 0
    if kept:
        assert result[2] == 0 and result[3] == ['C3']
        assert policy._tiebreak == {'base': True}       # baseline records restored
        assert state['exact_lead_change_kind'] == 'unchanged'
        assert state['exact_lead_changed'] is False
        assert state['exact_lead_selected_level_delta'] == 0.0
    else:
        assert result[2] == 1 and result[3] == ['C4']
        assert policy._tiebreak == {'exact': True}
        assert state['exact_lead_change_kind'] == kind
    if tie_rule:
        assert state['exact_lead_tie_baseline_kept'] is kept
        assert state['exact_lead_tie_baseline_exact_index'] == (1 if kept else None)
    else:
        assert not any(k.startswith('exact_lead_tie') for k in state)
    assert not any(k.startswith('exact_lead_policy') or k == 'exact_lead_first_trick'
                   for k in state)


def test_exact_means_are_dyadic_so_exact_equality_is_a_tie():
    # every per-world level is a half-integer category; 64 worlds divide exactly
    rng = random.Random(5)
    from shengji.rl.value_afterstate import category_signed_level, OUTCOME_CLASSES
    levels = [category_signed_level(c) for c in range(OUTCOME_CLASSES)]
    for _ in range(200):
        a = [rng.choice(levels) for _ in range(64)]
        b = a[:]
        rng.shuffle(b)
        sa = sb = 0.0
        for x, y in zip(a, b):
            sa += x
            sb += y
        assert sa / 64 == sb / 64


# ---------------------------------------------------------- policy first trick

def _lead_positions(rnd, worlds):
    seat = rnd.turn
    return [afterstate(root_clone(rnd, h, b), seat, h, b, [card])
            for h, b in worlds for card in sorted(set(rnd.hands[seat]))]


def _worlds(rnd, n=4, seed=11):
    policy = bot(False, exact_lead_endgame=True)
    policy.sampler.rng.seed(seed)
    from shengji.ai.cwv_policy import sample_worlds as draw
    worlds, _ = draw(policy.sampler, rnd, rnd.turn, n, mem=Memory(rnd, rnd.turn))
    return worlds


def test_view_rows_equal_full_root_encodings_byte_for_byte():
    rnd = root(5)
    checked = 0
    for position in _lead_positions(rnd, _worlds(rnd)):
        while elp._open_trick(position):
            seat = position.turn
            views, _ = sample_worlds(elp.MCBot(seed=1), position, seat, 6,
                                     mem=Memory(position, seat))
            rows = elp.view_rows(position, seat, views, 2)
            full = [flat_input(root_tensors(root_clone(position, h, b), seat, 2), 2)
                    for h, b in views]
            assert len(rows) == len(full) == 6
            for got, want in zip(rows, full):
                assert got.dtype == want.dtype and got.tobytes() == want.tobytes()
            checked += len(rows)
            position.play(seat, default_finisher().decide_play(position, seat))
    assert checked > 50


def test_responder_view_never_depends_on_hidden_hands():
    """Two positions with the responder's identical information state but
    different hidden hands give byte-identical policy rows (same seed)."""
    rnd = root(5)
    compared = 0
    for position in _lead_positions(rnd, _worlds(rnd)):
        seat = position.turn
        # a different deal of everything the responder cannot see
        other, _ = sample_worlds(elp.MCBot(seed=99), position, seat, 1,
                                 mem=Memory(position, seat))
        hands, buried = other[0]
        twin = root_clone(position, hands, buried)
        if twin.hands == position.hands:
            continue
        assert elp.information_key(twin, seat) == elp.information_key(position, seat)
        a = elp.ExactLeadPolicyFirst(predict, 2, seed='s')._view(position, seat)
        b = elp.ExactLeadPolicyFirst(predict, 2, seed='s')._view(twin, seat)
        assert [r.tobytes() for r in a] == [r.tobytes() for r in b]
        compared += 1
    assert compared >= 4


class CountingPredict:
    def __init__(self, fail=False):
        self.calls, self.rows, self.fail = 0, 0, fail

    def __call__(self, X):
        self.calls += 1
        self.rows += len(X)
        if self.fail:
            raise RuntimeError('predictor down')
        return predict(X)


def test_complete_plays_policy_argmax_forced_and_shared_choices():
    rnd = root(5)
    worlds = _worlds(rnd, n=3)
    # every world twice: each responder information state occurs at least twice
    positions = _lead_positions(rnd, worlds + copy.deepcopy(worlds))
    reference = copy.deepcopy(positions)
    counting = CountingPredict()
    player = elp.ExactLeadPolicyFirst(counting, 2, seed='t')
    player.complete(positions)
    assert counting.calls == player.batches <= 3 and player.fallbacks == 0
    assert player.policy_plays + player.forced == 3 * len(positions)
    assert player.forced > 0 and player.policy_plays > 0
    # one view per information state, shared by every position holding it
    assert 2 * player.views <= player.policy_plays and player.view_worlds_drawn == 8 * player.views
    # replay: the test predictor's log-odds are the same for every row, so the
    # policy choice is best_follow on them; forced follows are the one action
    log_odds = predict(np.zeros((1, 1)))[0]
    for done, position in zip(positions, reference):
        while elp._open_trick(position):
            seat = position.turn
            forced = elp.ExactLeadPolicyFirst._forced(position, seat)
            action = forced or best_follow(position.hands[seat], position.trick.plays[0].cards,
                                           position.ordering, log_odds, CARD_INDEX)
            position.play(seat, action)
        assert [(p.seat, list(p.cards)) for p in done.history[-1].plays] == \
            [(p.seat, list(p.cards)) for p in position.history[-1].plays]
        assert len(done.history) == len(rnd.history) + 1


def test_policy_failure_falls_back_to_the_heuristic_per_responder():
    rnd = root(5)
    positions = _lead_positions(rnd, _worlds(rnd))
    reference = copy.deepcopy(positions)
    player = elp.ExactLeadPolicyFirst(CountingPredict(fail=True), 2, seed='t')
    player.complete(positions)
    assert player.policy_plays == 0 and player.batches == 0
    assert player.fallbacks + player.forced == 3 * len(positions) and player.fallbacks > 0
    from shengji.ai.cwv_policy import finish_current_trick
    for done, position in zip(positions, reference):
        finish_current_trick(position)   # the S18 heuristic leaf
        assert [(p.seat, list(p.cards)) for p in done.history[-1].plays] == \
            [(p.seat, list(p.cards)) for p in position.history[-1].plays]


def test_policy_first_decision_completes_and_leaves_the_served_stream():
    rnd = root(2)
    seat = rnd.turn
    s18 = variant_bot()
    first = variant_bot(exact_lead_policy_first=True)
    s18_cards = s18.decide_play(copy.deepcopy(rnd), seat)
    cards = first.decide_play(copy.deepcopy(rnd), seat)
    a, b = s18.last_decision_record, first.last_decision_record
    assert a['work_complete'] and b['work_complete']
    assert a['exact_lead_status'] == b['exact_lead_status'] == 'complete'
    assert a['admitted'] == b['admitted'] and a['exact_lead_base_value_means'] == \
        b['exact_lead_base_value_means']
    assert s18.sampler.rng.getstate() == first.sampler.rng.getstate()
    assert b['exact_lead_first_trick'] == 'policy'
    n = len(b['admitted']) * b['worlds'] * 3
    assert b['exact_lead_policy_plays'] + b['exact_lead_policy_forced'] \
        + b['exact_lead_policy_fallbacks'] == n
    assert b['exact_lead_policy_fallbacks'] == 0
    assert not any(k.startswith('exact_lead_policy') or k.startswith('exact_lead_tie')
                   or k == 'exact_lead_first_trick' for k in a)
    assert sorted(cards) in [sorted(x) for x in b['admitted']]
    assert sorted(s18_cards) in [sorted(x) for x in a['admitted']]
    again = variant_bot(exact_lead_policy_first=True)
    assert again.decide_play(copy.deepcopy(rnd), seat) == cards
    assert again.last_decision_record['value_means'] == b['value_means']


def test_expiry_inside_policy_completion_keeps_the_baseline(monkeypatch):
    rnd = root(2)
    policy = variant_bot(exact_lead_policy_first=True)
    base = (np.array([-100.0]), 1, 0, [rnd.hands[rnd.turn][0]], 1)
    deadline = Deadline()
    view = elp.ExactLeadPolicyFirst._view

    def expire(self, position, seat):
        deadline.force = True          # the next guard (before the predictor) expires
        return view(self, position, seat)
    monkeypatch.setattr(elp.ExactLeadPolicyFirst, '_view', expire)
    monkeypatch.setattr(elp.ExactLeadPolicyFirst, '_forced', staticmethod(lambda p, s: None))
    predicted = CountingPredict()
    policy.predict = predicted
    policy._tiebreak = {'base': True}
    result = policy._exact_lead_decision(
        rnd, rnd.turn, [base[3]], [(copy.deepcopy(rnd.hands), list(rnd.buried))],
        time.perf_counter(), deadline, [0.0], base)
    assert result is base and predicted.calls == 0
    assert policy._tiebreak == {'base': True}
    state = policy._exact_lead
    assert state['exact_lead_status'] == 'abandoned'
    assert state['exact_lead_abandon_reason'] == 'hard_budget'


# ------------------------------------------------- production package, captured root

def test_variants_on_captured_joker_root(pinned_production_package, monkeypatch):
    """#700 captured root (4-card lead); frozen module clock as in
    test_exact_corrects_captured_joker_lead_through_api."""
    from scripts.qualify_exact_lead import qualification_env
    from shengji.train.lead_root_capture import restore_with_ledger
    monkeypatch.setattr(pv, 'time', SimpleNamespace(perf_counter=lambda: 0.0))
    packet = json.loads((Path(__file__).parent / 'fixtures/r44_joker_lead.json').read_text())
    env = {**qualification_env(pinned_production_package, 45),
           'SHENGJI_PV_EXACT_LEAD_ENDGAME': '1'}
    records = {}
    for arm, extra in {'s18': {}, 'elt': {TIE: '1'}, 'elp': {POLICY: '1'},
                       'both': {TIE: '1', POLICY: '1'}}.items():
        entries = pv.pv_registry_entries(**pv.pv_env_recipe({**env, **extra}))
        name, = entries
        rnd, ledger = restore_with_ledger(packet)
        policy = entries[name](seed=941210121)
        policy._refusals = ledger
        cards = policy.decide_play(rnd, 3)
        record = policy.last_decision_record
        assert record['work_complete'] and record['exact_lead_status'] == 'complete'
        assert record['exact_lead_worlds_completed'] == 64
        assert sorted(cards) in [sorted(a) for a in record['admitted']]
        records[arm] = (cards, record, policy.sampler.rng.getstate())
    s18, elt_, first, both = (records[k] for k in ('s18', 'elt', 'elp', 'both'))
    assert s18[0] == ['BJ'] and elt_[0] == ['BJ']   # a strict improvement: elt agrees
    assert elt_[1]['exact_lead_tie_baseline_kept'] is False
    for other in (elt_, first, both):
        assert other[1]['admitted'] == s18[1]['admitted']
        assert other[1]['exact_lead_base_value_means'] == s18[1]['exact_lead_base_value_means']
        assert other[2] == s18[2]
    assert elt_[1]['value_means'] == s18[1]['value_means']
    assert both[1]['value_means'] == first[1]['value_means']
    assert first[1]['exact_lead_policy_fallbacks'] == 0
    assert first[1]['exact_lead_policy_plays'] > 0
