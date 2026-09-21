import importlib.util
import json
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


@pytest.fixture
def planner(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('gen_full_plan', SCRIPTS / 'plan_gen_production_full.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_packet_is_matched_and_keeps_four_model_family(planner):
    p = planner.packet('python', 'gen4.pt', 'gen3.pt', 'prod.npz', '/unused')
    assert p['launch_hold'] is True
    assert p['source_git_sha'] == '75bc524a1580d8fe8d306b4977f1a6346a9d1027'
    assert p['analysis']['family_size'] == len(p['analysis']['family']) == 4
    assert p['analysis']['primary_confidence'] == .9875
    assert p['analysis']['bootstrap_seed'] == 20260921
    expected = [
        ('GEN4_W64_K8', 'gen4.pt', '3f83bfb7cac5580ec2711c856c5a26cba68670ea3bcdd595040ffa0216a4de7e'),
        ('GEN3_W64_K8', 'gen3.pt', 'd2514e6e2c71dcef1331174f29e6aaf73941b18fc32c241b6f3cb6afae9ef72f'),
    ]
    for arm, (name, checkpoint, digest) in zip(p['arms'], expected, strict=True):
        assert arm['name'] == name
        argv = arm['command']
        for flag, value in {'--seed0': '625800000', '--deals': '800',
                            '--worlds': '64', '--candidates': '8', '--workers': '12',
                            '--mode': 'policy-value', '--control': 'production-play',
                            '--checkpoint': checkpoint, '--checkpoint-sha256': digest,
                            '--production-checkpoint': 'prod.npz'}.items():
            assert argv[argv.index(flag) + 1] == value


def test_plan_never_reads_or_creates_paths(planner, tmp_path, capsys):
    out = tmp_path / 'absent'
    argv = ['--python', '/missing/python', '--gen4-checkpoint', '/missing/gen4',
            '--gen3-checkpoint', '/missing/gen3', '--production-checkpoint', '/missing/prod',
            '--out', str(out)]
    assert planner.main(argv) == 0
    assert json.loads(capsys.readouterr().out)['launch_hold'] is True
    assert not out.exists()
    with pytest.raises(RuntimeError, match='launch held'):
        planner.main(argv + ['--run'])
    assert not out.exists()
