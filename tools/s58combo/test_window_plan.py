"""Queue wiring tests with synthetic seeds; no game or experiment dispatch."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from window_plan import queue_windows, FIRST_WINDOWS, RANKS


ARMS = [{'name': 'candidate'}, {'name': 'comparator'}]
SEEDS = [i * 1000 for i in range(10)]


def test_plan_reaches_real_queue_command_builder(tmp_path, monkeypatch):
    from shengji.train import cwv_screen_queue as queue

    seen = []
    # A nonzero producer response stops before any completion/readout checks.
    def capture(argv):
        seen.append(dict(zip(argv[::2], argv[1::2], strict=True)))
        return 77
    monkeypatch.setattr(queue.screen, 'main', capture)
    windows = queue_windows(ARMS, SEEDS, tmp_path)
    assert len(windows) == 20 and len({w['output'] for w in windows}) == 20
    for window in windows:
        assert queue.main(window['argv']) == 77
    assert len(seen) == 20
    for i, (window, command) in enumerate(zip(windows, seen, strict=True)):
        first = i % 10 in FIRST_WINDOWS
        assert command['--arm-policy'] == ARMS[i // 10]['name']
        assert command['--seed0'] == str(SEEDS[i % 10])
        assert command['--trump-ranks'] == ('2' if first else RANKS)
        assert command.get('--round-kind', 'first') == window['round_kind']
        assert command['--out'] == window['output']
        assert command['--clusters'] == '520' and command['--workers'] == '14'
        assert command['--decision-deadline'] == '300'
        assert command['--baseline'] == 'production'


@pytest.mark.parametrize('seeds', [SEEDS[:-1], [0] * 10, [i * 519 for i in range(10)],
                                  [-1, *SEEDS[1:]], [True, *SEEDS[1:]]])
def test_invalid_schedule_refuses(seeds, tmp_path):
    with pytest.raises(ValueError):
        queue_windows(ARMS, seeds, tmp_path)


@pytest.mark.parametrize('workers', [0, 15, True])
def test_invalid_worker_cap_refuses(workers, tmp_path):
    with pytest.raises(ValueError):
        queue_windows(ARMS, SEEDS, tmp_path, workers=workers)
