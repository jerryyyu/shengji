"""Synthetic qualification of the complete scheduled input boundary; no corpus IO."""
import copy
import hashlib
import json

import pytest

from shengji.engine.cards import card_suit
from shengji.engine.round import actual_play_after
from shengji.eval.s11_manifest import select_manifest_shards
from shengji.eval.s11_selection import select_ply
from shengji.eval.s11_shard import mirror_play_rows
from shengji.eval.s11_reconstruction import reconstruct_s11_trajectory
from shengji.eval.s11_public_view import public_s11_fixture
from shengji.harvest.legal import enumerate_legal
from shengji.harvest.rebuild import deck_from_seed, round_from_setup
from shengji.harvest.trajectory import build_run_manifest


def _rows(seed, cluster, mirror):
    deck = deck_from_seed('2', mirror, seed)
    suit = next(card_suit(c) for c in deck[-8:] if card_suit(c))
    setup = dict(trump_rank='2', banker=mirror, declarations=[],
                 trump_suit=suit, trump_is_nt=False, buried=deck[-8:])
    rnd = round_from_setup(deck, setup)
    rows, prefix = [], []
    for ply in range(100):
        seat = rnd.turn
        action = enumerate_legal(rnd, seat, cap=1).actions[0]
        previous = rnd.last_trick
        rnd.play(seat, action)
        actual = actual_play_after(rnd, seat, previous)
        rows.append(dict(source_ref=f'join:{cluster}:{mirror}:{seat}:{ply}',
                         round_seed=seed, deck=list(deck), setup=copy.deepcopy(setup),
                         seat=seat, ply=ply, decision_kind='play', action=list(action),
                         engine_play=actual, plays_prefix=copy.deepcopy(prefix)))
        prefix.append(dict(seat=seat, cards=actual))
    assert rnd.phase == 'round_end'
    # Native storage order is by seat, not by chronology.
    return sorted(rows, key=lambda row: (row['seat'], row['ply']))


def test_full_manifest_to_scheduled_public_fixture(tmp_path):
    (tmp_path / 'shards').mkdir()
    shards, sidecars = {}, {}
    for cluster in range(64):
        seed = 9000 + cluster
        rows = _rows(seed, cluster, 0) + _rows(seed, cluster, 1)
        raw = b''.join(json.dumps(row).encode() + b'\n' for row in rows)
        shards[cluster] = raw
        (tmp_path / 'shards' / f'cluster-{cluster:06d}.json').write_text('{}')
        sidecars[cluster] = dict(seed=seed, path=f'shards/cluster-{cluster:06d}.jsonl',
                                 sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                                 records=len(rows), counts={'rounds': 2}, work={})
    manifest = build_run_manifest(dict(run_id='join', seed0=9000, round_mix='first'),
                                  {}, rounds=128, sidecars=sidecars,
                                  merged=None, out_dir=tmp_path)
    raw_manifest = json.dumps(manifest).encode()
    pin = hashlib.sha256(raw_manifest).hexdigest()
    schedule = select_manifest_shards(raw_manifest, sha256=pin)
    completed = []
    for item in schedule:
        raw = shards[item.cluster]
        assert len(raw) == item.byte_count
        rows = mirror_play_rows(raw, sha256=item.sha256, record_count=item.record_count,
                                run_id=item.run_id, cluster=item.cluster,
                                seed=item.seed, mirror=item.mirror)
        # Establish terminal completeness before the position draw. This test
        # repeats replay for clarity; it does not prescribe collector caching.
        reconstruct_s11_trajectory(rows, 0)
        ply = select_ply(pin, item.seed, item.mirror, len(rows))
        fixture = public_s11_fixture(rows, ply, root_id=f'draw-{item.draw_index}')
        assert fixture.seat == rows[ply]['seat']
        assert fixture.setup['declarations'] == []
        assert len(fixture.plays) == ply
        assert fixture.setup['buried'] is None or fixture.seat == item.mirror
        assert all(key not in fixture.to_json() for key in ('deck', 'round_seed', 'hands'))
        completed.append(item.draw_index)
    assert completed == list(range(64))
    first = schedule[0]
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        mirror_play_rows(shards[first.cluster] + b' ', sha256=first.sha256,
                         record_count=first.record_count, run_id=first.run_id,
                         cluster=first.cluster, seed=first.seed, mirror=first.mirror)
