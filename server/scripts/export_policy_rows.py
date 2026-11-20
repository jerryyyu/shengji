"""Copy validated policy chunks into a self-contained, movable trainer input.

The source may be a composed tree with absolute links. The export has regular
chunk files and an explicit, consumer-validated points scale; source manifest
hashes remain provenance, not runtime dependencies. No arrays are re-encoded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.policy_rows import PolicyRowsStream  # noqa: E402


def export(source: Path, out: Path, *, version: int) -> dict:
    source, out = Path(source).resolve(), Path(out)
    if out.exists() or out.is_symlink():
        raise ValueError(f'output exists: {out}')
    out = out.resolve()
    raw = (source / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    targets = []
    names = set()
    for chunk in manifest['chunks']:
        name = chunk['file']
        if Path(name).name != name or not name.endswith('.npz') or name in names:
            raise ValueError('chunk names must be unique npz basenames')
        names.add(name)
        targets.append((source / name).resolve(strict=True))
    for directory in {source, *(p.parent for p in targets)}:
        if out == directory or out in directory.parents or directory in out.parents:
            raise ValueError('output overlaps source or linked chunks')
    provenance = []
    seen = set()
    snapshots = {}

    def record(directory):
        directory = Path(directory).resolve()
        if directory in seen:
            return
        seen.add(directory)
        data = (directory / 'manifest.json').read_bytes()
        snapshots[directory] = hashlib.sha256(data).hexdigest()
        provenance.append(snapshots[directory])
        for part in json.loads(data).get('composed_from') or []:
            record(part['dir'])

    record(source)
    stream = PolicyRowsStream(source, window=1, version=version)
    if stream.values_scale != 'points':
        raise ValueError('portable export requires verified explicit points scale')
    if stream.n != manifest['rows']:
        raise ValueError('source manifest row count differs from consumer')

    if snapshots[source] != hashlib.sha256(raw).hexdigest():
        raise ValueError('source manifest changed during validation')
    # Scale recursion has already validated every source. The portable leaf
    # carries the established scale instead of retaining external dependencies.
    result = dict(manifest)
    result.pop('composed_from', None)
    result['values_scale'] = 'points'
    result['exported_from'] = {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                              'source_manifest_sha256s': provenance}
    result['chunks'] = [{k: v for k, v in c.items() if k != 'source'} for c in manifest['chunks']]
    out.mkdir(parents=True)
    for chunk, target in zip(result['chunks'], targets):
        tmp = out / (chunk['file'] + '.tmp')
        digest = hashlib.sha256()
        with target.open('rb') as src, tmp.open('xb') as dst:
            for block in iter(lambda: src.read(1024 * 1024), b''):
                digest.update(block)
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        if digest.hexdigest() != chunk['sha256']:
            raise ValueError(f'source changed while copying {chunk["file"]}')
        tmp.rename(out / chunk['file'])
    for directory, expected in snapshots.items():
        if hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest() != expected:
            raise ValueError('source manifest changed during export')
    tmp = out / 'manifest.json.tmp'
    with tmp.open('x') as f:
        json.dump(result, f, indent=1)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp.rename(out / 'manifest.json')
    return {'rows': stream.n, 'chunks': len(targets), 'source_manifest_sha256':
            result['exported_from']['manifest_sha256']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--encoder-version', type=int, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(export(args.source, args.out, version=args.encoder_version)))


if __name__ == '__main__':
    main()
