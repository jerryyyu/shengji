from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SERVER = Path(__file__).parents[1]
REPO = SERVER.parent
SCRIPTS = SERVER / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CTRL = _load(
    "s3c_one_card_controller", SCRIPTS / "s3c_one_card_controller.py")
RUNTIME = _load(
    "s3c_one_card_runtime", SCRIPTS / "s3c_one_card_runtime.py")


def _fake_census() -> dict:
    rows = []
    for offset in range(4):
        for index in range(64):
            seed = 173_000_000 + offset * 100 + index
            rows.append({
                "state_id": f"s3c-b1-s{seed}-o{offset}",
                "deal_seed": seed,
                "max_hand_cards": 1,
                "within_trick_offset": offset,
                "actor_seat": offset,
                "actor_role": "attacker" if index % 2 else "defender",
                "surface": "lead" if offset == 0 else "follow",
                "state_sha256": CTRL.sha256_bytes(
                    f"{seed}:{offset}".encode()),
                "legal_action_count": 1,
                "legal_action_size_counts": {"1": 1},
            })
    return {"rows": rows}


def _scheduled_root(offset: int = 0, *, state_id: str = "root-0") -> dict:
    return {
        "state_id": state_id,
        "deal_seed": 173_000_001 + offset,
        "within_trick_offset": offset,
        "actor_seat": offset,
        "actor_role": "attacker",
        "surface": "lead" if offset == 0 else "follow",
        "state_sha256": "a" * 64,
        "legal_action_count": 1,
        "legal_action_size_counts": {"1": 1},
        "selection_rank_within_offset": 1,
        "selection_hash": "b" * 64,
        "worlds": [{"index": index, "seed": 1000 + index}
                   for index in range(4)],
    }


def _world_record(index: int, offset: int = 0) -> dict:
    frontier = 0 if offset == 3 else 1
    nodes = 0 if frontier == 0 else 2
    return {
        "status": "COMPLETE",
        "world_index": index,
        "world_seed": 1000 + index,
        "world_sha256": f"{index + 1:064x}",
        "sampler": {
            "sample_attempts": 1,
            "accepted_worlds": 1,
            "failed_worlds": 0,
            "rejected_worlds": 0,
            "impossible_worlds": 0,
        },
        "exact": {
            "attempts": frontier,
            "successes": frontier,
            "refusals": 0,
            "budget_overflows": 0,
            "sessions": 1,
            "nodes": nodes,
            "cache_hits": 0,
        },
        "session": {
            "frontiers": frontier,
            "nodes": nodes,
            "cache_hits": 0,
            "max_hand_cards": 1,
            "max_nodes": 256,
        },
    }


def _root_record(root: dict, *, refused: bool = False) -> dict:
    worlds = [_world_record(index, root["within_trick_offset"])
              for index in range(4)]
    if refused:
        worlds = worlds[:2]
        worlds[-1] = {
            "status": "REFUSED_SCORE_FREE",
            "world_index": 1,
            "world_seed": 1001,
            "reason_class": "SAMPLER_REFUSAL",
            "sampler": {
                "sample_attempts": 1,
                "accepted_worlds": 0,
                "failed_worlds": 1,
                "rejected_worlds": 1,
                "impossible_worlds": 0,
            },
            "exact": {
                "attempts": 0,
                "successes": 0,
                "refusals": 0,
                "budget_overflows": 0,
                "sessions": 0,
                "nodes": 0,
                "cache_hits": 0,
            },
            "session": {
                "frontiers": 0,
                "nodes": 0,
                "cache_hits": 0,
                "max_hand_cards": 1,
                "max_nodes": 256,
            },
        }
    record = {
        "status": "REFUSED_SCORE_FREE" if refused else "COMPLETE",
        "state_id": root["state_id"],
        "deal_seed": root["deal_seed"],
        "within_trick_offset": root["within_trick_offset"],
        "actor_seat": root["actor_seat"],
        "actor_role": root["actor_role"],
        "surface": root["surface"],
        "state_sha256": root["state_sha256"],
        "selection_hash": root["selection_hash"],
        "legal_action_count": 1,
        "legal_action_sha256": "c" * 64,
        "worlds": worlds,
        "work": RUNTIME._sum_world_counters(worlds),
    }
    if refused:
        record["reason_class"] = "SAMPLER_REFUSAL"
    return record


def _packet(roots: list[dict]) -> dict:
    schedule = {"roots": roots, "schedule_sha256": "d" * 64}
    return {
        "producer": {
            "git": "e" * 40,
            "controller_script_sha256": "f" * 64,
        },
        "runtime_sources": {
            "server/scripts/s3c_one_card_runtime.py": "1" * 64,
        },
        "schedule": schedule,
        "score_free_preflight": {"root_geometry_sha256": "2" * 64},
        "packet_sha256": "3" * 64,
        "external_packet_sha256": "4" * 64,
    }


def test_select_roots_is_balanced_deterministic_and_deal_disjoint() -> None:
    census = _fake_census()
    first = CTRL.select_roots(census)
    second = CTRL.select_roots(copy.deepcopy(census))
    assert first == second
    assert len(first) == 64
    assert len({row["deal_seed"] for row in first}) == 64
    assert {offset: sum(row["within_trick_offset"] == offset for row in first)
            for offset in range(4)} == {0: 16, 1: 16, 2: 16, 3: 16}
    assert all(row["legal_action_count"] == 1 for row in first)


def test_schedule_has_exact_unique_world_work() -> None:
    schedule = CTRL.build_schedule(_fake_census())
    seeds = [world["seed"] for root in schedule["roots"]
             for world in root["worlds"]]
    assert schedule["root_count"] == 64
    assert schedule["world_count"] == 256
    assert len(seeds) == len(set(seeds)) == 256
    assert schedule["max_execution_nodes"] == 65_536
    assert schedule["max_total_pipeline_nodes"] == 131_072


def test_tracked_design_and_census_reopen_exactly() -> None:
    design_path = REPO / CTRL.DESIGN_PACKET_LOGICAL_PATH
    census_path = REPO / CTRL.CENSUS_LOGICAL_PATH
    design = CTRL.validate_design_packet(design_path)
    census = CTRL.validate_census(census_path)
    assert design["packet_sha256"] == CTRL.DESIGN_PACKET_INTERNAL_SHA256
    assert census["census_sha256"] == CTRL.CENSUS_INTERNAL_SHA256
    assert len(CTRL.select_roots(census)) == 64


def test_real_score_free_preflight_replays_roots_without_worlds() -> None:
    census = CTRL.validate_census(REPO / CTRL.CENSUS_LOGICAL_PATH)
    preflight = CTRL.score_free_preflight(CTRL.build_schedule(census))
    assert preflight["roots_replayed"] == 64
    assert preflight["by_offset"] == {"0": 16, "1": 16, "2": 16, "3": 16}
    assert preflight["worlds_sampled"] == 0
    assert preflight["exact_solver_sessions"] == 0
    assert preflight["outcomes_computed"] is False


def test_design_review_marker_is_exact(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    review = tmp_path / "review.md"
    review.write_text(
        "S3C_EXACT_ROOT_CURRICULUM_V1_REVIEW "
        + json.dumps(CTRL.DESIGN_REVIEW_CLAIM, sort_keys=True) + "\n")
    monkeypatch.setattr(CTRL, "require_ancestor", lambda _commit: None)
    assert CTRL.require_design_review(review) == CTRL.DESIGN_REVIEW_CLAIM
    changed = dict(CTRL.DESIGN_REVIEW_CLAIM, strength_claim=True)
    review.write_text(
        "S3C_EXACT_ROOT_CURRICULUM_V1_REVIEW "
        + json.dumps(changed, sort_keys=True) + "\n")
    with pytest.raises(CTRL.ControllerRefused, match="marker drift"):
        CTRL.require_design_review(review)


def test_packet_authority_and_preflight_mutations_refuse() -> None:
    expected = {
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "exact_solver_invoked": False,
            "action_values_computed": False,
            "outcomes_computed": False,
            "controller_review_authorized": True,
            "one_card_capacity_execution_authorized": False,
            "two_card_packet_review_authorized": False,
            "solver_or_strength_screen_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
        "score_free_preflight": {
            "worlds_sampled": 0,
            "exact_solver_sessions": 0,
            "exact_solver_nodes": 0,
            "action_values_computed": False,
            "outcomes_computed": False,
        },
    }
    assert CTRL.packet_problems(expected, expected) == []
    widened = copy.deepcopy(expected)
    widened["authority"]["one_card_capacity_execution_authorized"] = True
    assert "controller authority widened" in CTRL.packet_problems(
        widened, expected)
    sampled = copy.deepcopy(expected)
    sampled["score_free_preflight"]["worlds_sampled"] = 1
    assert "controller preflight is not score-free" in CTRL.packet_problems(
        sampled, expected)


def test_exclusive_publication_refuses_second_writer(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    CTRL.publish_exclusive(path, {"ok": True})
    with pytest.raises(CTRL.ControllerRefused, match="overwrite"):
        CTRL.publish_exclusive(path, {"ok": False})


class _FakeSession:
    def __init__(self, frontiers: int):
        self.frontiers = 0
        self.nodes = 0
        self.cache_hits = 0
        self.expected_frontiers = frontiers
        self.solver = SimpleNamespace(max_hand_cards=1, max_nodes=256)


class _FakeBot:
    def __init__(self, _seed: int, *, frontiers: int, sample: bool = True):
        self.frontiers = frontiers
        self.sample = sample
        self.sample_attempts = 0
        self.accepted_worlds = 0
        self.failed_worlds = 0
        self.rejected_worlds = 0
        self.impossible_worlds = 0
        self.exact_endgame_attempts = 0
        self.exact_endgame_calls = 0
        self.exact_endgame_refusals = 0
        self.exact_endgame_budget_exceeded = 0
        self.exact_endgame_sessions = 0
        self.exact_endgame_nodes = 0
        self.exact_endgame_cache_hits = 0

    def _sample_hands(self, _rnd, _seat, _memory):
        self.sample_attempts += 1
        if not self.sample:
            self.failed_worlds += 1
            self.rejected_worlds += 1
            return None
        self.accepted_worlds += 1
        return {1: ["H2"], 2: ["H3"], 3: ["H4"]}, ["D2"]

    def _new_exact_world_session(self, _rnd, _buried):
        self.exact_endgame_sessions += 1
        self.session = _FakeSession(self.frontiers)
        return self.session

    def _rollout(self, _rnd, _seat, _sampled, _buried, _action, *,
                 exact_session):
        if self.frontiers:
            self.exact_endgame_attempts += 1
            self.exact_endgame_calls += 1
            self.exact_endgame_nodes += 2
            exact_session.frontiers = 1
            exact_session.nodes = 2
        return 80.0


@pytest.mark.parametrize(("offset", "frontiers"), [(0, 1), (3, 0)])
def test_run_world_publishes_capacity_not_score(
        offset: int, frontiers: int,
        monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scheduled_root(offset)
    fake = _FakeBot(1000, frontiers=frontiers)
    monkeypatch.setattr(RUNTIME, "OneCardExactBot", lambda seed: fake)
    monkeypatch.setattr(RUNTIME, "Memory", lambda *_args, **_kwargs: object())
    rnd = SimpleNamespace(turn=offset)
    record = RUNTIME.run_world(
        rnd, ["H2"], root, root["worlds"][0])
    assert record["status"] == "COMPLETE"
    assert record["exact"]["attempts"] == frontiers
    assert "attacker_points" not in json.dumps(record)
    RUNTIME.validate_world_record(record, offset=offset)


def test_sampler_refusal_is_terminal_and_score_free(
        monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scheduled_root(0)
    fake = _FakeBot(1000, frontiers=1, sample=False)
    monkeypatch.setattr(RUNTIME, "OneCardExactBot", lambda seed: fake)
    monkeypatch.setattr(RUNTIME, "Memory", lambda *_args, **_kwargs: object())
    record = RUNTIME.run_world(
        SimpleNamespace(turn=0), ["H2"], root, root["worlds"][0])
    assert record["status"] == "REFUSED_SCORE_FREE"
    assert record["reason_class"] == "SAMPLER_REFUSAL"
    assert record["sampler"]["accepted_worlds"] == 0
    assert record["exact"]["sessions"] == 0


def test_world_validator_rejects_hidden_outcome_field() -> None:
    record = _world_record(0)
    record["attacker_points"] = 80
    with pytest.raises(RUNTIME.RuntimeRefused, match="forbidden result field"):
        RUNTIME.validate_world_record(record, offset=0)


def test_world_validator_rejects_wrong_offset_frontier() -> None:
    record = _world_record(0, offset=0)
    record["exact"]["attempts"] = 0
    with pytest.raises(RUNTIME.RuntimeRefused, match="exact/session counters"):
        RUNTIME.validate_world_record(record, offset=0)


def test_run_root_stops_at_first_refusal_without_replacement(
        monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scheduled_root(0)
    monkeypatch.setattr(
        RUNTIME, "replay_root", lambda _root: (object(), [["H2"]]))
    calls = []

    def fake_world(_rnd, _action, _root, world):
        calls.append(world["index"])
        if world["index"] == 1:
            return _root_record(root, refused=True)["worlds"][-1]
        return _world_record(world["index"])

    monkeypatch.setattr(RUNTIME, "run_world", fake_world)
    record = RUNTIME.run_root(root)
    assert calls == [0, 1]
    assert record["status"] == "REFUSED_SCORE_FREE"
    assert record["work"]["worlds_attempted"] == 2


def test_result_payload_complete_is_capacity_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CTRL, "ROOT_COUNT", 1)
    root = _scheduled_root(0)
    packet = _packet([root])
    payload = RUNTIME.result_payload(packet, "5" * 64, [_root_record(root)])
    assert payload["status"] == "COMPLETE_CAPACITY_ONLY"
    assert payload["two_card_packet_review_authorized"] is False
    assert payload["utility_or_strength_gate"] is False
    assert payload["action_values_published"] is False


def test_result_payload_any_refusal_closes_next_authority(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CTRL, "ROOT_COUNT", 1)
    root = _scheduled_root(0)
    packet = _packet([root])
    payload = RUNTIME.result_payload(
        packet, "5" * 64, [_root_record(root, refused=True)])
    assert payload["status"] == "REFUSED_INCOMPLETE_NO_NEXT_AUTHORITY"
    assert payload["counts"]["roots_refused"] == 1
    assert payload["two_card_packet_review_authorized"] is False


def test_terminal_payload_is_only_place_two_card_review_can_open(
        tmp_path: Path) -> None:
    root = _scheduled_root(0)
    packet = _packet([root])
    result = {"status": "COMPLETE_CAPACITY_ONLY", "result_sha256": "6" * 64}
    result_path = tmp_path / "result.json"
    result_path.write_text("{}\n")
    final = RUNTIME.terminal_payload(packet, result_path, result, 1, 2)
    assert final["status"] == "AUTHORIZE_TWO_CARD_MECHANISM_PACKET_REVIEW"
    assert final["two_card_packet_review_authorized"] is True
    assert final["solver_or_strength_screen_authorized"] is False


def test_expected_controller_review_claim_never_authorizes_two_card() -> None:
    packet = _packet([_scheduled_root(0)])
    claim = RUNTIME.expected_review_claim(packet, "4" * 64)
    assert claim["one_card_capacity_execution_authorized"] is True
    assert claim["two_card_packet_review_authorized"] is False
    assert claim["worlds_sampled_before_review"] == 0
    assert claim["exact_solver_sessions_before_review"] == 0
    assert claim["strength_claim"] is False


def test_admission_slot_survives_receipt_and_blocks_reissue(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = tmp_path / "run"
    receipt_path = namespace / "execution-receipt.json"
    slot_path = tmp_path / "locks" / "consumed.json"
    packet = _packet([_scheduled_root(0)])
    monkeypatch.setattr(RUNTIME, "_expected_namespace", lambda: namespace)
    monkeypatch.setattr(RUNTIME, "_expected_receipt_path", lambda: receipt_path)
    monkeypatch.setattr(RUNTIME, "_expected_slot_path", lambda: slot_path)
    monkeypatch.setattr(RUNTIME, "_controller_packet", lambda *_args: packet)
    monkeypatch.setattr(
        RUNTIME, "_controller_review",
        lambda *_args: RUNTIME.expected_review_claim(packet, "4" * 64))
    review = tmp_path / "review.md"
    review.write_text("review\n")
    receipt = RUNTIME.admit(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="4" * 64,
        design_path=tmp_path / "design.json",
        census_path=tmp_path / "census.json",
        design_review_record=review,
        controller_review_record=review,
        namespace=namespace,
        receipt_path=receipt_path,
    )
    assert receipt_path.is_file()
    assert slot_path.is_file()
    assert receipt["one_card_capacity_execution_authorized"] is True
    receipt_path.unlink()
    with pytest.raises(RUNTIME.RuntimeRefused, match="slot is already consumed"):
        RUNTIME.admit(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="4" * 64,
            design_path=tmp_path / "design.json",
            census_path=tmp_path / "census.json",
            design_review_record=review,
            controller_review_record=review,
            namespace=namespace,
            receipt_path=receipt_path,
        )


def test_terminal_verifier_requires_explicit_full_replay() -> None:
    with pytest.raises(RUNTIME.RuntimeRefused, match="replay-every-complete-root"):
        RUNTIME.verify_result(
            packet_path=Path("packet"), expected_packet_sha256="a" * 64,
            design_path=Path("design"), census_path=Path("census"),
            design_review_record=Path("review"), receipt_path=Path("receipt"),
            expected_receipt_sha256="b" * 64, result_path=Path("result"),
            out=Path("final"), replay_every_complete_root=False,
        )


def test_command_contract_is_single_process_and_progress_visible() -> None:
    commands = CTRL.command_templates()
    assert "run_once" in commands
    assert "run_shards" not in commands
    assert "--progress-every" in commands["run_once"]
    assert "--replay-every-complete-root" in commands["terminal_verify"]
