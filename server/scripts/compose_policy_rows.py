"""Compose tagged C12 policy rows without copying/re-encoding chunk arrays.

All inputs must declare exploration tags and carry both arrays in every chunk.
The real PolicyRowsStream consumer still verifies hashes, shapes and counts;
this metadata-only step does not claim to validate arbitrary chunk contents.
Existing outputs are refused. Failure during publication may leave an incomplete
directory; inspect it rather than overwriting/reusing it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import zipfile


def _counts(value, rows):
    if (not isinstance(value, dict) or set(value) != {'0', '1', '2'}
            or any(type(n) is not int or n < 0 for n in value.values())
            or sum(value.values()) != rows):
        raise ValueError('exploration counts must cover every row')
    return value


def compose(out: Path, parts: list[tuple[str, Path]]) -> dict:
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise ValueError(f'output already exists: {out}')
    if not parts:
        raise ValueError('at least one tagged source is required')
    heads, tags, targets, chunks, sources, corpora = [], set(), set(), [], [], []
    output_names = set()
    totals = {k: 0 for k in ('0', '1', '2')}
    rows = deals = 0
    names = {'0': 'no_draw', '1': 'draw_in_ballot', '2': 'draw_beat_shortlist'}
    for tag, src in parts:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', tag) or tag in tags:
            raise ValueError('source tags must be unique safe names')
        tags.add(tag)
        src = Path(src).resolve()
        man = json.loads((src / 'manifest.json').read_text())
        head = (man['schema'], man['input_dim'], man.get('enc_version', 2))
        if head[0] != 'shengji-policy-rows-chunked-v1' or (heads and head != heads[0]):
            raise ValueError('policy row schema/encoder mismatch')
        heads.append(head)
        if man.get('explore_tags') is not True or man.get('explore_flag_names') != names:
            raise ValueError(f'source lacks complete exploration tags: {src}')
        if man.get('values_scale') not in (None, 'points'):
            raise ValueError('policy values must use points scale')
        counts = _counts(man.get('explore_flag_counts'), man['rows'])
        actual = {k: 0 for k in totals}
        nrows = 0
        if not man['chunks']:
            raise ValueError('source has no chunks')
        for chunk in man['chunks']:
            filename = chunk['file']
            if Path(filename).name != filename or filename in ('.', '..'):
                raise ValueError('chunk must be a basename')
            target = (src / filename).resolve(strict=True)
            if target in targets:
                raise ValueError('duplicate source chunk')
            targets.add(target)
            output_name = f'{tag}-{filename}'
            if output_name in output_names:
                raise ValueError('composed chunk names collide')
            output_names.add(output_name)
            with zipfile.ZipFile(target) as archive:
                if not {'explore_flag.npy', 'explore_margin.npy'} <= set(archive.namelist()):
                    raise ValueError(f'chunk lacks exploration arrays: {target}')
            for key, count in _counts(chunk.get('explore_flag_counts'), chunk['rows']).items():
                actual[key] += count
            nrows += chunk['rows']
            chunks.append((dict(chunk, file=output_name, source=str(src)), target))
        if actual != counts or nrows != man['rows']:
            raise ValueError('source/chunk exploration counts disagree')
        for key in totals:
            totals[key] += counts[key]
        rows += nrows
        deals += int(man.get('deals', 0))
        sources.append({'tag': tag, 'dir': str(src)})
        corpora.extend(man.get('corpora', []))
    schema, dim, version = heads[0]
    manifest = dict(schema=schema, input_dim=dim, enc_version=version,
                    rows=rows, deals=deals, composed_from=sources, corpora=corpora,
                    deal_key_schema='shengji-value-deal-key-v1',
                    chunks=[entry for entry, _ in chunks], explore_tags=True,
                    explore_flag_names=names, explore_flag_counts=totals)
    # composed_from preserves the source scale declarations for the consumer's
    # recursive scale guard; do not relabel unspecified legacy values as points.
    out.mkdir(parents=True)
    for entry, target in chunks:
        (out / entry['file']).symlink_to(target)
    with (out / 'manifest.json').open('x') as stream:
        stream.write(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--part', nargs=2, action='append', required=True,
                        metavar=('TAG', 'DIRECTORY'))
    args = parser.parse_args(argv)
    result = compose(args.out, [(tag, Path(path)) for tag, path in args.part])
    print(json.dumps({k: result[k] for k in ('rows', 'explore_tags', 'explore_flag_counts')}))


if __name__ == '__main__':
    main()
