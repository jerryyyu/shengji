from types import SimpleNamespace

import pytest

from shengji.train import cwv_release27_search as R
from shengji.train import cwv_prior_admission as P


@pytest.mark.parametrize("mode", ["puct", "truncated", "policy"])
def test_release27_bury_and_baseline_do_not_follow_arm_model(monkeypatch, mode):
    fixed = SimpleNamespace(checkpoint_sha256=R.M1_SHA)
    arm = SimpleNamespace(checkpoint_sha256="g1")
    monkeypatch.setattr(R, "shared_evaluator",
                        lambda path, **kw: fixed if path == "m1.npz" else arm)
    monkeypatch.setattr(P, "load_prior_checked", lambda *a: ("separate", None, None))
    kwargs = dict(seed=19, baseline_checkpoint="m1.npz", prior_checkpoint="prior.npz",
                  arm_checkpoint="g1.pt", arm_sha256="g1", mode=mode)
    control = R.make_release27_side(side="baseline", **kwargs)
    candidate = R.make_release27_side(side="arm", **kwargs)
    assert control.evaluator is fixed
    assert candidate.evaluator is arm
    assert candidate.bury_evaluator is fixed
    for bot in (control, candidate):
        assert bot.bury_arm == "hybrid"
        assert bot.serving_budget_seconds == 2.0
        assert bot.prior_config.threshold == 1000
        assert bot.prior_config.top == 256
        assert bot.REPORT_FOLD_WORLDS == 300


def test_policy_matched_control_changes_only_guidance(monkeypatch):
    fixed = SimpleNamespace(checkpoint_sha256=R.M1_SHA)
    arm = SimpleNamespace(checkpoint_sha256='g1')
    monkeypatch.setattr(R, 'shared_evaluator',
                        lambda path, **kw: fixed if path == 'm1.npz' else arm)
    monkeypatch.setattr(P, 'load_prior_checked', lambda *a: ('separate', None, None))
    kwargs = dict(seed=19, baseline_checkpoint='m1.npz', prior_checkpoint='prior.npz',
        arm_checkpoint='g1.pt', arm_sha256='g1', mode='policy', control='matched-continuation',
        guided_tricks=1, continuation_tricks=None)
    baseline = R.make_release27_side(side='baseline', **kwargs)
    candidate = R.make_release27_side(side='arm', **kwargs)
    assert type(candidate) is type(baseline) is R.PolicyFixedBuryBot
    assert baseline.guided_tricks == 0 and candidate.guided_tricks == 1
    for bot in (baseline, candidate):
        assert bot.evaluator is arm and bot.bury_evaluator is fixed
        assert bot.continuation_tricks is None
    assert baseline.shortlist_config == candidate.shortlist_config
    assert baseline.prior_config == candidate.prior_config
    assert baseline.rng.getstate() == candidate.rng.getstate()


def test_release27_refuses_different_control_asset(monkeypatch):
    monkeypatch.setattr(R, "shared_evaluator",
                        lambda *a, **kw: SimpleNamespace(checkpoint_sha256="other"))
    with pytest.raises(ValueError, match="frozen M1"):
        R.make_release27_side(side="baseline", seed=1, baseline_checkpoint="other",
            prior_checkpoint="prior", arm_checkpoint="g1", arm_sha256="g1", mode="puct")


def test_screen_dispatch_requires_deadline_and_binds_recipe(monkeypatch):
    from shengji.train import cwv_shortlist_screen as S
    from test_cwv_shortlist_screen import cfg
    config = cfg('learned', release27_search={'mode': 'puct'})
    with pytest.raises(ValueError, match='300s'):
        S.make_side(config, 'arm', 19)
    config['decision_deadline'] = dict(S.DEADLINE_RECIPE)
    monkeypatch.setattr(R, 'make_release27_side', lambda **kw: kw)
    assert S.make_side(config, 'arm', 19) == dict(side='arm', seed=19, mode='puct')
    assert S._recipe(config)['release27_search'] == {'mode': 'puct'}
    config['throw_components'] = True
    with pytest.raises(ValueError, match='cannot mix'):
        S.make_side(config, 'arm', 19)


def test_cli_binds_both_assets_and_retains_completed_pairs(monkeypatch, tmp_path):
    from scripts import cwv_release27_screen as C
    monkeypatch.setattr(C, 'file_sha256', lambda path:
        R.M1_SHA if str(path) == 'm1' else R.PRIOR_SHA if str(path) == 'prior' else 'armsha')
    monkeypatch.setattr(C, 'make_release27_side', lambda **kw: None)
    monkeypatch.setattr(C, 'execution_source_identity', lambda *a: {'test': 'source'})
    seen = []
    def pending(config, indexes, shards, **kw):
        seen.append((config, indexes))
    monkeypatch.setattr(C, '_run_pending', pending)
    argv = ['--baseline-checkpoint', 'm1', '--prior-checkpoint', 'prior',
            '--arm-checkpoint', 'arm', '--mode', 'puct', '--seed0', '19',
            '--clusters', '2', '--out', str(tmp_path)]
    assert C.main(argv) == 0
    assert seen[0][1] == [0, 1]
    assert seen[0][0]['baseline_asset_sha256'] == R.M1_SHA
    assert seen[0][0]['release27_search']['arm_sha256'] == 'armsha'
    # A completed pair is loaded, never re-enqueued.
    (tmp_path / 'cluster-00000.json').write_text('{}')
    monkeypatch.setattr(C.screen, 'reopen_shard', lambda *a: {'cluster': 0})
    monkeypatch.setattr(C.screen, 'summary_for', lambda *a: {'complete': False})
    assert C.main(argv) == 0
    assert seen[1][1] == [1]


def test_summary_reports_bury_fallbacks_and_missing_accounting(monkeypatch):
    from shengji.train import cwv_shortlist_screen as S
    from test_cwv_shortlist_screen import cfg, identity_summary
    monkeypatch.setattr(S.duel, 'summarize', identity_summary)
    config = cfg('learned', release27_search={'mode': 'puct'})
    shard = {'records': [], 'bury_records': [
        {'side': 'arm', 'record': {'schema': 'cwv-bury-fallback-v1', 'reason': 'budget'}},
        {'side': 'baseline', 'record': {'schema': 'cwv-bury-v1'}}]}
    result = S.summary_for([shard], config)
    assert result['bury_accounting_complete']
    assert result['bury_outcomes']['arm']['budget_fallbacks'] == 1
    assert result['bury_outcomes']['baseline']['completed'] == 1
    shard['bury_records'].pop()
    assert not S.summary_for([shard], config)['bury_accounting_complete']
