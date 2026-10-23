import json
from pathlib import Path
import pytest
import launcher
from test_launcher import packet, bound_source, release, runner
from sealed_input import load_inputs


@pytest.fixture
def completed(tmp_path):
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
