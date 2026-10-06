import copy

import pytest

from shengji.eval.s11_admission_once import plan_s11_staging
from shengji.eval.s11_manifest import select_manifest_shards
from test_s11_manifest import manifest, encode


def test_only_fixed_selected_shards_and_identity_fields(manifest, capsys):
    # Native producer metadata may contain outcome aggregates. Never forward
    # arbitrary manifest dictionaries to stdout, receipts or transfer lists.
    manifest['private_outcomes'] = {'winner': 2, 'score': 900, 'levels': 13}
    raw, pin = encode(manifest)
    plan = plan_s11_staging(raw, manifest_sha256=pin)
    selected = select_manifest_shards(raw, sha256=pin)
    assert len(plan['files']) == len({s['path'] for s in plan['files']}) == 64
    assert plan['files'] == [dict(path=s.path, sha256=s.sha256,
        bytes=s.byte_count, draw_index=s.draw_index) for s in selected]
    assert set(plan) == {'schema', 'manifest_sha256', 'manifest_bytes', 'files',
        'shard_bytes', 'max_manifest_bytes', 'max_shard_bytes', 'max_total_shard_bytes'}
    assert plan['shard_bytes'] == sum(s.byte_count for s in selected)
    assert plan['shard_bytes'] <= plan['max_total_shard_bytes']
    assert all(s['path'].endswith('.jsonl') for s in plan['files'])
    assert capsys.readouterr() == ('', '')


def test_manifest_and_selected_byte_limits_fail_closed(manifest):
    with pytest.raises(ValueError, match='8MiB'):
        plan_s11_staging(b' ' * ((8 << 20) + 1), manifest_sha256='a' * 64)
    for s in manifest['shards']:
        s['bytes'] = (4 << 20) + 1
    raw, pin = encode(manifest)
    with pytest.raises(ValueError, match='no replacement'):
        plan_s11_staging(raw, manifest_sha256=pin)


def test_exact_transport_ceiling_is_accepted(manifest):
    for s in manifest['shards']:
        s['bytes'] = 4 << 20
    raw, pin = encode(manifest)
    assert plan_s11_staging(raw, manifest_sha256=pin)['shard_bytes'] == 256 << 20


@pytest.mark.parametrize('bad_path', ['../secret', '/etc/passwd',
    'shards/cluster-000000.jsonl\n/etc/passwd', '--files-from=secret'])
def test_malformed_inventory_cannot_enter_transfer_plan(manifest, bad_path):
    altered = copy.deepcopy(manifest)
    altered['shards'][0]['path'] = bad_path
    raw, pin = encode(altered)
    with pytest.raises(ValueError, match='canonical'):
        plan_s11_staging(raw, manifest_sha256=pin)


def test_staging_requires_pinned_manifest_before_parsing():
    with pytest.raises(ValueError, match='SHA256'):
        plan_s11_staging(b'not json', manifest_sha256='a' * 64)


def test_admission_enforces_transport_ceiling_before_shard_access(tmp_path, manifest, monkeypatch):
    from shengji.eval import s11_admission_once as module
    for s in manifest['shards']:
        s['bytes'] = (4 << 20) + 1
    raw, pin = encode(manifest)
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_bytes(raw)
    output = tmp_path / 'admission'
    output.mkdir()
    monkeypatch.setattr(module, 'read_s11_inputs', lambda *a, **kw: pytest.fail('opened shard'))
    with pytest.raises(ValueError, match='admission failed'):
        module.admit_s11_inputs_once(manifest_path, tmp_path, output,
            manifest_sha256=pin, packet_sha256='a' * 64, max_manifest_bytes=8 << 20)
    assert not (output / 'bundle.json').exists()
