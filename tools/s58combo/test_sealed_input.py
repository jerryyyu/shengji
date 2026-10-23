import json
from pathlib import Path
import pytest
import launcher
from test_launcher import packet, bound_source, release, runner
from sealed_input import load_inputs


@pytest.fixture
def completed(tmp_path, monkeypatch):
    import resource_gate
    monkeypatch.setattr(resource_gate, "available_memory", lambda: 128 * 1024**3)
    plan, expected = packet(tmp_path)
    file = Path(launcher.__file__)
    launch, token = release(tmp_path, plan, expected, file)
    args = runner()
    args = (*args[:-1], args[-1].replace(".close() for i", ".write('{}') for i"))
    root = tmp_path / 'out'
    launcher.run_plan(plan, expected, source=bound_source(tmp_path, plan), output=root,
                      release=token, launcher=launch, host_lock=tmp_path / 'lock',
                      runner=args, runner_file=file)
    pins = dict(root=root, terminal_sha=launcher._sha(root / 'terminal.json'),
                reader_path=Path(__file__).resolve(), reader_sha=launcher._sha(Path(__file__)), owner='codex')
    return plan, expected, pins


def test_producer_seals_consumer_reads_once(completed):
    plan, expected, pins = completed
    with pytest.raises(ValueError, match='HOLD'):
        load_inputs(plan, expected, **pins)
    assert not (pins['root'] / 'READOUT_CONSUMED.json').exists()
    (pins['root'] / 'READOUT_HOLD').unlink()
    configs, shards = load_inputs(plan, expected, **pins)
    assert configs == expected and sum(map(len, shards.values())) == 10400
    with pytest.raises(FileExistsError): load_inputs(plan, expected, **pins)


@pytest.mark.parametrize('defect', ['terminal', 'reservation', 'seal', 'shard', 'reader', 'owner'])
def test_tamper_refused(completed, defect):
    plan, expected, pins = completed
    root = pins['root']; (root / 'READOUT_HOLD').unlink()
    target = Path(plan['windows'][0]['output'])
    if defect == 'reader': pins['reader_sha'] = '0' * 64
    elif defect == 'owner': pins['owner'] = 'someone-else'
    else:
        path = {'terminal': root / 'terminal.json', 'reservation': root / 'reservation.json',
                'seal': root / 'seals' / f'{target.name}.json', 'shard': target / 'cluster-00000.json'}[defect]
        path.write_text('{} ')
    with pytest.raises(ValueError): load_inputs(plan, expected, **pins)
    assert (root / 'READOUT_CONSUMED.json').exists() == (defect == 'shard')


def test_sealed_loader_feeds_existing_scientific_consumer(completed, monkeypatch):
    import outcome_gate
    from sealed_input import sealed_outcome_checked_result
    plan, expected, pins = completed
    (pins['root'] / 'READOUT_HOLD').unlink()
    seen = []
    def consumer(p, e, configs, shards):
        assert p == plan and e == expected and configs == expected
        seen.append(sum(map(len, shards.values())))
        return dict(status='STAGE_OUTCOME_CHECKED_ONLY', pending=['sealed input binding', 'scientific review'])
    monkeypatch.setattr(outcome_gate, 'outcome_checked_result', consumer)
    result = sealed_outcome_checked_result(plan, expected, **pins)
    assert seen == [10400] and result['pending'] == ['scientific review']


def test_unused_summary_is_hash_checked_as_opaque_bytes(completed):
    plan, expected, pins = completed
    root = pins['root']
    (root / 'READOUT_HOLD').unlink()
    target = Path(plan['windows'][0]['output'])
    (target / 'summary.json').write_bytes(b'opaque producer summary')
    seal = root / 'seals' / (target.name + '.json')
    contents = json.loads(seal.read_text())
    contents['files']['summary.json'] = dict(
        sha256=launcher._sha(target / 'summary.json'),
        size=(target / 'summary.json').stat().st_size)
    seal.write_text(json.dumps(contents))
    terminal_path = root / 'terminal.json'
    terminal = json.loads(terminal_path.read_text())
    terminal['results'][0]['seal_sha256'] = launcher._sha(seal)
    terminal_path.write_text(json.dumps(terminal))
    pins['terminal_sha'] = launcher._sha(terminal_path)
    configs, shards = load_inputs(plan, expected, **pins)
    assert configs == expected and sum(map(len, shards.values())) == 10400


def test_resource_refusal_preserves_one_shot(completed, monkeypatch):
    import resource_gate
    plan, expected, pins = completed
    (pins['root'] / 'READOUT_HOLD').unlink()
    monkeypatch.setattr(resource_gate, 'available_memory', lambda: 0)
    with pytest.raises(ValueError, match='memory'):
        load_inputs(plan, expected, **pins)
    assert not (pins['root'] / 'READOUT_CONSUMED.json').exists()


def test_sealed_valid_result_final_transition(completed, monkeypatch):
    import outcome_gate
    from sealed_input import sealed_outcome_checked_result
    plan, expected, pins = completed
    (pins['root'] / 'READOUT_HOLD').unlink()
    monkeypatch.setattr(outcome_gate, 'outcome_checked_result', lambda *args: dict(
        status='STAGE_OUTCOME_CHECKED_ONLY', pending=['sealed input binding',
        'final recipe telemetry and full reader battery review'], estimate={'synthetic': True}))
    result = sealed_outcome_checked_result(plan, expected, **pins)
    assert result['status'] == 'SCREEN_VALID' and 'pending' not in result


def test_streaming_reads_each_producer_shard_only_once(completed, monkeypatch):
    import sealed_input
    plan, expected, pins = completed
    (pins['root'] / 'READOUT_HOLD').unlink()
    reads = {}
    original = sealed_input._bound_bytes
    def counted(path, sha):
        if path.name.startswith('cluster-'):
            reads[str(path)] = reads.get(str(path), 0) + 1
        return original(path, sha)
    monkeypatch.setattr(sealed_input, '_bound_bytes', counted)
    configs, spool = load_inputs(plan, expected, **pins, streaming=True)
    try:
        assert configs == expected
        for _ in range(2):
            assert sum(sum(1 for shard in spool[key]) for key in spool) == 10400
        assert len(reads) == 10400 and set(reads.values()) == {1}
    finally:
        spool.close()
    assert not spool.directory.exists()


@pytest.mark.parametrize('failure', [False, True])
def test_streaming_cache_cleanup_after_consumer(completed, monkeypatch, failure):
    import outcome_gate
    from sealed_input import sealed_outcome_checked_result
    plan, expected, pins = completed
    (pins['root'] / 'READOUT_HOLD').unlink()
    def consume(*args):
        assert list(pins['root'].glob('s58-shards-*'))
        if failure:
            raise ValueError('synthetic gate failure')
        return dict(status='OUTCOME_INVALID')
    monkeypatch.setattr(outcome_gate, 'outcome_checked_result', consume)
    if failure:
        with pytest.raises(ValueError, match='gate'):
            sealed_outcome_checked_result(plan, expected, **pins, streaming=True)
    else:
        assert sealed_outcome_checked_result(plan, expected, **pins, streaming=True)['status'] == 'OUTCOME_INVALID'
    assert not list(pins['root'].glob('s58-shards-*'))
