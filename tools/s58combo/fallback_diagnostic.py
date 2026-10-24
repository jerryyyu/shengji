"""One separately authorized, outcome-free projection of sealed fallback receipts."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from decision_gate import _cause_label
from launcher import _sha, packet_digest
from sealed_input import _bound_json, load_inputs


def project(shards):
    counts = {'decisions': 0, 'play_fallback': 0}
    causes = {}
    overflow = 0
    for shard in shards:
        for trace in shard['decision_traces']:
            if trace['side'] != 'arm':
                continue
            for rec in trace['decisions']:
                counts['decisions'] += 1
                if rec['schema'] == 'pv-search-fallback-v1':
                    counts['play_fallback'] += 1
                    key = tuple(_cause_label(rec.get(k)) for k in ('reason', 'error_class', 'error_stage'))
                    if key in causes or len(causes) < 32:
                        causes[key] = causes.get(key, 0) + 1
                    else:
                        overflow += 1
                elif rec['schema'] != 'pv-search-decision-v1':
                    raise ValueError('unknown decision schema')
    return dict(counts=counts, causes=[dict(reason=k[0], error_class=k[1],
                error_stage=k[2], count=v) for k, v in sorted(causes.items())], overflow=overflow)


def diagnose(*, source_head, reader_sha, root, terminal_sha, plan_path, expected_path, saved_sha):
    reader = Path(__file__).resolve()
    source = reader.parents[2]
    if (_sha(reader) != reader_sha or subprocess.check_output(
            ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != source_head
            or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain',
                                        '--untracked-files=no'], text=True)):
        raise ValueError('diagnostic source drift')
    root = Path(root)
    saved = _bound_json(root / 'readout.json', saved_sha)
    if saved['status'] != 'DECISION_INVALID' or saved['terminal_sha256'] != terminal_sha:
        raise ValueError('not the named invalid readout')
    consumed = json.loads((root / 'READOUT_CONSUMED.json').read_text())
    if consumed['terminal_sha256'] != terminal_sha or consumed['reader_sha256'] != saved['reader_sha256']:
        raise ValueError('original consumption binding drift')
    plan, expected = (json.loads(Path(p).read_text()) for p in (plan_path, expected_path))
    if packet_digest(plan, expected) != saved['packet_sha256']:
        raise ValueError('saved packet drift')
    load_inputs(plan, expected, root=root, terminal_sha=terminal_sha,
                reader_path=reader, reader_sha=reader_sha, owner='codex',
                preflight_only=True, streaming=True)
    terminal = _bound_json(root / 'terminal.json', terminal_sha)
    targets = {}
    for item in terminal['results']:
        target = Path(item['output'])
        targets[item['output']] = _bound_json(root / 'seals' / (target.name + '.json'), item['seal_sha256'])
    result_path = root / 'fallback-diagnostic.json'
    with result_path.open('x') as stream:
        json.dump({'status': 'READING', 'source_head': source_head}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    def shards(arm):
        for window in plan['windows']:
            if window['side'] != arm:
                continue
            for i in range(520):
                if (root / 'READOUT_HOLD').exists():
                    raise ValueError('readout HOLD appeared')
                name = f'cluster-{i:05}.json'
                path = Path(window['output']) / name
                pin = targets[window['output']]['files'][name]
                if path.stat().st_size != pin['size']:
                    raise ValueError('shard size drift')
                yield _bound_json(path, pin['sha256'])
    try:
        arms = {arm: project(shards(arm)) for arm in ('candidate', 'comparator')}
        for arm, data in arms.items():
            if any(value != saved['decision_check']['counts'][arm][key]
                   for key, value in data['counts'].items()):
                raise ValueError('counts disagree with saved verdict')
        result = dict(status='DIAGNOSTIC_COMPLETE', arms=arms)
    except Exception as exc:
        result = dict(status='DIAGNOSTIC_FAILED', error_class=type(exc).__name__)
    result.update(source_head=source_head, reader_sha=reader_sha, terminal_sha=terminal_sha, saved_sha=saved_sha)
    pending = root / 'fallback-diagnostic.pending'
    with pending.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, result_path)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source-head', 'reader-sha', 'root', 'terminal-sha', 'plan-path', 'expected-path', 'saved-sha'):
        parser.add_argument('--' + key, required=True)
    result = diagnose(**vars(parser.parse_args()))
    print(json.dumps({'status': result['status']}))
    raise SystemExit(result['status'] != 'DIAGNOSTIC_COMPLETE')
