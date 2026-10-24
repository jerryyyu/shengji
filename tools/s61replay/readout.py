"""One-shot extraction of the named replay pair; requires external exact review."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from extract import LOCATOR
from selector import select_pair

TERMINAL = 's61dev DEV output sealed; rc/status only (strength qualification is reader-owned); LANE DONE'


def extract_once(source, *, source_sha, terminal, terminal_sha, hold, output,
                 locator=LOCATOR, expected_rows=1200):
    """Preserve a consumption claim even if selection or publication fails.

    The caller establishes authorization, reviewed source identity and dead
    producer ownership. Only the selected prefixes enter the saved result.
    """
    source, terminal, hold, output = map(Path, (source, terminal, hold, output))
    if hold.exists() or hold.is_symlink():
        raise ValueError('readout HOLD')
    if source.is_symlink() or not source.is_file() or terminal.is_symlink():
        raise ValueError('unaliased source and terminal required')
    if terminal.stat().st_size > 128 * 1024:
        raise ValueError('terminal exceeds metadata bound')
    raw = terminal.read_bytes()
    if hashlib.sha256(raw).hexdigest() != terminal_sha:
        raise ValueError('terminal seal drift')
    lines = raw.decode().splitlines()
    if not lines or not lines[-1].endswith(TERMINAL):
        raise ValueError('terminal not LANE DONE')
    if output.is_symlink() or not output.is_dir():
        raise ValueError('existing unaliased output directory required')
    result = output / 'prefix.json'
    if result.exists() or result.is_symlink():
        raise FileExistsError('saved prefix exists; reuse it')
    with (output / 'consumed.json').open('x') as stream:
        json.dump(dict(owner='codex', source=str(source.resolve()), source_sha256=source_sha,
                       terminal_sha256=terminal_sha, locator=locator), stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    if hold.exists() or hold.is_symlink():
        raise ValueError('readout HOLD appeared')
    with source.open('rb') as stream:
        selected = select_pair(stream, source_sha, locator=locator, expected_rows=expected_rows)
    with result.open('x') as stream:
        json.dump(selected, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'source-sha', 'terminal', 'terminal-sha', 'hold', 'output',
                'reader-head', 'reader-sha'):
        parser.add_argument('--' + key, required=True)
    args = vars(parser.parse_args())
    reader = Path(__file__).resolve()
    root = reader.parents[2]
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain',
                                    '--untracked-files=no'], text=True)
    if (head != args.pop('reader_head') or dirty
            or hashlib.sha256(reader.read_bytes()).hexdigest() != args.pop('reader_sha')):
        raise ValueError('reviewed reader drift')
    result = extract_once(**args)
    print(json.dumps(dict(saved=str(result), status='PREFIX_EXTRACTED')))


if __name__ == '__main__':
    main()
