import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('metadata_plan', Path(__file__).parents[1] / 'scripts/plan_joint_metadata_benchmark.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_reference_and_matched_twins(tmp_path):
    result = mod.plan('/data', '/omit', '/retain', '/python', tmp_path / 'fresh')
    assert result['status'] == 'HELD_NOT_ARMED'
    attribution, retained, omitted = result['arms']
    for arm in result['arms']:
        a = arm['argv']
        assert a.count('--data') == 20
        assert a[a.index('--epochs') + 1] == '1'
        assert a[a.index('--policy-rows') + 1] == '/data/fl-pilot/policy_rows_v9'
        assert a[a.index('--policy-weight') + 1] == '0.2'
        assert '--policy-soft-targets' not in a
        assert a.count('--eval-holdout') == 4
    assert '--loader-stage-timing' in attribution['argv']
    assert '--loader-stage-timing' not in retained['argv'] + omitted['argv']
    assert retained['argv'][:-1] == omitted['argv'][:-1]
    assert not (tmp_path / 'fresh').exists()


def test_refuses_alias_and_existing_output(tmp_path):
    with pytest.raises(ValueError, match='separate'):
        mod.plan('/data', '/same', '/same', '/python', tmp_path / 'fresh')
    with pytest.raises(ValueError, match='fresh'):
        mod.plan('/data', '/omit', '/retain', '/python', tmp_path)
    with pytest.raises(ValueError, match='absolute'):
        mod.plan('relative', '/omit', '/retain', '/python', tmp_path / 'fresh')


def test_soft_reference_changes_only_policy_targets(tmp_path):
    args = ('/data', '/omit', '/retain', '/python', tmp_path / 'fresh')
    hard = mod.plan(*args)
    soft = mod.plan(*args, recipe='gen4-run4-soft')
    assert soft['status'] == 'HELD_NOT_ARMED'
    assert soft['reference_recipe'] == 'gen4-run4-soft'
    for before, after in zip(hard['arms'], soft['arms']):
        expected = list(before['argv'])
        expected[expected.index('--policy-rows') + 1] = '/data/fl-pilot/policy_rows_v10'
        expected[expected.index('--policy-weight') + 1] = '1.0'
        at = expected.index('--init')
        expected[at:at] = ['--policy-soft-targets', '--policy-soft-temperature', '1.0']
        assert after['argv'] == expected
        assert after['environment'] == before['environment']
        assert after['cwd'] == before['cwd']
    assert not (tmp_path / 'fresh').exists()
    with pytest.raises(ValueError, match='unknown reference'):
        mod.plan(*args, recipe='unknown')


def test_exact_optimizer_delta_only():
    source = 'prefix\n' + mod.NEEDLE + '\nsuffix\n'
    patch = mod.retained_metadata_patch(source)
    assert '-            "include_metadata": False,' in patch
    assert '+            "include_metadata": True,' in patch
    for bad in ('unrecognized', source + source):
        with pytest.raises(ValueError, match='exactly one'):
            mod.retained_metadata_patch(bad)


@pytest.mark.parametrize('recipe', ['gen4-run1', 'gen4-run4-soft'])
def test_cli_prints_only_and_refuses_run(tmp_path, recipe):
    tree = tmp_path / 'source'
    trainer = tree / 'server/shengji/train/train_cwv.py'
    trainer.parent.mkdir(parents=True)
    trainer.write_text(mod.NEEDLE + '\n')
    out = tmp_path / 'output'
    argv = [sys.executable, str(SPEC.origin), '--base', str(tmp_path / 'data'),
            '--omitted-source', str(tree), '--retained-source', str(tmp_path / 'retained'),
            '--python', '/nonexistent-trainer-python', '--output', str(out), '--recipe', recipe]
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'HELD_NOT_ARMED' in result.stdout
    assert not out.exists()
    assert not (tmp_path / 'retained').exists()
    assert trainer.read_text() == mod.NEEDLE + '\n'
    refused = subprocess.run(argv + ['--run'], capture_output=True, text=True)
    assert refused.returncode != 0
    assert 'unrecognized arguments: --run' in refused.stderr
    assert not out.exists()
