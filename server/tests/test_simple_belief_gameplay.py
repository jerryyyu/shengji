import copy

import pytest

from shengji.train import simple_belief_gameplay as gameplay


def test_schedule_has_one_common_baseline_and_three_mirrored_treatments():
    schedule = gameplay.schedule()
    assert len(schedule) == 7
    assert schedule[0] == ("ordinary", None)
    assert schedule[1:] == [
        ("uniform-pool", 0), ("uniform-pool", 1),
        ("new-small", 0), ("new-small", 1),
        ("r4-synthetic-primary", 0), ("r4-synthetic-primary", 1),
    ]
    assert len(set(schedule)) == 7


def test_run_cluster_preserves_shared_policy_seeds_and_reuses_sealed_arms(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from shengji.train.cwv_bury_policy import CWVBuryConfig
    checkpoint = tmp_path / 'small.pt'
    checkpoint.write_bytes(b'fixture')
    config = {'output': str(tmp_path), 'config_sha256': 'cfg', 'checkpoint': '/unused',
              'checkpoint_sha256': 'value', 'small_checkpoint': str(checkpoint),
              'small_checkpoint_sha256': hashlib.sha256(b'fixture').hexdigest(),
              'cache_recipe_sha256': 'recipe', 'archive_server': '/unused', 'training_root': '/unused'}
    evaluator = SimpleNamespace(checkpoint_sha256='value', identity=lambda: {})
    monkeypatch.setattr(gameplay, 'shared_evaluator', lambda *a, **k: evaluator)
    monkeypatch.setattr(gameplay, 'SmallBeliefPredictor', lambda *a: object())
    monkeypatch.setattr(gameplay, 'R4RuntimeClient', lambda *a: SimpleNamespace(identity={}, close=lambda: None))
    monkeypatch.setattr(gameplay, '_make_bot', lambda mode, evaluator, seed, *a:
                        SimpleNamespace(seed=seed, mode=mode, bury_config=CWVBuryConfig()))
    captured = []
    def play(rnd, bots, cluster, arm, team):
        captured.append((arm, team, [b.seed for b in bots], [b.mode for b in bots]))
        return {**_row(arm, team, 1)['outcome'], 'child_inference_wall_s': 0.}
    monkeypatch.setattr(gameplay, 'play_round', play)
    monkeypatch.setattr(gameplay, '_work_counters', lambda *a: {})
    result = gameplay.run_cluster(config, 0)
    assert len(captured) == 7
    for arm, team, seeds, modes in captured:
        assert seeds == [gameplay.seed_for('play:0', s) for s in range(4)]
        assert modes == [arm if team == s % 2 else 'ordinary' for s in range(4)]
    monkeypatch.setattr(gameplay, 'shared_evaluator', lambda *a, **k: pytest.fail('completed arms rerun'))
    assert gameplay.run_cluster(config, 0) == result


def test_preparation_is_legal_and_rank_and_seed_bound():
    first, _ = gameplay.prepare_round(gameplay.spec_for(0))
    different_rank, _ = gameplay.prepare_round(gameplay.spec_for(1))
    extra, _ = gameplay.prepare_round(gameplay.spec_for(13))
    assert first.phase == different_rank.phase == extra.phase == "bury"
    assert first.trump_rank != different_rank.trump_rank
    assert first.banker == 0
    assert extra.banker in range(4)  # no fixed banker; declaration decides it
    assert len(first.deck) == 108
    assert sorted(map(len, first.hands)) == [25, 25, 25, 33]

    again, _ = gameplay.prepare_round(gameplay.spec_for(0))
    assert first.deck == again.deck
    assert first.declaration == again.declaration
    assert first.hands == again.hands


def _row(arm, team, score):
    return {
        "schema": "simple-belief-gameplay-arm-v1",
        "config_sha256": "cfg",
        "spec": gameplay.spec_for(0),
        "arm": arm,
        "focal_team": team,
        "outcome": {
            "team0_signed_levels": score,
            "banker": 0,
            "attacker_points": 40,
            "kitty_bonus": 0,
            "buried": ["S2"] * 8,
            "transcript": [],
        },
    }


def test_summary_aggregates_mirror_differences_by_deal():
    baseline = _row("ordinary", None, 1)
    records = [baseline]
    for arm in gameplay.ARMS:
        records.extend([_row(arm, 0, 2), _row(arm, 1, -2)])
    summary = gameplay.summarize([{"records": records}])
    assert summary["independent_deals"] == 1
    for arm in gameplay.ARMS:
        assert summary["comparisons"][arm]["signed_levels"]["mean"] == 2
        assert summary["comparisons"][arm]["wins"]["mean"] == 0.5


def test_resume_validation_accepts_exact_arm_and_refuses_drift(tmp_path):
    config = {"config_sha256": "cfg"}
    row = _row("ordinary", None, 1)
    path = tmp_path / "arm.json"
    path.write_text(__import__("json").dumps(row))
    assert gameplay.read_arm(path, config, gameplay.spec_for(0), "ordinary", None) == row
    changed = copy.deepcopy(row)
    changed["arm"] = "new-small"
    path.write_text(__import__("json").dumps(changed))
    with pytest.raises(ValueError, match="identity"):
        gameplay.read_arm(path, config, gameplay.spec_for(0), "ordinary", None)
