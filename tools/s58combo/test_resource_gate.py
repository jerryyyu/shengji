import pytest
from resource_gate import check_resources, RESERVE_BYTES, MAX_FILE_BYTES


def seals(size):
    return {'window': {'files': {'cluster.json': {'size': size}}}}


def test_memory_boundary():
    need = RESERVE_BYTES + 16 * 100
    assert check_resources(seals(100), available=need)['required_memory_bytes'] == need
    with pytest.raises(ValueError, match='memory'):
        check_resources(seals(100), available=need - 1)


@pytest.mark.parametrize('size', [-1, True, 1.5, MAX_FILE_BYTES + 1])
def test_malformed_or_oversized_file_refused(size):
    with pytest.raises(ValueError):
        check_resources(seals(size), available=128 * 1024**3)


def test_aggregate_refused():
    big = {'window': {'files': {str(i): {'size': MAX_FILE_BYTES} for i in range(385)}}}
    with pytest.raises(ValueError, match='aggregate'):
        check_resources(big, available=128 * 1024**3)
