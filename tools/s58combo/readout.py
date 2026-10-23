"""Persist one sealed analysis; caller must first obtain exact reader review."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from launcher import _sha, packet_digest
from sealed_input import sealed_outcome_checked_result


def read_once(*, source, source_head, plan_path, expected_path, packet_sha,
              root, terminal_sha, reader_sha, result_path):
    source, root, result_path = map(Path, (source, root, result_path))
    reader = Path(__file__).resolve()
    if source.resolve() != reader.parents[2]:
        raise ValueError('reader is outside reviewed source')
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True)
    if head != source_head or dirty or _sha(reader) != reader_sha:
        raise ValueError('reviewed reader source drift')
    plan = json.loads(Path(plan_path).read_text())
    expected = json.loads(Path(expected_path).read_text())
    if packet_digest(plan, expected) != packet_sha:
        raise ValueError('reviewed packet drift')
    if result_path.parent.resolve() != root.resolve():
        raise ValueError('saved result must reside in reserved output')
    if (root / 'READOUT_HOLD').exists():
        raise ValueError('readout HOLD')
    # Reserve publication before consuming sealed data; never overwrite evidence.
    with result_path.open('x') as stream:
        json.dump(dict(status='READING', source_head=head), stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        result = sealed_outcome_checked_result(plan, expected, root=root,
            terminal_sha=terminal_sha, reader_path=reader, reader_sha=reader_sha, owner='codex')
    except Exception as exc:
        result = dict(status='READOUT_FAILED', error_type=type(exc).__name__, error=str(exc))
    result.update(reader_source_head=head, reader_sha256=reader_sha, packet_sha256=packet_sha)
    temporary = result_path.with_name(result_path.name + '.pending')
    with temporary.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, result_path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('source', 'source-head', 'plan-path', 'expected-path', 'packet-sha',
                  'root', 'terminal-sha', 'reader-sha', 'result-path'):
        parser.add_argument('--' + field, required=True)
    result = read_once(**vars(parser.parse_args()))
    print(json.dumps({'status': result['status'], 'saved': True}))
    return int(result['status'] == 'READOUT_FAILED')


if __name__ == '__main__':
    raise SystemExit(main())
