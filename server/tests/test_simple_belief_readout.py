import copy

import pytest

from shengji.train.simple_belief_gameplay import schedule
from shengji.train.simple_belief_readout import distribution, gameplay_readout


def test_weighting_contrast_and_cost_reach_report_with_both_team_signs():
    rows = []
    for arm, team in schedule():
        # Small wins both team mirrors; all other arms give team0 +1.
        score = -1 if arm == 'new-small' and team == 1 else 1
        rows.append({'arm': arm, 'focal_team': team, 'wall_s': 10.,
                     'work': {'parent_cpu_seconds': 8., 'child_inference_wall_seconds': 2., 'total_rollouts': 100},
                     'outcome': {'team0_signed_levels': score,
                                 'transcript': [{'seat': team or 0, 'decision_wall_s': 2., 'last_belief': None}]}})
    result = gameplay_readout([{'records': rows}])
    comparison = result['learned_weighting_contrasts']['new-small vs uniform-pool']
    assert comparison['signed_levels']['mean'] == 1.
    assert comparison['wins']['mean'] == .5
    assert comparison['signed_levels']['n_independent_states'] == 1
    assert result['cost_and_diversity']['new-small']['summed_parent_cpu_seconds'] == 16
    assert result['cost_and_diversity']['new-small']['focal_decision_seconds']['mean'] == 2
    changed = copy.deepcopy(rows)
    changed[4]['outcome']['team0_signed_levels'] = 3
    assert gameplay_readout([{'records': changed}])['learned_weighting_contrasts'][
        'new-small vs uniform-pool']['signed_levels']['mean'] == -1


def test_distribution_rejects_nonfinite_and_does_not_fake_empty_samples():
    assert distribution([])['mean'] is None
    assert distribution([1, 2, 3])['mean'] == 2
    with pytest.raises(ValueError, match='nonfinite measured cost'):
        distribution([float('nan')])
