import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from test_benchmark_panel_seals import packet
from test_sealed_panel_reader import full_packet


def write(path, value):
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def bundle(tmp_path):
    base = tmp_path.resolve()
    source = base / 'source'
    for name in ('scripts', 'shengji/luna'):
        (source / name).mkdir(parents=True)
    for name in ('scripts', 'shengji', 'shengji/luna'):
        (source / name / '__init__.py').write_text('')
    original = Path(__file__).resolve().parents[1]
    for name in ('scripts/run_sealed_panel_readout.py', 'shengji/luna/benchmark_readout_receipt.py'):
        (source / name).write_bytes((original / name).read_bytes())
    (source / 'scripts/sealed_production_llm_panel_readout.py').write_text(
        'from pathlib import Path\n'
        'def read_sealed_panel(path, sha):\n'
        '    with (Path(path).parent / "opened").open("x") as out: out.write("once")\n'
        '    return {"synthetic": True}\n')
    manifest = dict(schema='sol-panel-analysis-bundle-v1', source_root=str(source),
                    python=sys.executable,
                    python_binary_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                    environment={}, source_files={
                        p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in source.rglob('*.py')})
    spec = dict(schema='sol-panel-read-invocation-v1', manifest=write(base / 'manifest.json', manifest),
                plan=write(base / 'plan.json', {'synthetic': True}), output_dir=str(base / 'output'))
    return base, source, manifest, spec


def invoke(bundle):
    base, source, _, spec = bundle
    ref = write(base / 'invocation.json', spec)
    env = {k: v for k, v in os.environ.items() if not k.startswith('SHENGJI_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env.update(bundle[2].get('environment', {}))
    return subprocess.run([sys.executable, str(source / 'scripts/run_sealed_panel_readout.py'),
                           ref['path'], ref['sha256']], env=env, capture_output=True, text=True)


def test_fresh_process_once_and_receipt(bundle):
    base, _, _, spec = bundle
    first = invoke(bundle)
    assert first.returncode == 0, first.stderr
    receipt = json.loads((base / 'output/receipt.json').read_text())
    assert receipt['status'] == 'complete'
    assert receipt['identity']['plan'] == spec['plan']
    assert receipt['result_sha256'] == hashlib.sha256((base / 'output/result.json').read_bytes()).hexdigest()
    second = invoke(bundle)
    assert second.returncode != 0 and 'already exists' in second.stderr
    assert (base / 'opened').read_text() == 'once'


@pytest.mark.parametrize('corruption', ['source', 'python', 'environment', 'extra', 'manifest'])
def test_refuses_before_callback(bundle, corruption):
    base, source, manifest, spec = bundle
    if corruption == 'source':
        (source / 'scripts/sealed_production_llm_panel_readout.py').write_text('raise RuntimeError("untrusted")')
    elif corruption == 'extra':
        (source / 'scripts/extra.py').write_text('')
    elif corruption == 'manifest':
        spec['manifest']['sha256'] = '0' * 64
    else:
        if corruption == 'python':
            manifest['python_binary_sha256'] = '0' * 64
        else:
            manifest['environment']['OMP_NUM_THREADS'] = 'unmatched'
            # Change the file, not the launch environment used by invoke.
            changed = dict(manifest, environment={'OMP_NUM_THREADS': 'unmatched'})
            manifest['environment'] = {}
            spec['manifest'] = write(base / 'manifest.json', changed)
            outcome = invoke(bundle)
            assert outcome.returncode != 0
            assert not (base / 'opened').exists()
            return
        spec['manifest'] = write(base / 'manifest.json', manifest)
    outcome = invoke(bundle)
    assert outcome.returncode != 0
    assert not (base / 'opened').exists()
    assert not (base / 'output').exists()


@pytest.mark.parametrize('native', [False, True])
def test_actual_nine_row_reader_in_fresh_wrapper(bundle, full_packet, native):
    base, source, manifest, spec = bundle
    original = Path(__file__).resolve().parents[1]
    # Copy project source only, never real results. full_packet constructs all
    # nine reports, retained originals and seals from synthetic fixtures.
    for package in ('scripts', 'shengji'):
        for path in (original / package).rglob('*'):
            if not path.is_file() or path.suffix not in ('.py', '.so', '.pyd'):
                continue
            destination = source / path.relative_to(original)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
    manifest['source_files'] = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in source.rglob('*') if p.is_file()}
    if native:
        manifest['environment'] = {'SHENGJI_FAST': '1'}
    spec['manifest'] = write(base / 'manifest.json', manifest)
    spec['plan'] = write(base / 'synthetic-plan.json', full_packet[0][1])
    outcome = invoke(bundle)
    assert outcome.returncode == 0, outcome.stderr
    result = json.loads((base / 'output/result.json').read_text())
    assert result['panel_size'] == 9
    assert result['seals']['metadata_and_content_validated'] is True
    assert result['terminal_accounting']['m1-prior']['failed'] == 1
    assert result['policies']['m1-prior']['pt_sol']['forfeit_endpoint']['paired_signed_levels']['coverage']['scheduled_pairs'] == 10
    # The old directory CLI is fenced in this very same bundle.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(source))
    blocked = subprocess.run([sys.executable, '-m', 'scripts.production_llm_panel_readout', '--help'],
                             cwd=source, env=env, capture_output=True, text=True)
    assert blocked.returncode != 0 and 'forbids the directory CLI' in blocked.stderr
