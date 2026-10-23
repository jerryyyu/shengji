"""Assemble a host-local review packet; never write RELEASE or dispatch."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tomllib

from launcher import _sha, _require_clean_source, packet_digest, render_wrapper


def freeze(source, packet, output, play, old, new):
    source, packet, output = map(lambda p: Path(p).resolve(), (source, packet, output))
    if packet.exists() or output.exists():
        raise ValueError('packet and output must be new paths')
    if os.environ.get('SHENGJI_FAST') != '1':
        raise ValueError('compiled admission required')
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    _require_clean_source(source, head)
    from recipe import arm_envs
    from window_plan import build_plan
    from config_probe import probe_configs
    from shengji.engine import fast
    from shengji.engine import legal
    if not fast.HAVE_FAST or legal.validate_follow.__module__ != 'shengji.engine._fast':
        raise ValueError('compiled engine unavailable')
    base = tomllib.loads((source / 'fly.toml').read_text())['env']
    envs = arm_envs(base, play, old, new)
    envs[0].update(SHENGJI_PV_ENCODE_PREFIX_CACHE='1', SHENGJI_PV_LEAF_GREEDY_STREAM='1')
    plan = build_plan(envs, [230060910 + i * 100000 for i in range(10)], output,
                      profile='served', workers=14)
    artifacts = [Path(p).resolve() for p in (play, old, new, sys.executable)]
    for pattern in ('shengji/engine/_fast*.so', 'shengji/ai/_cwv_math*.so', 'shengji/ai/_endgame_fast*.so'):
        matches = list((source / 'server').glob(pattern))
        if len(matches) != 1:
            raise ValueError('compiled extension inventory mismatch')
        artifacts += matches
    plan.update(source_head=head, source_path=str(source), host_identity={'hostname': socket.gethostname()},
                host_lock='/root/.claude-host.lock', hold=str(packet / 'HOLD'),
                legacy_locks=['/root/.claude-screen.lock', '/root/.claude-datagen.lock'],
                artifact_sha256={str(p): _sha(p) for p in artifacts},
                dispatch_authorized=True,
                pending=['host capacity qualification', 'exact packet review', 'RELEASE'],
                analysis_contract={'contrast': 'candidate minus comparator levels/round',
                    'windows': 10, 'clusters_per_window': 520, 'paired_mirrors': True,
                    'positive': 'standalone 95% CI lower > 0', 'goal': 0.05,
                    'extension': False, 'pool_with_previous': False,
                    'readout_owner': 'codex', 'readout': 'HOLD until exact reader independently reviewed',
                    'raw_access': 'No raw screen outcomes before named handoff and reader PASS; reuse saved result',
                    'terminal': 'LANE_DONE with all20 return codes zero and per-window seals',
                    'invalid': 'No strength estimate on any failed scientific gate; preserve all shards',
                    'reader_source': 'tools/s58combo/*_gate.py, admission.py, paired_result.py, sealed_input.py',
                    'fault_ceilings': {'play_fallback': 0, 'belief_fallback': 0.01,
                                      'exact_abandon': 0.02, 'bury_fallback': 0.01, 'declare_abandon': 0.01}})
    expected = probe_configs(plan)
    digest = packet_digest(plan, expected)
    packet.mkdir()
    for name, value in [('plan.json', plan), ('expected.json', expected)]:
        (packet / name).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    runner = source / 'tools/s58combo/launcher.py'
    wrapper = packet / 'screen.sh'
    wrapper.write_text(render_wrapper(digest, _sha(runner)))
    wrapper.chmod(0o755)
    capacity = packet / 'capacity.py'
    capacity.write_text('''import hashlib,json,subprocess,sys
from pathlib import Path
source=Path(__SOURCE__)
packet=Path(__PACKET__)
if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=__HEAD__:
    raise SystemExit('source drift')
sys.path.insert(0,str(source/'tools/s58combo'))
sys.path.insert(0,str(source/'server'))
from launcher import packet_digest,_sha
plan=json.loads((packet/'plan.json').read_text())
expected=json.loads((packet/'expected.json').read_text())
if packet_digest(plan,expected)!=__DIGEST__:
    raise SystemExit('packet drift')
if not (packet/'CAPACITY_RELEASE').is_file() or (packet/'CAPACITY_RELEASE').read_text().strip()!=_sha(Path(__file__)):
    raise SystemExit('capacity RELEASE absent or wrong')
from capacity_probe import run_rehearsal
result=run_rehearsal(plan,source=source,output=Path(__OUTPUT__),host_lock=Path(plan['host_lock']),
                     hold=Path(plan['hold']),legacy_locks=tuple(map(Path,plan['legacy_locks'])))
print(json.dumps(result,sort_keys=True),flush=True)
'''.replace('__SOURCE__', repr(str(source))).replace('__PACKET__', repr(str(packet))).replace('__HEAD__', repr(head))
       .replace('__DIGEST__', repr(digest)).replace('__OUTPUT__', repr(str(output) + '-capacity')))
    compile(capacity.read_text(), str(capacity), 'exec')
    manifest = dict(source_head=head, packet_sha256=digest,
                    files={p.name: _sha(p) for p in (packet / 'plan.json', packet / 'expected.json', wrapper, capacity)},
                    qualification_output=str(output) + '-capacity', screen_output=str(output),
                    python=sys.executable, source=str(source))
    (packet / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('source', 'packet', 'output', 'play', 'old', 'new'):
        p.add_argument('--' + name, required=True, type=Path)
    print(json.dumps(freeze(**vars(p.parse_args())), sort_keys=True))
