import copy
import hashlib
import json

import pytest

from shengji.eval.s11_input_bundle import (
    load_s11_input_bundle, publish_s11_input_bundle,
)
from test_s11_schedule import PIN, refusal, slots, trajectory


def publish(slots, path, pin=PIN):
    return publish_s11_input_bundle(slots, path, manifest_sha256=pin,
                                    packet_sha256='b' * 64)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def reload(raw):
    return load_s11_input_bundle(raw, sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('count', [0, 1, 4])
def test_exact_roundtrip_and_input_only_ledger(tmp_path, slots, count, capsys):
    for i in range(count):
        slots[i] = refusal(slots[i])
    before = copy.deepcopy(slots)
    path = tmp_path / 'bundle.json'
    receipt = publish(slots, path)
    loaded, repeated = load_s11_input_bundle(path.read_bytes(),
                                            sha256=receipt['bundle_sha256'])
    assert loaded == before == slots
    assert repeated == receipt
    assert receipt['counts'] == dict(completed=0, interrupted=0,
                                    refused=count, unattempted=64-count)
    assert set(receipt) == {'schema', 'bundle_sha256', 'manifest_sha256',
        'packet_sha256', 'seed', 'fill_seed', 'max_public_refusals', 'ledger', 'counts'}
    for row in receipt['ledger']:
        assert set(row) == {'root_id', 'draw_index', 'status'}
    # Receipt whitelist excludes fixture state, reasons and all outcome fields.
    assert capsys.readouterr() == ('', '')
    assert path.stat().st_mode & 0o777 == 0o400
    with pytest.raises(ValueError, match='occupied'):
        publish(slots, path)


@pytest.mark.parametrize('stage,count', [('shard', 1), ('terminal', 1),
                                        ('public-projection', 5)])
def test_refusal_gates_leave_no_publication(tmp_path, slots, stage, count):
    for i in range(count):
        slots[i] = refusal(slots[i], stage)
    with pytest.raises(ValueError, match='refusal'):
        publish(slots, tmp_path / 'bundle.json')
    assert list(tmp_path.iterdir()) == []


def test_digest_is_checked_before_json_or_fixture_parsing(tmp_path, slots, monkeypatch):
    import shengji.eval.s11_input_bundle as module
    path = tmp_path / 'bundle.json'
    receipt = publish(slots, path)
    monkeypatch.setattr(module, 'fixture_from_json', lambda *_: pytest.fail('parsed drift'))
    with pytest.raises(ValueError, match='SHA256'):
        load_s11_input_bundle(path.read_bytes() + b' ', sha256=receipt['bundle_sha256'])


@pytest.mark.parametrize('damage', ['ledger', 'count', 'extra', 'order', 'missing',
    'ply', 'fixture-extra', 'setup-private', 'play-outcome', 'observed', 'seat-type',
    'ceiling', 'fill', 'seed', 'duplicate', 'nonfinite', 'rank-payload',
    'declaration-payload', 'attempt-payload'])
def test_authenticated_malformed_bundle_refused(tmp_path, slots, damage):
    path = tmp_path / 'bundle.json'
    publish(slots, path)
    value = json.loads(path.read_bytes())
    fx = value['slots'][0]['fixture']
    if damage == 'ledger':
        value['ledger'][0]['status'] = 'completed'
    elif damage == 'count':
        value['counts']['completed'] = 64
    elif damage == 'extra':
        value['winner'] = 1
    elif damage == 'order':
        value['slots'].reverse()
    elif damage == 'missing':
        value['slots'].pop()
    elif damage == 'ply':
        value['slots'][0]['selected_ply'] -= 1
    elif damage == 'fixture-extra':
        fx['winner'] = 1
    elif damage == 'setup-private':
        fx['setup']['round_seed'] = 123
    elif damage == 'play-outcome':
        fx['plays'][0]['outcome_for'] = 1
    elif damage == 'observed':
        fx['observed'] = {'winner': 1}
    elif damage == 'seat-type':
        fx['seat'] = str(fx['seat'])
    elif damage == 'rank-payload':
        fx['setup']['trump_rank'] = {'winner': 1}
    elif damage == 'declaration-payload':
        fx['setup']['declarations'] = [{'seat': 0, 'cards': ['winner=1']}]
    elif damage == 'attempt-payload':
        fx['plays'][0]['attempted'] = ['winner=1']
    elif damage in ('ceiling', 'fill', 'seed'):
        value[{'ceiling': 'max_public_refusals', 'fill': 'fill_seed', 'seed': 'seed'}[damage]] = 9
    raw = encoded(value)
    if damage == 'duplicate':
        raw = b'{"seed":0,' + raw[1:]
    elif damage == 'nonfinite':
        raw = raw.replace(b'"seed":0', b'"seed":NaN')
    with pytest.raises(ValueError):
        reload(raw)


def test_real_input_reader_roundtrip_without_second_raw_access(tmp_path, monkeypatch):
    from test_s11_input_join import input_frame
    from shengji.eval import s11_inputs
    manifest, pin, shards = input_frame(tmp_path)
    for cluster, raw in shards.items():
        (tmp_path / 'shards' / f'cluster-{cluster:06d}.jsonl').write_bytes(raw)
    slots = s11_inputs.read_s11_inputs(manifest, sha256=pin, root=tmp_path)
    assert len(slots) == 64 and all(s['status'] == 'valid' for s in slots)
    path = tmp_path / 'bundle.json'
    receipt = publish(slots, path, pin)
    monkeypatch.setattr(s11_inputs, '_read_shard', lambda *_: pytest.fail('raw reread'))
    restored, _ = load_s11_input_bundle(path.read_bytes(), sha256=receipt['bundle_sha256'])
    assert restored == slots


def test_illegal_public_history_refuses_before_publication_and_reload(tmp_path, slots):
    from shengji.eval.tactical import fixture_from_json
    path = tmp_path / 'bundle.json'
    publish(slots, path)
    value = json.loads(path.read_bytes())
    fx = value['slots'][0]['fixture']
    play = next(p for p in fx['plays'] if p['seat'] != fx['seat'])
    play['seat'] = next(s for s in range(4) if s not in (fx['seat'], play['seat']))
    # This passes the coarse fixture loader but cannot reconstruct legal play.
    slots[0]['fixture'] = fixture_from_json(fx)
    refused = tmp_path / 'refused.json'
    with pytest.raises(ValueError):
        publish(slots, refused)
    assert not refused.exists() and not (tmp_path / '.refused.json.partial').exists()
    with pytest.raises(ValueError):
        reload(encoded(value))
