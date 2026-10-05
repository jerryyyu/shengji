"""Local synthetic integration against the retained, pinned historical fixtures."""
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types

import pytest

for name, path in (
    ('shengji', '/private/tmp/shengji-policy-admission-20260929/server/shengji'),
    ('shengji.train', '/private/tmp/shengji-policy-admission-20260929/server/shengji/train'),
):
    module = types.ModuleType(name)
    module.__path__ = [path]
    sys.modules[name] = module
sys.path.insert(0, '/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/readers')
import test_v50t38_reader as fixture
import v52ec_reader as reader

with tempfile.TemporaryDirectory(prefix='v52ec-full-synthetic-') as tmp, pytest.MonkeyPatch.context() as mp:
    tmp = Path(tmp)
    root = tmp / 'root'
    root.mkdir()
    templates = json.loads(reader.CONFIGS.read_text())
    for template in templates:
        template['clusters'] = 2
    configs = tmp / 'templates.json'
    configs.write_text(json.dumps(templates))
    mp.setattr(reader, 'CONFIGS', configs)
    mp.setattr(reader, 'CONFIG_SHA', hashlib.sha256(configs.read_bytes()).hexdigest())
    mp.setattr(reader, 'CLUSTERS', 2)
    for side, prefix in enumerate(reader.PREFIXES):
        for seed in reader.HOST_SEEDS['cloud']:
            config = dict(templates[side], seed0=seed)
            name = f'{prefix}-{seed}'
            fixture.f._arm(root, name, config, [11, 7] if side == 0 else [-1, 1], 'a' * 16)
            for path in (root / name).glob('cluster-*.json'):
                obj = json.loads(path.read_text())
                obj['recipe'] = fixture.f.readout_module._recipe(config)
                obj['decision_traces'] = [dict(mirror=0, side='arm', decisions=[fixture.record(True), fixture.record(False)])]
                fixture.f._write(path, obj)
    reservation = tmp / 'reservation.json'
    reservation.write_text(json.dumps(dict(schema='claude-reservation-v1', lane='v52ec',
        seeds=list(reader.HOST_SEEDS['cloud']), count=2,
        pairing='candidate and control on the same seeds', launcher='/root/claude_v52ec_screen_cloud.sh',
        launcher_sha256=reader.LAUNCHER_SHA, status='/root/claude_v52ec_screen.status',
        output_root='/root/vol-screen-claude-v52ec-r38-20261005', created_at='2026-10-05T00:00:00Z',
        expected_identity={side: sha + '  /root/claude_v52ec_expected_' + suffix + '.json'
                           for side, suffix, sha in zip(('candidate', 'comparator'), ('cand', 'cmp'), reader.EXPECTED_SHA)})))
    status = tmp / 'status'
    status.write_text('2026-10-05T00:00:00Z v52ec armed (pid 123, launcher sha256 ' + reader.LAUNCHER_SHA + ')\n'
                      '2026-10-05T01:00:00Z v52ec PHASE B DONE (release 38 as served x5, same seeds); LANE DONE\n')
    reads = []
    original = Path.read_bytes
    def observe(path):
        if path.name.startswith('cluster-'):
            reads.append(path)
        return original(path)
    mp.setattr(Path, 'read_bytes', observe)
    result = reader.analyze(root, reservation=reservation, status=status)
    assert len(reads) == len(set(reads)) == 20
    assert len(result['windows']) == 5 and len(result['receipts']) == 10
    assert result['triage']['mean'] == pytest.approx(9)
    assert result['statistical_result'] == 'POSITIVE'
    assert result['extension'].startswith('no extension')
    assert result['strength_verdict'] == 'WITHHELD_PENDING_HEALTH_AND_PROVENANCE_REVIEW'
    assert all(row['counts']['valid_records'] == 20 for row in result['refusal_observation_summary'].values())
    expected_max = max(fixture.record(flag)['refusal_observations'] for flag in (True, False))
    assert all(row['max_observations'] == expected_max for row in result['refusal_observation_summary'].values())
    assert 'common_config_sha256' not in result
    reads.clear()
    last = root / f'{reader.PREFIXES[1]}-{reader.HOST_SEEDS["cloud"][-1]}' / 'config.json'
    c = json.loads(last.read_text())
    c['arm_policy_identity']['config']['worlds'] = 999
    last.write_text(json.dumps(c))
    with pytest.raises(ValueError, match='frozen complete config'):
        reader.analyze(root, reservation=reservation, status=status)
    assert reads == []
    print('PASS: full v52 reader,5 windows/20 unique synthetic shards; primary+health+extension; last-arm drift refused before raw')
