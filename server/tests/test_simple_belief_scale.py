import json
import numpy as np
import pytest

from shengji.train import simple_belief_scale as scale
from shengji.train.simple_belief_data import deal_split, canonical, digest
from test_simple_belief_data import record


def test_nested_training_preserves_fixed_holdouts_and_excludes_value_holdouts():
    keys = [f'deck:{i}' for i in range(100)]
    trains = [k for k in keys if deal_split(k) == 'train']
    old = {'deals': [{'deal_key': trains[0], 'split': 'train'},
                     {'deal_key': trains[1], 'split': 'check'},
                     {'deal_key': trains[2], 'split': 'dev'}]}
    fit = set(keys)-{trains[3]}
    small = scale.choose_keys(dict.fromkeys(keys), fit, old, {trains[4]}, 8)
    large = scale.choose_keys(dict.fromkeys(keys), fit, old, {trains[4]}, 16)
    assert small == large[:8] and len(set(large)) == 16
    assert trains[0] in small
    assert not set(large) & set(trains[1:5])
    assert all(deal_split(k) == 'train' for k in large)


def test_streaming_worker_uses_real_labels_reuses_and_refuses_changed_bytes(tmp_path):
    r = record()
    key = scale.record_deal_key(r)
    source = tmp_path/'source'
    source.mkdir()
    raw = canonical(r)+b'\n'
    (source/'rows.jsonl').write_bytes(raw)
    shard = {'path': 'rows.jsonl', 'bytes': len(raw), 'records': 1, 'sha256': digest(raw)}
    output = tmp_path/'out'
    output.mkdir()
    task = (key, [(str(source), shard)], str(output), 'code')
    desc = scale.encode_extra(task)
    path = output/desc['path']
    with np.load(path) as saved:
        assert saved['x'].shape == (1, 776)
        assert np.take_along_axis(saved['allowed'], saved['targets'][..., None], -1).all()
    stamp = path.stat().st_mtime_ns
    assert scale.encode_extra(task) == desc
    assert path.stat().st_mtime_ns == stamp
    other = tmp_path/'other'
    other.mkdir()
    (source/'rows.jsonl').write_bytes(raw+b' ')
    with pytest.raises(ValueError, match='^source shard byte binding differs$'):
        scale.encode_extra((key, task[1], str(other), 'code'))


def test_write_once_never_replaces_different_plan(tmp_path):
    path = tmp_path/'plan.json'
    scale.write_once(path, {'sizes': [8, 32]})
    with pytest.raises(ValueError, match='existing scaling artifact differs'):
        scale.write_once(path, {'sizes': [16]})
    assert json.loads(path.read_bytes()) == {'sizes': [8, 32]}


def test_rescore_changes_model_only_and_refuses_state_mismatch():
    from shengji.train.simple_belief_scale_assess import replace_predictions
    targets = np.zeros((1, 4, 54), dtype=int)
    masks = np.ones((1, 4, 54, 3), dtype=bool)
    p = np.zeros((1, 4, 54, 3))
    p[..., 0] = 1
    row = {'state_key': 'one', 'targets': targets[0].tolist(),
           'uncertain': np.ones((4, 54), dtype=bool).tolist(),
           'reference_probabilities': (np.ones((4, 54, 3))/3).tolist(),
           'reference_corrected_brier': 0.5, 'model_brier': 1.}
    changed = replace_predictions([row], ['one'], p, masks, targets)[0]
    assert changed['model_brier'] == 0 and row['model_brier'] == 1
    assert changed['reference_probabilities'] == row['reference_probabilities']
    assert changed['reference_corrected_brier'] == 0.5
    with pytest.raises(ValueError, match='saved state labels/masks differ'):
        replace_predictions([row], ['one'], p, masks, targets+1)


def test_luna_fit_manifest_is_required_and_deals_deduplicated(tmp_path):
    r = record()
    raw = canonical(r)+b'\n'+canonical(r)+b'\n'
    source = tmp_path/'source'
    source.mkdir()
    (source/'private.jsonl').write_bytes(raw)
    spec = {'extras': {'split': 'fit'}, 'outputs': {'private.jsonl': {
        'private': True, 'records': 2, 'sha256': digest(raw)}}}
    (source/'manifest.json').write_bytes(canonical(spec))
    keys, manifest, _ = scale.luna_fit_source(source, tmp_path/'out')
    assert keys == {scale.record_deal_key(r)} and len(manifest['shards']) == 1
    spec['extras']['split'] = 'validation'
    (source/'manifest.json').write_bytes(canonical(spec))
    with pytest.raises(ValueError, match='explicitly fit designated'):
        scale.luna_fit_source(source, tmp_path/'out')
