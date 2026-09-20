from scripts.cwv_puct_probe_states import snapshots
from shengji.luna.game import _round_from_snapshot


def test_probe_states_are_deterministic_replayable_and_span_phases():
    rows = snapshots(seeds=(19,))
    assert rows == snapshots(seeds=(19,))
    assert len(rows) == 4
    states = [_round_from_snapshot(row) for row in rows]
    assert all(state.phase == "play" for state in states)
    sizes = [max(map(len, state.hands)) for state in states]
    assert sizes[0] == 25
    assert all(size <= limit for size, limit in zip(sizes, (25, 12, 6, 3)))
    assert sizes == sorted(sizes, reverse=True)
