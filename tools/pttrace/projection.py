"""Outcome-blind event projection of one explicitly named failed PT call."""
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
OUTPUT = Path('/root/codex-pt-trace-projection-output')
SOURCE = Path('/root/codex-pt-src-1cae46e5/server')
TRANSPORT_SHA = 'dfea3b8932ac9ad0f78f4d2965fae9a1605aadd1e55a61a9b779ee00b117d8b8'


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('invalid JSON constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def project(raw, final, parser):
    import re
    events = [strict_json(line) for line in raw.splitlines() if line]
    if not events or any(type(e) is not dict or type(e.get('type')) is not str for e in events):
        raise ValueError('invalid events')
    allowed = {'thread.started', 'turn.started', 'turn.completed', 'item.completed'}
    rejected = [(i, e['type']) for i, e in enumerate(events) if e['type'] not in allowed]
    if not rejected:
        raise ValueError('no rejected top-level event')
    index, kind = rejected[0]
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{0,79}', kind):
        raise ValueError('event type outside public bounds')
    # Assert the prefix reaches this exact guard, not an earlier item rejection.
    try:
        parser(b'\n'.join(json.dumps(e).encode() for e in events[:index+1]), use_final_message=True)
    except Exception as exc:
        if type(exc).__name__ != 'CodexTurnTransportError' or str(exc) != 'Codex trace event forbidden':
            raise ValueError('different first refusal') from None
    else:
        raise ValueError('prefix unexpectedly accepted')
    filtered = b'\n'.join(json.dumps(e).encode() for e in events if e['type'] in allowed)
    complete = agreement = False
    try:
        _, _, message = parser(filtered, use_final_message=True)
        complete = True
        agreement = strict_json(message) == strict_json(final)
    except Exception:
        pass
    return dict(first_rejected_type=kind, first_rejected_index=index,
                completed_before=any(e['type']=='turn.completed' for e in events[:index]),
                completed_after=any(e['type']=='turn.completed' for e in events[index+1:]),
                completion_valid_after_removing_rejected_events=complete,
                final_file_agrees=agreement)


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
    if any(Path('/proc', str(pid)).exists() for pid in (2340757, 2340760)):
        raise ValueError('producer live')
    terminal = read_file(ROOT / 'terminal.json', 16384)
    if hashlib.sha256(terminal).hexdigest() != TERMINAL_SHA:
        raise ValueError('terminal drift')
    OUTPUT.mkdir()
    (OUTPUT / 'claim.json').write_text(json.dumps({'mirror': KEY, 'terminal_sha256': TERMINAL_SHA}))
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
        import sys
        sys.path.insert(0, str(SOURCE))
        from shengji.luna import transport as module
        if Path(module.__file__).resolve() != transport.resolve():
            raise ValueError('parser origin drift')
        raw = read_file(TRACE_DIR / 'stdout.jsonl', 4 * 1024 * 1024)
        final = read_file(TRACE_DIR / 'final.json', 1024 * 1024)
        result = project(raw, final, module._events_and_usage)
        (OUTPUT / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
    except Exception:
        (OUTPUT / 'refusal.json').write_text('{"refused":true}\n')
        raise ValueError('projection refused; private details suppressed') from None



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args()
    run()
