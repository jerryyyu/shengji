"""Post-decision coverage attachment; fake policies, no inference."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from shengji.eval import tactical as T


def setup(monkeypatch, bad=None):
    fixtures = T.load_fixtures(Path(__file__).parent / 'tactical/public_observations.jsonl')
    calls = []
    def run(bot, fx, *, fill_seed):
        calls.append((bot, fx.id, fill_seed))
        admitted = copy.deepcopy(fx.observed['admitted'])
        if bot == 'treatment' and fx is fixtures[0]:
            admitted.append(fx.observed['alternative'])
        record = {'work_complete': True, 'admitted': admitted}
        if bad == 'missing':
            record.pop('admitted')
        elif bad == 'incomplete':
            record['work_complete'] = False
        return T.Result(fx, list(fx.observed['action']), None, 'synthetic',
                        record=record, seconds=0.125, extra={'observation': {'test': True}})
    monkeypatch.setattr(T, 'run_fixture', run)
    return fixtures, calls


def test_each_arm_uses_own_ballot_without_changing_decisions_or_timing(monkeypatch):
    fixtures, calls = setup(monkeypatch)
    rows = T.run_observation_comparison(lambda seed: 'control', lambda seed: 'treatment', fixtures)
    assert len(rows) == 12 and len(calls) == 24
    for row in rows:
        for arm in ('control', 'treatment'):
            result = row[arm]
            assert result.action == result.fixture.observed['action']
            assert result.seconds == 0.125 and result.passed is None
            assert result.extra['observation'] == {'test': True}
            assert not result.extra['ballot_opportunity']['strategic_quality_assessed']
        if row['fixture'] == fixtures[0].id:
            control = row['control'].extra['ballot_opportunity']['cards']['S6']
            treatment = row['treatment'].extra['ballot_opportunity']['cards']['S6']
            assert control['ballot_spent'] == [2]
            assert treatment['ballot_spent'] == [0, 2]
            assert control['legal_spent'] == treatment['legal_spent'] == [0, 1, 2]


@pytest.mark.parametrize('bad', ['missing', 'incomplete'])
def test_unobserved_telemetry_is_not_reported_as_zero_coverage(monkeypatch, bad):
    fixtures, _ = setup(monkeypatch, bad)
    with pytest.raises(T.TacticalError, match='telemetry'):
        T.run_observation_comparison(lambda _: 'control', lambda _: 'treatment', fixtures, seeds=(0,))


def test_incomplete_legal_pool_refuses(monkeypatch):
    from shengji.harvest import legal
    fixtures, _ = setup(monkeypatch)
    monkeypatch.setattr(legal, 'enumerate_legal', lambda *a, **k: SimpleNamespace(actions=[], complete=False))
    with pytest.raises(ValueError, match='complete legal'):
        T.run_observation_comparison(lambda _: 'control', lambda _: 'treatment', fixtures, seeds=(0,))
