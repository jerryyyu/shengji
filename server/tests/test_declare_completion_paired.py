import json
import random

import pytest

from shengji.engine.round import Round
from shengji.train import declare_completion_paired as paired
from shengji.train.declare_completion import DeclareObservation, baseline_action


def test_one_actual_intervention_and_baseline_equivalence():
    found = 0
    for index in range(27):
        rank, banker, team = paired.context(index)
        seed = paired.derived_seed('paired-fresh-deal', index)
        calls = []
        def choose(obs):
            assert type(obs) is DeclareObservation
            assert obs.seat % 2 == team and len(obs.own_hand) >= 20
            assert obs.options
            calls.append(obs)
            return baseline_action(obs)
        a, b = Round(rank, banker, random.Random(seed)), Round(rank, banker, random.Random(seed))
        exposure = paired.complete_actual_deal(a, focal_team=team, choose=choose)
        paired.complete_actual_deal(b, focal_team=team)
        assert len(calls) <= 1
        assert a.phase == b.phase == 'bury'
        assert a.hands == b.hands and a.deck == b.deck
        assert a.declaration == b.declaration and a.trump_suit == b.trump_suit
        if exposure:
            assert not exposure['changed']
            found += 1
    assert found == 4  # Fixed score-free population; do not filter unexposed deals.


def test_all_ranks_and_banker_contexts_are_prespecified():
    cells = [paired.context(i) for i in range(27)]
    assert len({r for r, _, _ in cells}) == 13
    assert {b for _, b, _ in cells} == {None, 0, 1, 2, 3}
    assert [t for _, _, t in cells].count(0) == 14
    assert [t for _, _, t in cells].count(1) == 13


def test_actual_pair_selects_before_evaluation_and_has_independent_rng(tmp_path, monkeypatch):
    config = {'start_index': 0, 'config_sha256': 'test', 'output': str(tmp_path)}
    calls, selections = [], []
    def evaluator(rnd, *, focal_team, seed):
        assert rnd.phase == 'bury'
        calls.append((seed, list(rnd.deck)))
        return {'focal_signed_levels': 1, 'focal_won': 1, 'kitty_bonus': 0, 'kitty_ge80': 0}
    monkeypatch.setattr(paired, 'FullW32Evaluator', lambda config: evaluator)
    def choose(obs, config, index, evaluator):
        # At this point no actual outcome from this pair exists.
        assert not calls
        selections.append(obs)
        return baseline_action(obs)
    monkeypatch.setattr(paired, 'select_declaration', choose)
    exposed = 0
    for index in range(8):
        calls.clear()
        row = paired.run_pair(config, index)
        assert len(calls) == 2 and calls[0] == calls[1]
        assert row['evaluation_seed'] != row['deal_seed']
        assert row['evaluation_seed'] not in {
            paired.derived_seed(f'paired-inner:{index}', w) for w in range(2)}
        exposed += int(row['exposure'] is not None)
    assert exposed > 0


def test_selector_reuses_completed_selection_and_refuses_changed_observation(tmp_path, monkeypatch):
    from shengji.train.declare_completion_screen import capture_first_opportunity
    obs = capture_first_opportunity(2)
    config = {'output': str(tmp_path), 'config_sha256': 'test'}
    calls = []
    def evaluate(observation, *, seeds, evaluator):
        calls.append(seeds)
        return {'selected_action': list(observation.options[0]), 'actions': []}
    monkeypatch.setattr(paired, 'evaluate_actions', evaluate)
    first = paired.select_declaration(obs, config, 42, None)
    assert paired.select_declaration(obs, config, 42, None) == first
    assert len(calls) == 1 and len(set(calls[0])) == 2
    path = tmp_path/'selection-00042.json'
    saved = json.loads(path.read_text())
    saved['identity']['observation']['seat'] = 3
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='selection input differs'):
        paired.select_declaration(obs, config, 42, None)


def test_summary_keeps_unexposed_deals_and_counts_deals_not_worlds():
    metric = lambda value: {'focal_signed_levels': value, 'focal_won': int(value > 0),
                            'kitty_bonus': 0, 'kitty_ge80': 0}
    rows = [{'cluster': i, 'wall_s': 5, 'exposure': None if i == 0 else {'changed': True},
             'arms': {'sampled': metric(1 if i == 0 else -1), 'baseline': metric(1)}} for i in range(2)]
    summary = paired.summarize(rows, {'deals': 27})
    assert summary['completed_deals'] == 2 and not summary['complete']
    assert summary['exposed_deals'] == summary['changed_deals'] == 1
    assert summary['paired_deltas']['focal_signed_levels']['mean'] == -1


def test_paired_cli_resume_reuses_completed_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv('SHENGJI_REQUIRE_VOIDS', '1')
    monkeypatch.setattr(paired, 'execution_source_identity', lambda *args: {'source': 'test'})
    monkeypatch.setattr(paired, 'FullW32Evaluator', lambda config: lambda rnd, **kw:
        {'focal_signed_levels': 1, 'focal_won': 1, 'kitty_bonus': 0, 'kitty_ge80': 0})
    monkeypatch.setattr(paired, 'select_declaration', lambda obs, *args: baseline_action(obs))
    checkpoint = tmp_path/'model.bin'
    checkpoint.write_bytes(b'test')
    calls = []
    def execute(config, pending, shards, *, output, **kwargs):
        calls.append(list(pending))
        for cluster in pending:
            row = paired.run_pair(config, cluster)
            paired._publish(output/f'cluster-{cluster:05d}.json', row)
            shards.append(row)
    monkeypatch.setattr(paired, '_run_pending', execute)
    args = ['--checkpoint', str(checkpoint), '--out', str(tmp_path/'out'), '--deals', '2']
    paired.main(args)
    paired.main(args)
    assert calls == [[0, 1], []]
    row_path = tmp_path/'out'/'cluster-00000.json'
    row = json.loads(row_path.read_text())
    row['evaluation_seed'] += 1
    row_path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='paired deal identity differs'):
        paired.main(args)
