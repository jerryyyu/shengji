import itertools

import numpy as np
import pytest

from shengji.train.cwv_residual_diagnostic import corrected_estimate, compare_estimators, collect_reference


def test_all_uniform_subsets_are_unbiased_and_full_subset_is_exact():
    r = np.array([[1., 9.], [3., 2.], [8., 1.], [-1., 3.]])
    v = np.array([[7., 2.], [1., 6.], [3., 5.], [2., 8.]])
    estimates = [corrected_estimate(v, r[list(ids)], ids)
                 for ids in itertools.combinations(range(4), 2)]
    np.testing.assert_allclose(np.mean(estimates, axis=0), r.mean(axis=0))
    np.testing.assert_allclose(corrected_estimate(v, r, range(4)), r.mean(axis=0))


def test_good_proxy_helps_bad_proxy_can_hurt():
    r = np.array([[1., 9.], [3., 2.], [8., 1.], [-1., 3.]])
    good = compare_estimators(r, r, subset_worlds=1)
    bad = compare_estimators(-r, r, subset_worlds=1)
    assert good['estimates']['corrected']['pair_gap_squared_error'] == 0
    assert bad['estimates']['corrected']['pair_gap_squared_error'] > bad['estimates']['small_mc']['pair_gap_squared_error']
    assert good == compare_estimators(r, r, subset_worlds=1)


@pytest.mark.parametrize('ids', [[0, 0], [True], [-1], [2], []])
def test_bad_subset_refuses(ids):
    with pytest.raises(ValueError):
        corrected_estimate([[1., 2.], [3., 4.]], [[0., 0.]] * len(ids), ids)


@pytest.mark.parametrize('advance', [False, True])
def test_real_world_sampling_and_point_level_signs(monkeypatch, advance):
    from tests.test_world_shortlist import play_state, round_signature
    from shengji.ai.registry import REGISTRY
    from shengji.rl.value_afterstate import category_signed_level, signed_level_category
    rnd = play_state()
    if advance:
        rnd.play(rnd.turn, [rnd.hands[rnd.turn][0]])
    before = round_signature(rnd)
    points = 120
    monkeypatch.setattr(REGISTRY['mc-s0-report-lcb'], '_rollout', lambda *a, **kw: points)
    class Evaluator:
        def score(self, leaves, seat):
            return np.full(len(leaves), category_signed_level(signed_level_category(points, rnd.is_attacker(seat))))
    from shengji.ai.heuristic import HeuristicBot
    actions = [HeuristicBot().decide_play(rnd, rnd.turn)]
    data = collect_reference(rnd, rnd.turn, actions, Evaluator(), worlds=2)
    np.testing.assert_equal(data['model'], data['rollout'])
    assert data['mc_points_means'] == [points * (1 if rnd.is_attacker(rnd.turn) else -1)]
    assert data['full_rollouts'] == data['model_rows'] == 2
    assert round_signature(rnd) == before


def test_cli_publishes_reusable_matrix_and_resumes_without_rollouts(tmp_path, monkeypatch):
    import json
    from shengji.train import cwv_residual_diagnostic as diagnostic
    from shengji.ai import cwv_policy
    from shengji.ai.registry import REGISTRY
    from shengji.luna.game import _state_snapshot
    from tests.test_world_shortlist import play_state
    rnd = play_state()
    action = [rnd.hands[rnd.turn][0]]
    states = tmp_path / 'states.json'
    states.write_text(json.dumps({'results': [{'snapshot': _state_snapshot(rnd),
                     'seat': rnd.turn, 'incumbent': action, 'submitted': action}]}))
    class Evaluator:
        checkpoint_sha256 = 'a' * 64
        def score(self, leaves, seat):
            return np.zeros(len(leaves))
    monkeypatch.setattr(cwv_policy, 'shared_evaluator', lambda *a, **kw: Evaluator())
    monkeypatch.setattr(REGISTRY['mc-s0-report-lcb'], '_rollout', lambda *a, **kw: 120)
    argv = ['--states', str(states), '--checkpoint', 'fixture.pt', '--out', str(tmp_path / 'out'),
            '--worlds', '2', '--subset-worlds', '1', '--seed', '73']
    assert diagnostic.main(argv) == 0
    output = tmp_path / 'out' / 'state-0000.json'
    raw = output.read_bytes()
    data = json.loads(raw)
    assert data['reference']['full_rollouts'] == 2
    assert data['comparison']['units'] == 'acting-team-signed-level'
    monkeypatch.setattr(diagnostic, 'collect_reference', lambda *a, **kw: pytest.fail('replayed completed state'))
    assert diagnostic.main(argv) == 0
    assert output.read_bytes() == raw
    monkeypatch.setattr(__import__('shengji.train.search_screen', fromlist=['execution_source_identity']),
                        'execution_source_identity', lambda *a: 'changed-source')
    with pytest.raises(ValueError, match='different configuration'):
        diagnostic.main(argv)


def test_unpatched_production_rollout_accepts_sampled_world_shape():
    from tests.test_world_shortlist import play_state
    rnd = play_state()
    class Evaluator:
        def score(self, leaves, seat):
            return np.zeros(len(leaves))
    data = collect_reference(rnd, rnd.turn, [[rnd.hands[rnd.turn][0]]],
                             Evaluator(), worlds=2)
    assert data['full_rollouts'] == 2
    assert np.isfinite(data['rollout']).all()
