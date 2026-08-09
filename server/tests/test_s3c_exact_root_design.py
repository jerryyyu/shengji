from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "s3c_exact_root_design.py"
SPEC = importlib.util.spec_from_file_location("s3c_exact_root_design", SCRIPT)
assert SPEC and SPEC.loader
S3C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S3C)


def _corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    corpus = tmp_path / "human_v8"
    corpus.mkdir()
    plays = [
        {"source": "a.jsonl", "round": 1, "event_index": remaining,
         "cards_remaining": remaining,
         "surface": "lead" if remaining % 4 == 0 else "follow",
         "role": "attacker" if remaining % 2 else "defender"}
        for remaining in range(1, 14)
    ]
    play_path = corpus / "play_decisions.jsonl"
    play_path.write_text("".join(json.dumps(row) + "\n" for row in plays))
    manifest = {
        "schema": "human-decision-corpus-v1",
        "artifacts": [{
            "name": "play_decisions.jsonl",
            "sha256": S3C.sha256_file(play_path),
            "bytes": play_path.stat().st_size,
        }],
    }
    manifest_path = corpus / "manifest.json"
    manifest_path.write_bytes(S3C.canonical_json(manifest))
    digest = S3C.sha256_file(manifest_path)
    monkeypatch.setattr(S3C, "HUMAN_MANIFEST_SHA256", digest)
    return corpus, digest


def _fake_prefix(seed: int, band: int, offset: int) -> dict:
    return {
        "state_id": f"s3c-b{band}-s{seed}-o{offset}",
        "deal_seed": seed,
        "max_hand_cards": band,
        "within_trick_offset": offset,
        "actor_seat": offset,
        "actor_role": "attacker" if offset % 2 else "defender",
        "surface": "lead" if offset == 0 else "follow",
        "trick_index": 24 - band,
        "trick_play_count": offset,
        "lead_size": None if offset == 0 else 1,
        "hand_sizes": [band - (1 if seat < offset else 0)
                       for seat in range(4)],
        "cards_remaining": 4 * band - offset,
        "legal_action_count": band + offset,
        "legal_action_size_counts": {"1": band + offset},
        "state_sha256": S3C.sha256_bytes(
            f"{seed}:{band}:{offset}".encode()),
    }


def _fake_sources(*, exact_solver_digest: str = "e" * 64) -> dict:
    return {
        name: {
            "logical_path": logical_path,
            "sha256": (exact_solver_digest if name == "exact_solver"
                       else S3C.sha256_bytes(name.encode())),
            "bytes": 1,
        }
        for name, logical_path in S3C.SOURCE_PATHS.items()
    }


def _smoke_census(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    corpus, digest = _corpus(tmp_path, monkeypatch)
    monkeypatch.setattr(S3C, "prefix_row", _fake_prefix)
    monkeypatch.setattr(S3C, "source_identity", _fake_sources)
    return S3C.build_census(corpus, digest, smoke=True)


@pytest.mark.parametrize(
    ("band", "seed", "expected_actions"),
    [(1, 173_000_000, 1), (2, 174_000_000, 3), (3, 175_000_000, 5)],
)
def test_real_natural_prefix_replays_deterministically(
        band: int, seed: int, expected_actions: int) -> None:
    first = S3C.prefix_row(seed, band, 0)
    second = S3C.prefix_row(seed, band, 0)
    assert first == second
    assert first is not None
    assert first["surface"] == "lead"
    assert first["hand_sizes"] == [band] * 4
    assert first["legal_action_count"] == expected_actions
    assert len(first["state_sha256"]) == 64


def test_human_appendix_is_bounded_and_identifier_free(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus, digest = _corpus(tmp_path, monkeypatch)
    appendix = S3C.human_witness_appendix(corpus, digest)
    assert [appendix["by_equivalent_band"][str(band)]["rows"]
            for band in (1, 2, 3)] == [4, 4, 4]
    assert appendix["raw_identifiers_published"] is False
    assert appendix["formal_selection_source"] is False
    assert "a.jsonl" not in json.dumps(appendix)
    assert appendix["witness_key_sha256"] != ""


def test_smoke_census_has_disjoint_balanced_score_free_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    assert census["schema"] == S3C.CENSUS_SCHEMA
    assert len(census["rows"]) == 12
    assert len({row["deal_seed"] for row in census["rows"]}) == 12
    for band in (1, 2, 3):
        rows = [row for row in census["rows"]
                if row["max_hand_cards"] == band]
        assert {row["within_trick_offset"] for row in rows} == {0, 1, 2, 3}
    assert census["authority"]["outcomes_computed"] is False
    assert census["authority"]["action_values_computed"] is False
    assert census["authority"]["solver_or_screen_launch_authorized"] is False
    for row in census["rows"]:
        assert "action_value" not in row
        assert "final_attacker_points" not in row


def test_census_validation_and_packet_keep_all_launches_closed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    census_path = tmp_path / "census.json"
    census_path.write_bytes(S3C.canonical_json(census))
    census_sha = S3C.sha256_file(census_path)
    assert S3C.validate_census(census_path, census_sha) == census

    packet = S3C.build_packet(census_path, census_sha, smoke=True)
    assert packet["curriculum"]["one_card"]["utility_or_strength_gate"] is False
    assert packet["curriculum"]["four_card"]["status"] == \
        "CLOSED_BY_S3B_V2_CAPACITY_FAILURE"
    assert packet["information_boundary"]["public_policy_observes_hidden_hands"] \
        is False
    assert packet["authority"]["solver_or_screen_launch_authorized"] is False
    assert packet["authority"]["two_or_three_card_work_authorized"] is False
    assert packet["authority"]["training_authorized"] is False

    widened = copy.deepcopy(packet)
    widened["authority"]["solver_or_screen_launch_authorized"] = True
    assert "packet authority widened" in S3C.packet_problems(widened, widened)


def test_validate_census_refuses_mutated_quota(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    census["rows"].pop()
    path = tmp_path / "short.json"
    path.write_bytes(S3C.canonical_json(census))
    with pytest.raises(S3C.S3CDesignError, match="structure/authority"):
        S3C.validate_census(path, S3C.sha256_file(path))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda census: census["rows"][0].__setitem__(
            "state_id", "wrong"), "row selection identity"),
        (lambda census: census["rows"][0].__setitem__(
            "action_value", 1), "row field set"),
        (lambda census: census["rows"][0].__setitem__(
            "cards_remaining", -1), "row hand geometry"),
        (lambda census: census["scan_contract"]["1"].__setitem__(
            "seeds_scanned", 1), "band 1 scan contract"),
    ],
)
def test_validate_census_refuses_malformed_rows_and_scan(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        mutation, message: str) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    mutation(census)
    path = tmp_path / "mutated.json"
    path.write_bytes(S3C.canonical_json(census))
    with pytest.raises(S3C.S3CDesignError, match=message):
        S3C.validate_census(path, S3C.sha256_file(path))


def test_validate_census_refuses_stale_embedded_digest(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    census["human_witness_appendix"]["classification"] += " changed"
    path = tmp_path / "stale-digest.json"
    path.write_bytes(S3C.canonical_json(census))
    with pytest.raises(S3C.S3CDesignError, match="embedded digest"):
        S3C.validate_census(path, S3C.sha256_file(path))


def test_packet_refuses_stale_source_identity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    path = tmp_path / "census.json"
    path.write_bytes(S3C.canonical_json(census))
    monkeypatch.setattr(
        S3C, "source_identity",
        lambda: _fake_sources(exact_solver_digest="f" * 64))
    with pytest.raises(S3C.S3CDesignError, match="packet source identity"):
        S3C.build_packet(path, S3C.sha256_file(path), smoke=True)


def test_real_packet_refuses_smoke_census(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    census = _smoke_census(tmp_path, monkeypatch)
    path = tmp_path / "smoke.json"
    path.write_bytes(S3C.canonical_json(census))
    with pytest.raises(S3C.S3CDesignError, match="smoke/real"):
        S3C.build_packet(path, S3C.sha256_file(path), smoke=False)


def test_publish_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "packet.json"
    S3C.publish_exclusive(path, {"ok": True})
    with pytest.raises(S3C.S3CDesignError, match="existing"):
        S3C.publish_exclusive(path, {"ok": False})


def test_frozen_loader_refuses_symlink_and_hardlink(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}\n")
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(source)
    with pytest.raises(S3C.S3CDesignError, match="regular/unlinked"):
        S3C._load_frozen_json(symlink)

    hardlink = tmp_path / "hardlink.json"
    hardlink.hardlink_to(source)
    with pytest.raises(S3C.S3CDesignError, match="regular/unlinked"):
        S3C._load_frozen_json(source)
