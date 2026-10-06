import hashlib
import json

import pytest

from shengji.eval.s11_shard import mirror_play_rows


def rows():
    return [dict(source_ref=f"run:7:{m}:{p % 4}:{p}", decision_kind="play",
                 seat=p % 4, ply=p, round_seed=107, action_values=None,
                 outcome={"ignored": p})
            for m in (0, 1) for p in (0, 4, 1, 5, 2, 3)]


def read(records, mirror=0):
    raw = b"\n".join(json.dumps(r).encode() for r in records) + b"\n"
    return mirror_play_rows(raw, sha256=hashlib.sha256(raw).hexdigest(),
                            record_count=len(records), run_id="run",
                            cluster=7, seed=107, mirror=mirror)


@pytest.mark.parametrize("mirror", [0, 1])
def test_restores_chronology_without_label_or_opportunity_filter(mirror):
    records = rows()
    records.append(dict(source_ref=f"run:7:{mirror}:0:bury", decision_kind="bury",
                        seat=0, ply=None, round_seed=107, plays_prefix=[]))
    selected = read(records, mirror)
    assert [r["ply"] for r in selected] == list(range(6))
    assert selected == read(records[::-1], mirror)
    assert len(records) == 13


def test_wrong_digest_refuses_before_json_parse():
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        mirror_play_rows(b"not json", sha256="a" * 64, record_count=1,
                         run_id="run", cluster=7, seed=107, mirror=0)


@pytest.mark.parametrize("mutation", [
    lambda r: r.append(r[0]),
    lambda r: r.pop(0),
    lambda r: r.__delitem__(slice(6, None)),
    lambda r: r[0].update(source_ref="run:8:0:0:0"),
    lambda r: r[0].update(round_seed=108),
    lambda r: r[0].update(seat=True),
    lambda r: r[0].update(ply=False),
    lambda r: r[0].update(decision_kind="other"),
    lambda r: r[0].update(decision_kind="bury"),
])
def test_malformed_frame_refuses_without_fallback(mutation):
    records = rows()
    mutation(records)
    with pytest.raises(ValueError):
        read(records)


@pytest.mark.parametrize("raw,count", [(b'{"a":1,"a":2}', 1),
                                      (b'{"a":NaN}', 1),
                                      (b'{}\n\n', 2), (b'{}', 2)])
def test_ambiguous_json_or_count_refuses(raw, count):
    with pytest.raises(ValueError):
        mirror_play_rows(raw, sha256=hashlib.sha256(raw).hexdigest(),
                         record_count=count, run_id="run", cluster=7, seed=107, mirror=0)
