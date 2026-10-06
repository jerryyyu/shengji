"""Synthetic producer-shaped inputs through the actual S11 adapters."""
import copy
import random

import pytest

from shengji.eval.fixed_tape_policy import release38_admission
from shengji.eval.pair_resource_admission import project_rank_repair
from shengji.eval.s11_report import project_s11, summarize_s11
from test_fixed_tape_policy import _admission_fixture


@pytest.mark.parametrize('kind', ['lead', 'follow'])
def test_join_computes_both_repairs_from_same_canonical_baseline(kind):
    _, root, _, capture = _admission_fixture(kind)
    actions = capture['actions']
    values = [float(i % 7 - 3) for i in range(len(actions))]
    before = copy.deepcopy((root.hands, root.history, capture, values, random.getstate()))
    baseline = release38_admission(root, root.turn, capture)
    expected = [project_rank_repair(root, root.turn, capture, baseline['baseline_actions'],
                                   actions, values, signature_overlap_veto=veto)
                for veto in (True, False)]
    result = project_s11(kind, root, root.turn, capture, actions, values)
    assert result['baseline'] == baseline
    assert result['control'] == expected[0]
    assert result['treatment'] == expected[1]
    reordered = project_s11(kind, root, root.turn, capture,
                            list(reversed(actions)), list(reversed(values)))
    assert reordered == result
    changed_values = project_s11(kind, root, root.turn, capture, actions,
                                  [-value for value in values])
    for arm in ('control', 'treatment'):
        assert changed_values[arm]['repaired']['actions'] == result[arm]['repaired']['actions']
    assert (root.hands, root.history, capture, values, random.getstate()) == before
    # Real helper output must satisfy summary validation, not just hand-built fixtures.
    summary = summarize_s11([result], [kind])
    assert summary['valid_count'] == 1
    assert summary['primary']['mean'] == (
        expected[1]['repaired']['raw_value_max']
        - expected[0]['repaired']['raw_value_max'])
    assert summary['primary']['interval95'] is None
    assert summary['missing_count'] == 0


def test_join_budget_failure_returns_no_partial_report():
    _, root, _, capture = _admission_fixture('follow')
    def expired():
        raise RuntimeError('expired')
    with pytest.raises(RuntimeError, match='expired'):
        project_s11('root', root, root.turn, capture, capture['actions'],
                    [0.] * len(capture['actions']), check_budget=expired)


def test_join_mismatched_value_pool_refuses_instead_of_returning_partial():
    _, root, _, capture = _admission_fixture('follow')
    with pytest.raises(ValueError):
        project_s11('root', root, root.turn, capture, capture['actions'][:-1],
                    [0.] * (len(capture['actions']) - 1))


def test_budget_expiry_after_last_projection_still_refuses(monkeypatch):
    from shengji.eval import s11_report
    calls = []
    monkeypatch.setattr(s11_report, 'release38_admission',
                        lambda *args, **kwargs: {'baseline_actions': []})
    def repair(*args, signature_overlap_veto):
        calls.append(signature_overlap_veto)
        return {}
    monkeypatch.setattr(s11_report, 'project_rank_repair', repair)
    def expired_after_treatment():
        if calls == [True, False]:
            raise RuntimeError('expired after treatment')
    with pytest.raises(RuntimeError, match='expired after treatment'):
        project_s11('root', None, 0, {}, [], [],
                    check_budget=expired_after_treatment)
    assert calls == [True, False]
