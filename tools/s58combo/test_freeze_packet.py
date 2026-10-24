"""Packet assembly binds the requested recipe and cleared seed population."""
import json
from pathlib import Path
import pytest
import freeze_packet
import window_plan
import config_probe
from test_recipe import ROOT


@pytest.fixture
def packet_inputs(tmp_path, monkeypatch):
    from shengji.engine import fast, legal
    source = tmp_path/'source'
    source.mkdir()
    (source/'fly.toml').write_bytes((ROOT/'fly.toml').read_bytes())
    for name in ('server/shengji/engine/_fast.so', 'server/shengji/ai/_cwv_math.so',
                 'server/shengji/ai/_endgame_fast.so', 'tools/s58combo/launcher.py'):
        p = source/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('fixture')
    paths = []
    for name in ('play', 'old', 'new'):
        p = tmp_path/name
        p.write_text('fixture')
        paths.append(p)
    seeds = [240060910 + i*100000 for i in range(10)]
    clearance = tmp_path/'clearance'
    clearance.mkdir()
    names = ('seed_clear_smV3_reused.txt', 'seed_clear_jsm1_reused.txt', 'corpus_local.txt',
             'reservations_perf.txt', 'reservations_cloud.txt')
    for name in names:
        (clearance/name).write_text('fixture')
    composite = dict(status='PASS', overlaps=0, registry_clear=True,
        windows=[dict(seed0=s, clusters=520) for s in seeds],
        inputs={n: freeze_packet._sha(clearance/n) for n in names})
    (clearance/'composite.json').write_text(json.dumps(composite))
    monkeypatch.setenv('SHENGJI_FAST', '1')
    monkeypatch.setattr(fast, 'HAVE_FAST', True)
    def validate(*args): pass
    validate.__module__ = 'shengji.engine._fast'
    monkeypatch.setattr(legal, 'validate_follow', validate)
    monkeypatch.setattr(freeze_packet, '_require_clean_source', lambda *args: None)
    monkeypatch.setattr(freeze_packet.subprocess, 'check_output', lambda *args, **kw: 'a'*40)
    def build(envs, seeds, output, *, profile, workers):
        return dict(profile=profile, seeds=seeds, arms=envs, workers=workers)
    monkeypatch.setattr(window_plan, 'build_plan', build)
    monkeypatch.setattr(config_probe, 'probe_configs', lambda plan: dict(profile=plan['profile']))
    return dict(source=source, packet=tmp_path/'packet', output=tmp_path/'out',
                play=paths[0], old=paths[1], new=paths[2], clearance=clearance,
                seeds=seeds, profile='served-lgfd2000')


def test_guarded_profile_and_cleared_seeds_reach_frozen_packet(packet_inputs):
    args = packet_inputs
    result = freeze_packet.freeze(**args)
    plan = json.loads((args['packet']/'plan.json').read_text())
    assert plan['profile'] == 'served-lgfd2000' and plan['seeds'] == args['seeds']
    assert plan['arms'][0]['SHENGJI_PV_LEAF_GREEDY_DEADLINE'] == '2'
    assert plan['arms'][0]['SHENGJI_PV_ENCODE_BATCH_FAST'] == '1'
    assert plan['arms'][1].get('SHENGJI_PV_LEAF_GREEDY_DEADLINE', '0') == '0'
    assert result['packet_sha256'] == freeze_packet.packet_digest(plan, {'profile': plan['profile']})
    assert not args['output'].exists() and not (args['packet']/'RELEASE').exists()


def test_stale_clearance_refuses_before_packet_publication(packet_inputs):
    packet_inputs['seeds'][0] += 1
    with pytest.raises(ValueError, match='clearance'):
        freeze_packet.freeze(**packet_inputs)
    assert not packet_inputs['packet'].exists()
