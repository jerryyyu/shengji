"""Read a reviewed, released terminal once; never infer authority from output."""
import hashlib
import json
from pathlib import Path

from launcher import packet_digest


def _bound_json(path, sha):
    if not path.is_file() or path.is_symlink():
        raise ValueError('missing or symlinked sealed file')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError('sealed bytes changed')
    return json.loads(data)


def load_inputs(plan, expected, *, root, terminal_sha, reader_path, reader_sha, owner):
    """Caller supplies independently reviewed terminal and reader pins.

    No CLI is exposed. A future reviewed readout entrypoint must establish its
    named authority before calling; neither these arguments nor HOLD removal
    grant authority. A consumed marker deliberately survives any failure.
    """
    root, reader_path = Path(root), Path(reader_path)
    if owner != 'codex' or not reader_path.is_absolute() or reader_path.is_symlink():
        raise ValueError('unexpected reader ownership or path')
    if hashlib.sha256(reader_path.read_bytes()).hexdigest() != reader_sha:
        raise ValueError('reader source changed')
    if root.is_symlink() or (root / 'READOUT_HOLD').exists():
        raise ValueError('readout HOLD or aliased root')
    terminal = _bound_json(root / 'terminal.json', terminal_sha)
    if terminal.get('status') != 'LANE_DONE' or terminal.get('packet_sha256') != packet_digest(plan, expected):
        raise ValueError('wrong terminal or packet')
    reservation = _bound_json(root / 'reservation.json', terminal['reservation_sha256'])
    if reservation.get('packet_sha256') != terminal['packet_sha256']:
        raise ValueError('reservation mismatch')
    outputs = [w['output'] for w in plan['windows']]
    results = terminal.get('results', [])
    if len(outputs) != 20 or len(set(outputs)) != 20 or [r.get('output') for r in results] != outputs:
        raise ValueError('terminal window inventory mismatch')
    seals = {}
    names = {'config.json', 'summary.json'} | {f'cluster-{i:05}.json' for i in range(520)}
    for result in results:
        target = Path(result['output'])
        if target.parent.resolve() != root.resolve() or target.is_symlink() or result.get('returncode') != 0:
            raise ValueError('wrong window path or unsuccessful window')
        if (root / 'seals').is_symlink():
            raise ValueError('aliased seals directory')
        seal = _bound_json(root / 'seals' / f'{target.name}.json', result['seal_sha256'])
        if (seal.get('schema') != 's58combo-window-seal-v1' or seal.get('output') != str(target.resolve())
                or set(seal.get('files', {})) != names):
            raise ValueError('seal inventory mismatch')
        actual = {p.name for p in target.iterdir()}
        if actual - {'.screen.lock'} != names:
            raise ValueError('output inventory mismatch')
        seals[result['output']] = seal
    # Exclusive claim precedes the first scientific shard read.
    with (root / 'READOUT_CONSUMED.json').open('x') as stream:
        json.dump(dict(owner=owner, reader=str(reader_path), reader_sha256=reader_sha,
                       terminal_sha256=terminal_sha), stream)
    configs, shards = {}, {}
    for output, seal in seals.items():
        target = Path(output)
        values = {}
        for name, pin in seal['files'].items():
            path = target / name
            if (root / 'READOUT_HOLD').exists():
                raise ValueError('readout HOLD appeared')
            if path.stat().st_size != pin['size']:
                raise ValueError('sealed file size changed')
            values[name] = _bound_json(path, pin['sha256'])
        configs[output] = values['config.json']
        if configs[output] != expected[output]:
            raise ValueError('sealed config mismatch')
        shards[output] = [values[f'cluster-{i:05}.json'] for i in range(520)]
    return configs, shards


def sealed_outcome_checked_result(plan, expected, **pins):
    """Feed only hash-bound inputs to the existing scientific validity gates."""
    from outcome_gate import outcome_checked_result
    configs, shards = load_inputs(plan, expected, **pins)
    result = outcome_checked_result(plan, expected, configs, shards)
    if 'pending' in result:
        result['pending'] = [item for item in result['pending'] if item != 'sealed input binding']
    result['terminal_sha256'] = pins['terminal_sha']
    return result
