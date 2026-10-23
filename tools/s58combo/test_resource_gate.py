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


def test_streaming_uses_largest_file_and_requires_spool_disk(tmp_path, monkeypatch):
    import resource_gate
    from types import SimpleNamespace
    sizes = {'w': {'files': {str(i): {'size': 1024**2} for i in range(4000)}}}
    monkeypatch.setattr(resource_gate.shutil, 'disk_usage',
                        lambda root: SimpleNamespace(free=16 * 1024**3))
    assert check_resources(sizes, available=3 * 1024**3, streaming=True,
                           root=tmp_path)['required_memory_bytes'] < 3 * 1024**3
    with pytest.raises(ValueError, match='memory'):
        check_resources(sizes, available=3 * 1024**3)
    monkeypatch.setattr(resource_gate.shutil, 'disk_usage', lambda root: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match='disk'):
        check_resources(sizes, available=3 * 1024**3, streaming=True, root=tmp_path)
