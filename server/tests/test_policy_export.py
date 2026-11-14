"""A composed policy cache exports without runtime dependencies on its source."""
import json

import pytest

from scripts.compose_policy_rows import compose
from scripts.export_policy_rows import export
from shengji.train.policy_rows import PolicyRowsStream
from test_policy_rows_served import (pv_package, pv_store, served_store, produced,
                                     _canonical_rows)  # noqa: F401


def test_nested_export_reopens_after_sources_move(produced, tmp_path):
    leaf, summary, _, _ = produced
    first = tmp_path / 'first'
    composed = tmp_path / 'composed'
    compose(first, [('leaf', leaf)])
    compose(composed, [('first', first)])
    expected = _canonical_rows(composed)
    dest = tmp_path / 'portable'
    receipt = export(composed, dest, version=2)
    assert receipt['rows'] == summary['rows']
    man = json.loads((dest / 'manifest.json').read_text())
    assert 'composed_from' not in man and man['values_scale'] == 'points'
    assert len(man['exported_from']['source_manifest_sha256s']) == 3
    source_man = json.loads((composed / 'manifest.json').read_text())
    for c in man['chunks']:
        assert not (dest / c['file']).is_symlink()
        assert (dest / c['file']).read_bytes() == (composed / c['file']).read_bytes()
    assert [c['sha256'] for c in man['chunks']] == [c['sha256'] for c in source_man['chunks']]
    moved = leaf.with_name(leaf.name + '-unavailable')
    leaf.rename(moved)
    first.rename(tmp_path / 'first-unavailable')
    composed.rename(tmp_path / 'composed-unavailable')
    try:
        relocated = tmp_path / 'relocated'
        dest.rename(relocated)
        assert _canonical_rows(relocated) == expected
        assert PolicyRowsStream(relocated, version=2).n == receipt['rows']
    finally:
        moved.rename(leaf)


def test_export_refuses_overlap_existing_and_unverified_scale(produced, tmp_path):
    leaf, _, _, _ = produced
    with pytest.raises(ValueError, match='overlaps'):
        export(leaf, leaf / 'nested', version=2)
    existing = tmp_path / 'existing'; existing.mkdir()
    with pytest.raises(ValueError, match='exists'):
        export(leaf, existing, version=2)
    link = tmp_path / 'alias'; link.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match='exists'):
        export(leaf, link, version=2)
    composed = tmp_path / 'bad'; compose(composed, [('leaf', leaf)])
    mpath = composed / 'manifest.json'
    man = json.loads(mpath.read_text()); man['values_scale'] = 'levels'
    mpath.write_text(json.dumps(man))
    with pytest.raises(ValueError, match='only.*points'):
        export(composed, tmp_path / 'rejected', version=2)
    assert not (tmp_path / 'rejected').exists()


def test_source_change_during_copy_leaves_no_complete_manifest(produced, tmp_path, monkeypatch):
    from scripts import export_policy_rows as module
    leaf, _, _, _ = produced
    man = json.loads((leaf / 'manifest.json').read_text())
    chunk = leaf / man['chunks'][0]['file']
    original = chunk.read_bytes()
    real = module.PolicyRowsStream

    def changed_after_validation(*args, **kwargs):
        stream = real(*args, **kwargs)
        chunk.write_bytes(original + b'changed')
        return stream

    monkeypatch.setattr(module, 'PolicyRowsStream', changed_after_validation)
    dest = tmp_path / 'incomplete'
    try:
        with pytest.raises(ValueError, match='changed while copying'):
            export(leaf, dest, version=2)
        assert not (dest / 'manifest.json').exists()
        assert list(dest.glob('*.tmp'))
    finally:
        chunk.write_bytes(original)
