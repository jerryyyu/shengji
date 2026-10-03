"""Reuse within one identity call, never stale process-wide memoization."""
import pytest
from shengji.train import cwv_data


@pytest.mark.parametrize('version', [1, 2, 4, 5, 6])
def test_public_identity_computed_once_and_refreshed(monkeypatch, version):
    before = cwv_data.cwv_encoder_identity(version)
    original = cwv_data.public_encoder_identity
    calls = []
    def observed(v):
        calls.append(v)
        return original(v)
    monkeypatch.setattr(cwv_data, 'public_encoder_identity', observed)
    assert cwv_data.cwv_encoder_identity(version) == before
    assert calls == [version]
    assert cwv_data.cwv_encoder_identity(version) == before
    assert calls == [version, version]


def test_changed_public_identity_is_not_cached(monkeypatch):
    original = cwv_data.public_encoder_identity
    value = original(2)
    monkeypatch.setattr(cwv_data, 'public_encoder_identity', lambda _: value)
    first = cwv_data.cwv_encoder_identity(2)
    value = {**value, 'implementation_sha256':'changed',
             'transitive':{'implementation_sha256':'changed-contract'}}
    second = cwv_data.cwv_encoder_identity(2)
    assert first['public_head_encoder_sha256'] != second['public_head_encoder_sha256']
    assert second['public_head_encoder_contract_sha256'] == 'changed-contract'
