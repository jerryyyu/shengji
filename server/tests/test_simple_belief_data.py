from copy import deepcopy
import json
import random

import numpy as np
import pytest

from shengji.engine.round import Round
from shengji.harvest.rebuild import setup_from_round
from shengji.train import simple_belief_data as data


def record(seed=4):
    rnd = Round('2', 0, random.Random(seed))
    deck = list(rnd.deck)
    while rnd.phase == 'deal':
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(0, list(rnd.hands[0][:8]))
    return {'decision_kind': 'play', 'deck': deck, 'setup': setup_from_round(rnd),
            'seat': 0, 'plays_prefix': []}


def test_reconstruction_ignores_outcome_action_and_hidden_cache():
    r = record()
    changed = {**r, 'outcome': {'win': 12345}, 'action': ['not a card'],
               'round_seed': -999, 'hidden_hands': 'poison', 'value': float('nan')}
    assert set(data.reconstruction_record(changed)) == set(data.REPLAY_FIELDS)
    for a, b in zip(data.encode_record(r), data.encode_record(changed)):
        np.testing.assert_array_equal(a, b)
    with pytest.raises(ValueError, match='original deck'):
        data.encode_record({**r, 'deck': None})
    with pytest.raises(ValueError, match='actor turn differs'):
        data.encode_record({**r, 'seat': 1})


def test_dedup_ignores_labels_and_split_is_per_original_deal():
    r = record()
    rows = data.select_records([r, {**r, 'outcome': 'win'}, {**r, 'outcome': 'loss'}], 16)
    assert len(rows) == 1
    other = deepcopy(r)
    other['setup']['buried'].reverse()
    assert len(data.select_records([r, other], 16)) == 1
    key = data.record_deal_key(r)
    assert data.deal_split(key) == data.deal_split(data.record_deal_key(other))
    assert {data.deal_split(f'deck:{i}') for i in range(100)} == {'train', 'dev', 'check'}


def fixture_cache_source(tmp_path, duplicate=True):
    r = record()
    key = data.record_deal_key(r)
    sources = {}
    for name in (['runA', 'runC'] if duplicate else ['runA']):
        source = tmp_path / name
        source.mkdir()
        raw = data.canonical(r) + b'\n'
        (source / 'rows.jsonl').write_bytes(raw)
        manifest = {'source': 'trajectory', 'shards': [
            {'path': 'rows.jsonl', 'sha256': data.digest(raw), 'bytes': len(raw), 'records': 1}]}
        m = data.canonical(manifest)
        (source / 'manifest.json').write_bytes(m)
        sources[name] = {'manifest_sha256': data.digest(m), 'fit_deal_keys': [key]}
    c = {'schema': 'cwv-fit-subset-v1', 'baseline_val_test_included': 0,
         'baseline_checkpoint_sha256': 'a'*64, 'sources': sources, 'distinct_deals': 1}
    (tmp_path / 'curation.json').write_bytes(data.canonical(c))
    return c


def test_global_source_dedup_and_eligibility_refusal(tmp_path):
    c = fixture_cache_source(tmp_path)
    grouped, provenance, _ = data.load_fit_records(tmp_path)
    assert len(grouped) == 1 and len(next(iter(provenance.values()))) == 2
    assert len(data.select_records(next(iter(grouped.values())), 16)) == 1
    c['sources']['runC']['fit_deal_keys'] = []
    (tmp_path / 'curation.json').write_bytes(data.canonical(c))
    with pytest.raises(ValueError, match='fit eligibility'):
        data.load_fit_records(tmp_path)


def test_cache_reuses_complete_deals_and_witnesses_real_wiring(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    fixture_cache_source(source)
    out = tmp_path / 'out'
    result = data.build_cache(source, out, positions=4, workers=1)
    assert result['completed_deals'] == result['rows'] == 1
    recipe = json.loads((out / 'recipe.json').read_bytes())
    entry = recipe['deals'][0]
    path = out / entry['path']
    with np.load(path) as saved:
        assert saved['x'].shape == (1, 776)
        assert saved['allowed'].shape == (1, 4, 54, 3)
        assert np.take_along_axis(saved['allowed'], saved['targets'][..., None], -1).all()
    before = path.stat().st_mtime_ns
    def forbidden(*args):
        raise AssertionError('completed deal reconstructed')
    monkeypatch.setattr(data, 'encode_record', forbidden)
    assert data._cache_deal((entry['deal_key'], [None], str(path), entry['identity']))[2]
    assert path.stat().st_mtime_ns == before
    with pytest.raises(ValueError, match='different producing inputs'):
        data._cache_deal((entry['deal_key'], [None], str(path), 'wrong'))
