"""Only supported real-read entry for a separately reviewed analysis bundle.

Invoke in a fresh interpreter with a reviewed invocation JSON path and SHA256.
No project imports occur until its source and interpreter pins are verified.
This implements no launch, retry, or authorization discovery.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def require(value, message):
    if not value:
        raise ValueError(message)


def regular(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute canonical path required')
    for parent in path.parents:
        require(not parent.is_symlink(), 'symlink parent forbidden')
    require(stat.S_ISREG(path.lstat().st_mode), 'regular non-symlink file required')
    return path


def pinned(path, digest):
    path = regular(path)
    before = stamp(path)
    raw = path.read_bytes()
    require(stamp(path) == before, 'file changed during read')
    require(hashlib.sha256(raw).hexdigest() == digest, 'SHA256 mismatch: ' + str(path))
    return raw


def stamp(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def verify_bundle(manifest_path, digest):
    manifest = decode(pinned(manifest_path, digest))
    require(manifest['schema'] == 'sol-panel-analysis-bundle-v1', 'wrong bundle schema')
    source = Path(manifest['source_root'])
    require(source == Path(manifest_path).parent / 'source', 'source root mismatch')
    require(sys.executable == manifest['python'], 'interpreter path mismatch')
    # Virtualenv executables may be symlinks; authenticate their resolved binary.
    pinned(Path(sys.executable).resolve(), manifest['python_binary_sha256'])
    require(all(os.environ.get(k) == v for k, v in manifest['environment'].items()),
            'runtime environment mismatch')
    require(not any(k.startswith('SHENGJI_') and k not in manifest['environment']
                    for k in os.environ), 'unrecorded SHENGJI environment')
    files = manifest['source_files']
    require(type(files) is dict and bool(files), 'empty source inventory')
    stamps = {}
    for relative, expected in files.items():
        relative = Path(relative)
        require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe source path')
        path = source / relative
        pinned(path, expected)
        stamps[path] = stamp(path)
    require(Path(__file__).resolve() == source / 'scripts/run_sealed_panel_readout.py',
            'wrapper must execute from pinned bundle')
    require('scripts/run_sealed_panel_readout.py' in files, 'wrapper missing from pins')
    require(not any(source.rglob('*.pyc')), 'cached bytecode forbidden')
    for path in source.rglob('*'):
        require(not path.is_symlink(), 'source symlink forbidden')
        if path.is_file() and path.suffix in ('.py', '.so', '.pyd'):
            require(path.relative_to(source).as_posix() in files, 'unpinned importable source')
    return source, files, stamps


def run(invocation_path, invocation_sha256):
    spec = decode(pinned(invocation_path, invocation_sha256))
    require(set(spec) == {'schema', 'manifest', 'plan', 'output_dir'}, 'invocation fields mismatch')
    require(spec['schema'] in ('sol-panel-read-invocation-v1',
                              'sol-stage1-read-invocation-v1',
                              'sol-stage2-read-invocation-v1',
                              'sol-saved-feedback-panel-invocation-v1'), 'invocation schema mismatch')
    for key in ('manifest', 'plan'):
        require(set(spec[key]) == {'path', 'sha256'}, 'invalid reference')
    source, files, stamps = verify_bundle(spec['manifest']['path'], spec['manifest']['sha256'])
    require(not any(n == 'shengji' or n == 'scripts' or n.startswith(('shengji.', 'scripts.'))
                    for n in sys.modules), 'fresh interpreter required')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    from shengji.luna.benchmark_readout_receipt import run_once
    if spec['schema'] == 'sol-stage1-read-invocation-v1':
        from scripts.sealed_production_llm_panel_readout import read_sealed_stage1 as reader
    elif spec['schema'] == 'sol-stage2-read-invocation-v1':
        from scripts.sealed_production_llm_panel_readout import read_sealed_stage2 as reader
    elif spec['schema'] == 'sol-saved-feedback-panel-invocation-v1':
        from scripts.sealed_production_llm_panel_readout import read_saved_feedback_panel as reader
    else:
        from scripts.sealed_production_llm_panel_readout import read_sealed_panel as reader

    def check_imports():
        for name, module in list(sys.modules.items()):
            if name == 'shengji' or name == 'scripts' or name.startswith(('shengji.', 'scripts.')):
                file = getattr(module, '__file__', None)
                require(file is not None, 'unbound project module')
                path = Path(file).resolve()
                require(path.is_relative_to(source) and path.relative_to(source).as_posix() in files,
                        'project import escaped bundle')
        require(all(stamp(path) == expected for path, expected in stamps.items()), 'source changed')

    def read():
        if os.environ.get('SHENGJI_FAST') == '1':
            from shengji.engine import fast, legal
            require(fast.activate() and legal.check_in_hand.__module__ == 'shengji.engine._fast',
                    'native engine activation failed')
        check_imports()
        result = reader(spec['plan']['path'], spec['plan']['sha256'])
        check_imports()
        return result

    return run_once(spec['output_dir'], {
        'invocation_sha256': invocation_sha256, 'manifest': spec['manifest'],
        'plan': spec['plan'], 'python': sys.executable,
    }, read)


if __name__ == '__main__':
    require(len(sys.argv) == 3, 'usage: run_sealed_panel_readout.py INVOCATION SHA256')
    run(sys.argv[1], sys.argv[2])
