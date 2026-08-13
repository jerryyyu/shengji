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


def _historical_execution_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    """Reopen the frozen H0 contract without blessing current source bytes.

    H0-v3 permanently names the heuristic bytes it actually scored.  Static
    contract-shape tests should keep inspecting that historical object after
    the live heuristic evolves, while the real execution entry point must
    still refuse those moving bytes.  Mock only this one frozen identity; do
    not rewrite the production constant or relax ``validate_source``.
    """
    frozen_path = h0.REPO / h0.ROLLOUT_POLICY_LOGICAL_PATH
    actual_sha256_file = h0.sha256_file

    def historical_sha256_file(path) -> str:
        if Path(path) == frozen_path:
            return h0.ROLLOUT_POLICY_SHA256
        return actual_sha256_file(path)

    with monkeypatch.context() as patch:
        patch.setattr(h0, "sha256_file", historical_sha256_file)
        return h0.execution_contract()


def test_corpus_validation_binds_artifacts_and_authority(tmp_path: Path) -> None:
    corpus = tmp_path / "human"
    corpus.mkdir()
    play = _play("p1", "A.jsonl", 1, 1, trick=1)
    bury = {"source": "A.jsonl", "round": 1, "seat": 0,
            "player_id": "p1", "chosen": ["H3"]}
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


def test_v3_binds_the_executable_v11_checkpoint_and_portable_parent(
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


def test_v3_play_union_is_bounded_and_exhaustive_actions_only_propose() -> None:
    contract = h0.proposal_contract(
        {"policy": "mc-s0-report-lcb"}, {"sha256": "c" * 64})
    assert contract["production_ballot"] == {
        "source": "MCBot._candidates from exact live parent",
        "lead_max_candidates": 14,
        "follow_max_candidates": 12,
        "must_preserve_order_and_candidate_zero": True,
        "full_exhaustive_universe_is_not_added_to_union": True,
    }
    assert contract["play_source_maxima"] == {
        "live_production_ballot": 14,
        "human_action": 1,
        "v11pair_top_proposal": 1,
        "matched_random_proposal": 1,
        "max_unique_after_deduplication": 17,
    }
    assert contract["analysis_action_universe"][
        "all_actions_evaluated_by_pilot"] is False
    assert contract["v11pair_top_proposal"]["action_universe"] == \
        "shared-novel-proposal-pool"
    assert contract["random_diversifier"]["action_universe"] == \
        "shared-novel-proposal-pool"
    assert contract["novel_proposal_pool"]["shared_by_v11_and_random"] is True
    assert contract["v11pair_top_proposal"]["threshold_applied"] is False
    assert contract["v11pair_top_proposal"]["scalar_leaf_use"] is False
    encoded = json.dumps(contract, sort_keys=True)
    assert "live_champion_analysis_ballot" not in encoded
    assert "same_budget_random_structured_bury" not in encoded


def test_v3_bury_is_a_separate_bounded_surface() -> None:
    contract = h0.proposal_contract({}, {})
    bury = contract["structured_bury_ballot"]
    assert bury["max_candidates"] == 32
    assert bury["candidate_zero"] == "live_smart_bury"
    assert bury["max_unique_after_human_deduplication"] == 33
    assert contract["bury_union"] == [
        "s3a_structured_ballot_including_live_smart_candidate_zero",
        "human_bury_if_novel",
    ]


def test_v3_names_root_policy_and_real_rollout_continuation_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _historical_execution_contract(monkeypatch)
    assert contract["play_root_reference"]["policy"] == "mc-s0-report-lcb"
    assert contract["play_root_reference"][
        "separate_from_pilot_selection_and_report_folds"] is True
    assert contract["bury_root_reference"] == {
        "policy": "live_smart_bury",
        "candidate_world_rollouts": 0,
        "must_equal_structured_ballot_candidate_zero": True,
    }
    rollout = contract["rollout_continuation"]
    assert rollout["policy"] == "HeuristicBot"
    assert rollout["logical_path"] == "server/shengji/ai/heuristic.py"
    assert rollout["sha256"] == h0.ROLLOUT_POLICY_SHA256
    assert rollout["report_lcb_is_not_recursive_continuation"] is True
    assert contract["rng_folds"][
        "all_three_world_folds_pairwise_disjoint"] is True
    encoded = json.dumps(contract, sort_keys=True)
    assert '"production_continuation": "mc-s0-report-lcb"' not in encoded


def test_v3_work_ceiling_reconciles_from_named_actions_and_worlds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert h0.PLAY_REFERENCE_MAX_CANDIDATE_WORLDS == 14 * 30 + 2 * 300
    assert h0.PLAY_PILOT_MAX_CANDIDATE_WORLDS == 17 * 30 + 3 * 300
    assert h0.PLAY_MAX_CANDIDATE_WORLDS == 2430
    assert h0.BURY_MAX_CANDIDATE_WORLDS == 33 * 30 + 3 * 300 == 1890
    expected = 512 * 2430 + 45 * 1890
    assert h0.TOTAL_MAX_CANDIDATE_WORLDS == expected == 1_329_210
    work = _historical_execution_contract(monkeypatch)["work_ceiling"]
    assert work["selected_play_rows"] == 512
    assert work["selected_bury_rows"] == 45
    assert work["all_rows_max_candidate_worlds"] == expected


def test_v3_reports_source_survival_not_undefined_candidate_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _historical_execution_contract(monkeypatch)
    outputs = contract["outputs"]
    assert outputs["candidate_recall_claimed"] is False
    assert outputs["report_estimands"] == [
        "human-minus-reference-paired-utility",
        "selected-minus-reference-paired-utility",
        "selected-minus-human-paired-utility",
    ]
    completion = contract["row_completion"]
    assert completion["no_replacement_or_resampling_of_selected_rows"] is True
    assert completion[
        "partial_action_or_world_dose_cannot_publish_a_utility_row"] is True


def test_v3_source_identity_drift_refuses(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(h0, "sha256_file", lambda _path: "0" * 64)
    with pytest.raises(h0.H0PacketError, match="source SHA-256 drift"):
        h0.validate_source(
            h0.ROLLOUT_POLICY_LOGICAL_PATH, h0.ROLLOUT_POLICY_SHA256)


def test_v3_frozen_rollout_sha_is_unchanged_and_live_drift_refuses() -> None:
    assert h0.ROLLOUT_POLICY_SHA256 == (
        "a99dfb089fd17e7c17ddcc4d76542552d317598fbe233269c3e7c0501b9b15ef"
    )
    live_path = h0.REPO / h0.ROLLOUT_POLICY_LOGICAL_PATH
    assert h0.sha256_file(live_path) != h0.ROLLOUT_POLICY_SHA256
    with pytest.raises(h0.H0PacketError, match="source SHA-256 drift"):
        h0.execution_contract()
