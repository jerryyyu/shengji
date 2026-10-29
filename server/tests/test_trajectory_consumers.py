import json

import pytest

from scripts.validate_trajectory_consumers import validate_store
from shengji.harvest.trajectory import sha256_file
from shengji.train.cwv_data import TrainDataError
from test_harvest_trajectory_pv import _gen, data_policy, package  # noqa: F401


@pytest.fixture
def store(tmp_path, data_policy):
    root = tmp_path / 'corpus'
    _gen(root, data_policy, explore_rate=0, explore_k=0)
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['identity']['git_dirty'] = False
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return root, manifest


def check(store):
    root, manifest = store
    return validate_store(root, expected_rounds=2,
                          expected_source=manifest['identity']['git_sha'])


def test_complete_store_reaches_both_consumers(store):
    result = check(store)
    assert result['status'] == 'PASS'
    assert result['counts']['pv_rows'] > 0
    assert result['counts']['pv_rows'] == result['counts']['belief_rows']
    assert result['counts']['records'] == store[1]['counts']['records']


@pytest.mark.parametrize('defect', ['partial', 'duplicate', 'path', 'count', 'source'])
def test_bad_completed_manifest_is_refused(store, defect):
    root, manifest = store
    if defect == 'partial':
        (root / 'manifest.json').unlink()
    else:
        if defect == 'duplicate':
            manifest['shards'] *= 2
        elif defect == 'path':
            manifest['shards'][0]['path'] = '../outside.jsonl'
        elif defect == 'count':
            manifest['counts']['plays'] += 1
        elif defect == 'source':
            manifest['identity']['git_dirty'] = True
        (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        check(store)


def test_matching_hashes_do_not_hide_unusable_training_rows(store):
    root, manifest = store
    entry = manifest['shards'][0]
    shard = root / entry['path']
    records = [json.loads(line) for line in shard.read_text().splitlines()]
    next(r for r in records if r['decision_kind'] == 'play')['outcome'] = None
    shard.chmod(0o600)
    shard.write_text(''.join(json.dumps(r) + '\n' for r in records))
    side_path = root / entry['sidecar']
    side = json.loads(side_path.read_text())
    side.update(bytes=shard.stat().st_size, sha256=sha256_file(shard))
    side_path.chmod(0o600)
    side_path.write_text(json.dumps(side))
    entry.update(bytes=side['bytes'], sha256=side['sha256'],
                 sidecar_sha256=sha256_file(side_path))
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(TrainDataError, match='no_outcome'):
        check(store)


@pytest.mark.parametrize('field', ['schema', 'record_schema', 'source'])
def test_unknown_protocol_is_refused(store, field):
    root, manifest = store
    manifest[field] = 'unknown-future-protocol'
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='unsupported manifest protocol'):
        check(store)
