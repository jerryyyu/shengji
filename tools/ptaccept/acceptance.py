"""Boolean-only reconnect-parser acceptance for one bound failed PT call."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path('/root/vol-dev-codex-pt-r46-429-20261021')
TERMINAL_SHA = '4efb92095ab5535ce64b10dd823f29e18fe509f6449ec08ad66693d928f6249e'
KEY = 'sol-perfect-seed142060913-flip0'
TARGET = 'mirror-sol-perfect-142060913-0.json'


TRACE_DIR = ROOT / 'benchmark/evidence/sol-perfect/seed-142060913-flip-0/seat-0/call-ail8no6i'
MIRROR_SHA = 'c98331895f0649e84086f219b71e7a87432b6d743ef94ff0043a789d6f5f0e89'
OUTPUT = Path('/root/codex-pt-reconnect-acceptance-output')
SOURCE = Path('/root/codex-pt-src-1cae46e5/server')
TRANSPORT_SHA = 'dfea3b8932ac9ad0f78f4d2965fae9a1605aadd1e55a61a9b779ee00b117d8b8'


BENCHMARK_SHA = 'da0c830286c3f4104b53355de92493787346b5180f9ffff9720a59b7f3ac0cf0'
PRODUCER_PIDS = (2340757, 2340760)

def project(raw, final, adapter):
    try:
        _, _, message = adapter._benchmark_events_and_usage(raw)
        if adapter._strict_json(final, "benchmark final") != adapter._strict_json(
                message.encode(), "benchmark message"):
            raise adapter.CodexTurnTransportError("benchmark final/message mismatch")
    except Exception as exc:
        # Only a bounded class name crosses the private trace boundary.
        import re
        name = type(exc).__name__
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", name):
            raise ValueError("invalid refusal class") from None
        return {"accepted": False, "refusal_class": name}
    return {"accepted": True}


def read_file(path, limit):
    if (any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > limit):
        raise ValueError('invalid diagnostic input')
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('input changed')
    return raw


def run():
    for folder in (ROOT, Path('/root/codex-pt-packet-1cae46e5'), OUTPUT.parent):
        if folder.is_symlink():
            raise ValueError('aliased diagnostic root')
    for folder in (ROOT, Path('/root/codex-pt-packet-1cae46e5'), Path(__file__).resolve().parent, TRACE_DIR):
        if any((folder / name).exists() for name in ('HOLD', 'READOUT_HOLD')):
            raise ValueError('diagnostic HOLD')
    if any(Path('/proc', str(pid)).exists() for pid in PRODUCER_PIDS):
        raise ValueError('producer live')
    terminal = read_file(ROOT / 'terminal.json', 16384)
    if hashlib.sha256(terminal).hexdigest() != TERMINAL_SHA:
        raise ValueError('terminal drift')
    OUTPUT.mkdir()
    try:
        mirror = read_file(ROOT / 'benchmark' / TARGET, 32 * 1024 * 1024)
        if hashlib.sha256(mirror).hexdigest() != MIRROR_SHA:
            raise ValueError('mirror drift')
        row = json.loads(mirror)
        failed = [c for c in row['calls'] if c.get('error') == 'CodexTurnTransportError: Codex trace event forbidden']
        if len(failed) != 1 or failed[0].get('evidence_path') != str(TRACE_DIR):
            raise ValueError('failed call binding drift')
        transport = SOURCE / 'shengji/luna/transport.py'
        if hashlib.sha256(read_file(transport, 128 * 1024)).hexdigest() != TRANSPORT_SHA:
            raise ValueError('parser drift')
        benchmark = SOURCE / 'shengji/luna/benchmark_transport.py'
        if hashlib.sha256(read_file(benchmark, 128 * 1024)).hexdigest() != BENCHMARK_SHA:
            raise ValueError('adapter drift')
        import sys
        sys.path.insert(0, str(SOURCE))
        from shengji.luna import transport as module
        if Path(module.__file__).resolve() != transport.resolve():
            raise ValueError('parser origin drift')
        from shengji.luna import benchmark_transport as adapter
        if Path(adapter.__file__).resolve() != benchmark.resolve():
            raise ValueError('adapter origin drift')
        raw = read_file(TRACE_DIR / 'stdout.jsonl', 4 * 1024 * 1024)
        final = read_file(TRACE_DIR / 'final.json', 1024 * 1024)
        result = project(raw, final, adapter)
        (OUTPUT / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
    except Exception:
        raise ValueError('acceptance check refused; private details suppressed') from None



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args()
    run()
