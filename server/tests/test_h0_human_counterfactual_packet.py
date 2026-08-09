from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "h0_human_counterfactual_packet.py"
SPEC = importlib.util.spec_from_file_location("h0_packet", SCRIPT)
assert SPEC and SPEC.loader
h0 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h0)


def _play(player: str, source: str, round_: int, event: int, *, trick: int,
          surface: str = "follow", role: str = "attacker",
          off: bool = False) -> dict:
    return {
        "source": source,
        "round": round_,
        "event_index": event,
        "seat": event % 4,
        "player_id": player,
        "role": role,
        "surface": surface,
        "trick": trick,
        "cards_remaining": max(0, 104 - 4 * trick),
        "chosen": ["H5"] if off else ["H3"],
        "candidate_count": 2,
        "human_action_appended": off,
    }


def test_components_are_player_and_deal_connected() -> None:
    plays = [
        _play("p1", "A.jsonl", 1, 1, trick=1),
        _play("p2", "A.jsonl", 1, 2, trick=2),
        _play("p2", "B.jsonl", 1, 3, trick=3),
        _play("p3", "C.jsonl", 1, 4, trick=4),
    ]
    components = h0.derive_components(plays, [])
    assert components[0]["players"] == ["p1", "p2"]
    assert components[0]["deals"] == ["A.jsonl:round-1", "B.jsonl:round-1"]
    assert components[0]["play_rows"] == 3
    assert components[1]["players"] == ["p3"]


def test_selection_keeps_all_late_and_off_ballot_under_cap() -> None:
    rows = [
        _play("p1", f"{i}.jsonl", 1, i, trick=1,
              surface="follow", role="attacker", off=(i == 0))
        for i in range(4)
    ] + [
        _play("p1", f"late{i}.jsonl", 1, 20 + i, trick=18,
              surface="lead", role="defender")
        for i in range(2)
    ]
    selected = h0.select_rows(
        rows, target=4,
        cell_targets={("early", "follow", "attacker"): 2},
        max_per_deal=1,
    )
    keys = {h0.play_key(row) for row in selected}
    assert h0.play_key(rows[0]) in keys
    assert all(h0.play_key(row) in keys for row in rows[-2:])
    assert len(selected) == 4


def test_selection_refuses_vacuous_mandatory_cell() -> None:
    rows = [
        _play("p1", "A.jsonl", 1, 1, trick=1, off=True),
        _play("p1", "B.jsonl", 1, 2, trick=1, off=True),
    ]
    with pytest.raises(h0.H0PacketError, match="mandatory rows exceed"):
        h0.select_rows(
            rows, target=1,
            cell_targets={("early", "follow", "attacker"): 1},
        )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_corpus_validation_binds_artifacts_and_authority(tmp_path: Path) -> None:
    corpus = tmp_path / "human"
    corpus.mkdir()
    play = _play("p1", "A.jsonl", 1, 1, trick=1)
    bury = {"source": "A.jsonl", "round": 1, "player_id": "p1"}
    _write_jsonl(corpus / "play_decisions.jsonl", [play])
    _write_jsonl(corpus / "bury_decisions.jsonl", [bury])
    (corpus / "shard_00000.npz").write_bytes(b"score-free-test-fixture")
    artifacts = [
        {"name": path.name, "sha256": _sha(path), "bytes": path.stat().st_size}
        for path in sorted(corpus.iterdir())
    ]
    manifest = {
        "schema": h0.CORPUS_SCHEMA,
        "producer_git": "a" * 40,
        "producer_sha256": "b" * 64,
        "producer_tree_dirty": False,
        "training_authorized": False,
        "strength_claim": False,
        "source_manifest_sha256": "c" * 64,
        "sources": [{"name": "A.jsonl"}],
        "stats": {"play_decisions_accepted": 1,
                  "bury_decisions_accepted": 1},
        "artifacts": artifacts,
    }
    manifest_path = corpus / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    _, plays, buries = h0.validate_corpus(corpus, _sha(manifest_path))
    assert plays == [play]
    assert buries == [bury]

    (corpus / "play_decisions.jsonl").write_text("{}\n")
    with pytest.raises(h0.H0PacketError, match="artifact drift"):
        h0.validate_corpus(corpus, _sha(manifest_path))


def test_packet_authority_cannot_widen() -> None:
    expected = {"authority": {
        "score_free": True,
        "outcomes_computed": False,
        "execution_controller_implementation_authorized": False,
        "counterfactual_execution_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }}
    assert h0.packet_problems(expected, expected) == []
    widened = json.loads(json.dumps(expected))
    widened["authority"]["training_authorized"] = True
    assert "packet authority widened" in h0.packet_problems(widened, expected)


def test_v2_binds_the_executable_v11_checkpoint_and_portable_parent(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkpoint = tmp_path / "ep07.npz"
    checkpoint.write_bytes(b"fixture")
    monkeypatch.setattr(
        h0, "sha256_file",
        lambda path: (h0.V11PAIR_SHA256 if Path(path) == checkpoint
                      else h0.LIVE_PARENT_AUTH_SHA256),
    )
    bound = h0.validate_v11_checkpoint(checkpoint)
    assert bound == {
        "logical_path": "server/snapshots_v11pair/ep07.npz",
        "sha256": h0.V11PAIR_SHA256,
        "bytes": len(b"fixture"),
        "format": "numpy-npz",
        "encoder_contract": "reviewed-public-no-private-kitty-v1",
    }
    assert h0.V11PAIR_SHA256 == \
        "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
    parent = h0.live_parent_contract()
    assert parent["policy"] == "mc-s0-report-lcb"
    assert parent["authenticator_git"] == \
        "5390019aef36f63150d7613b38bf56cf9cfebf8b"
    assert parent["must_reopen_portably_before_each_execution"] is True


def test_v11_checkpoint_drift_refuses(monkeypatch: pytest.MonkeyPatch,
                                      tmp_path: Path) -> None:
    checkpoint = tmp_path / "ep07.npz"
    checkpoint.write_bytes(b"wrong")
    monkeypatch.setattr(h0, "sha256_file", lambda _path: "0" * 64)
    with pytest.raises(h0.H0PacketError, match="V11 checkpoint SHA-256 drift"):
        h0.validate_v11_checkpoint(checkpoint)


def test_v2_proposal_semantics_are_not_a_scalar_leaf() -> None:
    source = SCRIPT.read_text()
    assert '"action_universe": "exact-live-champion-analysis-ballot"' in source
    assert '"threshold_applied": False' in source
    assert '"scalar_leaf_use": False' in source
    assert '"proposals_per_decision": 1' in source
    assert '"report_fold_cannot_select_or_change_candidate_union": True' in source
