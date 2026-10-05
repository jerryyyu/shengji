import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from shengji.eval.paired_window_metadata import preflight_paired_windows


@pytest.fixture
def panel(tmp_path):
    configs = {}
    for prefix in ('candidate', 'control'):
        for seed in (10, 20):
            name = f'{prefix}-{seed}'
            folder = tmp_path / name
            folder.mkdir()
            c = dict(seed0=seed, clusters=2, rule=True, runtime={'source': 'frozen'})
            configs[name] = c
            (folder / 'config.json').write_text(json.dumps(c))
            (folder / 'summary.json').write_text(json.dumps({'config': c}))
            (folder / 'cluster-00000.json').write_text('NEVER READ')
    calls = []
    def load(path):
        assert not path.name.startswith('cluster-')
        raw = path.read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    def arm_metadata(root, entry):
        calls.append(entry['directory'])
        folder = root / entry['directory']
        c, cs = load(folder / 'config.json')
        s, ss = load(folder / 'summary.json')
        return folder, c, s, cs, ss
    validator = SimpleNamespace(_load=load, _arm_metadata=arm_metadata)
    return tmp_path, configs, validator, calls


def run(panel):
    root, configs, validator, _ = panel
    return preflight_paired_windows(root, configs, seeds=(10, 20),
                                    prefixes=('candidate', 'control'), clusters=2, validator=validator)


def test_order_all_metadata_and_no_raw_reads(panel):
    entries, hashes = run(panel)
    assert [seed for seed, _ in entries] == [10, 20]
    assert panel[3] == ['candidate-10', 'control-10', 'candidate-20', 'control-20']
    assert len(hashes) == 8


@pytest.mark.parametrize('mutation', ['bool_to_int', 'runtime', 'summary_type', 'failure', 'shadow',
                                     'symlink_shard', 'extra_dir', 'missing_config', 'missing_freeze'])
def test_bad_last_arm_refused_without_raw(panel, mutation):
    root, configs, _, _ = panel
    folder = root / 'control-20'
    if mutation in ('bool_to_int', 'runtime'):
        c = copy.deepcopy(configs['control-20'])
        if mutation == 'bool_to_int':
            c['rule'] = 1
        else:
            c['runtime']['source'] = 'other'
        (folder / 'config.json').write_text(json.dumps(c))
    elif mutation == 'summary_type':
        c = dict(configs['control-20'], rule=1)
        (folder / 'summary.json').write_text(json.dumps({'config': c}))
    elif mutation == 'failure':
        (folder / 'failure.json').write_text('{}')
    elif mutation == 'shadow':
        (root / 'control-20.summary.json').write_text('{}')
    elif mutation == 'symlink_shard':
        (folder / 'cluster-00001.json').symlink_to(folder / 'cluster-00000.json')
    elif mutation == 'extra_dir':
        (root / 'other-20').mkdir()
    elif mutation == 'missing_config':
        (folder / 'config.json').unlink()
    else:
        del configs['control-20']
    with pytest.raises(ValueError):
        run(panel)


def test_validator_terminal_failure_is_not_swallowed(panel):
    def fail(*args):
        raise ValueError('unsealed summary')
    panel[2]._arm_metadata = fail
    with pytest.raises(ValueError, match='unsealed'):
        run(panel)
