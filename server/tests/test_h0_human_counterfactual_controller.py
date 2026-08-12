from __future__ import annotations

import importlib.util
import json
import random
import subprocess
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
CONTROLLER = SCRIPTS / "h0_human_counterfactual_controller.py"
RUNTIME = SCRIPTS / "h0_human_counterfactual_runtime.py"

spec = importlib.util.spec_from_file_location("h0_controller", CONTROLLER)
assert spec and spec.loader
ctrl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctrl)

runtime_spec = importlib.util.spec_from_file_location("h0_runtime", RUNTIME)
assert runtime_spec and runtime_spec.loader
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)


def test_level_utility_includes_deal_half_level_and_role_sign() -> None:
    assert ctrl.attacker_level_utility(0) == -3.5
    assert ctrl.attacker_level_utility(39) == -2.5
    assert ctrl.attacker_level_utility(40) == -1.5
    assert ctrl.attacker_level_utility(79) == -1.5
    assert ctrl.attacker_level_utility(80) == 0.5
    assert ctrl.attacker_level_utility(120) == 1.5
    assert ctrl.attacker_level_utility(200) == 3.5
    assert ctrl.acting_utility(120, attacker=True) == 1.5
    assert ctrl.acting_utility(120, attacker=False) == -1.5
    with pytest.raises(ctrl.ControllerRefused, match="negative"):
        ctrl.attacker_level_utility(-1)
    with pytest.raises(ctrl.ControllerRefused, match="integral"):
        ctrl.attacker_level_utility(79.5)


def test_named_stream_seeds_are_deterministic_and_independent() -> None:
    args = ("DESIGN", "A.jsonl:round-1:event-7:seat-0", "play")
    reference = ctrl.seed_for(
        ctrl.DESIGN.REFERENCE_WORLD_DOMAIN, *args, "reference")
    selection = ctrl.seed_for(
        ctrl.DESIGN.SELECTION_WORLD_DOMAIN, *args, "selection")
    report = ctrl.seed_for(
        ctrl.DESIGN.REPORT_WORLD_DOMAIN, *args, "report")
    proposal = ctrl.seed_for(
        ctrl.DESIGN.PROPOSAL_SEED_DOMAIN, *args, "proposal")
    assert len({reference, selection, report, proposal}) == 4
    assert reference == ctrl.seed_for(
        ctrl.DESIGN.REFERENCE_WORLD_DOMAIN, *args, "reference")
    assert reference != ctrl.seed_for(
        ctrl.DESIGN.REFERENCE_WORLD_DOMAIN, "AUDIT", args[1], args[2],
        "reference")


def test_checked_in_v3_design_and_review_marker_reopen_exactly() -> None:
    repo = Path(__file__).parents[2]
    packet = ctrl.validate_design_packet(
        repo / ctrl.DESIGN_PACKET_LOGICAL_PATH)
    claim = ctrl.require_design_review(repo / "HANDOFF_REVIEW.md")
    assert packet["schema"] == ctrl.DESIGN.SCHEMA
    assert claim["verdict"] == "PASS"
    assert claim["max_candidate_worlds"] == 1_329_210
    assert claim["counterfactual_execution_authorized"] is False


def test_schedule_is_deal_clustered_complete_and_balanced() -> None:
    repo = Path(__file__).parents[2]
    packet = ctrl.validate_design_packet(
        repo / ctrl.DESIGN_PACKET_LOGICAL_PATH)
    schedule = ctrl.build_schedule(packet)
    assert len(schedule["shards"]) == 8
    row_keys = [key for shard in schedule["shards"]
                for key in shard["row_keys"]]
    assert len(row_keys) == len(set(row_keys)) == 557
    assert sum(shard["play_rows"] for shard in schedule["shards"]) == 512
    assert sum(shard["bury_rows"] for shard in schedule["shards"]) == 45
    loads = [shard["max_candidate_worlds"] for shard in schedule["shards"]]
    assert sum(loads) == 1_329_210
    assert max(loads) - min(loads) <= ctrl.DESIGN.PLAY_MAX_CANDIDATE_WORLDS
    deal_shards: dict[str, set[int]] = {}
    for shard in schedule["shards"]:
        for deal in shard["deal_keys"]:
            deal_shards.setdefault(deal, set()).add(shard["index"])
    assert all(len(indices) == 1 for indices in deal_shards.values())


def _play_round(seed: int = 11):
    from shengji.ai.smart import SmartBot
    from shengji.engine.game import Game

    rnd = Game(random.Random(seed)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, SmartBot().decide_bury(rnd, rnd.banker))
    return rnd


class _FakeNet:
    def value_candidates(self, _obs, actions):
        # Strictly increasing values make the last canonical novel action the
        # deterministic V11 proposal without depending on numpy/torch.
        return list(range(len(actions)))


def test_play_union_is_bounded_and_retains_duplicate_attribution() -> None:
    rnd = _play_round()
    seat = rnd.turn
    bot = ctrl.make_bot("mc-s0-report-lcb", seed=0)
    human = bot._candidates(rnd, seat)[0]
    union, diagnostics = ctrl.build_play_union(
        rnd, seat, human, "DESIGN", "synthetic", _FakeNet(), bot)
    assert union[0]["sources"] == ["human_action", "live_production_ballot"]
    assert len(union) <= ctrl.DESIGN.PLAY_MAX_UNIQUE_CANDIDATES
    assert len({ctrl.action_key(item["cards"]) for item in union}) == len(union)
    assert diagnostics["human_in_live_ballot"] is True
    if diagnostics["novel_pool"]:
        assert diagnostics["v11_proposed"] is True
        assert diagnostics["random_proposed"] is True


def test_bury_union_preserves_live_candidate_zero_and_cap() -> None:
    from shengji.engine.game import Game

    rnd = Game(random.Random(4)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    seat = rnd.banker
    human = ctrl.SmartBot().decide_bury(rnd, seat)
    union, diagnostics = ctrl.build_bury_union(rnd, seat, human)
    assert union[0]["cards"] == sorted(human)
    assert "human_action" in union[0]["sources"]
    assert len(union) <= ctrl.DESIGN.BURY_MAX_UNIQUE_CANDIDATES
    assert diagnostics["human_in_structured_ballot"] is True


def _complete_row(*, role: str = "attacker") -> dict:
    selection_raw = [80.0] * ctrl.DESIGN.PROPOSAL_WORLDS
    report_raw = [80.0] * ctrl.DESIGN.REPORT_WORLDS
    utilities_selection = [0.5 if role == "attacker" else -0.5] * 30
    utilities_report = [0.5 if role == "attacker" else -0.5] * 300
    candidate = {
        "cards": ["H3"],
        "sources": ["human_action", "live_production_ballot"],
    }
    scored_selection = {
        **candidate,
        "raw_attacker_points": selection_raw,
        "utilities": utilities_selection,
        "mean_utility": utilities_selection[0],
    }
    scored_report = {
        **candidate,
        "raw_attacker_points": report_raw,
        "utilities": utilities_report,
        "mean_utility": utilities_report[0],
    }
    selection_seed = ctrl.seed_for(
        ctrl.DESIGN.SELECTION_WORLD_DOMAIN, "DESIGN", "x", "play",
        "pilot-selection")
    report_seed = ctrl.seed_for(
        ctrl.DESIGN.REPORT_WORLD_DOMAIN, "DESIGN", "x", "play",
        "pilot-report")

    def sampler(worlds: int) -> dict:
        return {
            "requested": worlds,
            "accepted": worlds,
            "attempts": worlds,
            "attempt_cap": worlds * 40,
            "counters": {
                "sample_attempts": worlds,
                "accepted_worlds": worlds,
                "failed_worlds": 0,
                "rejected_worlds": 0,
                "impossible_worlds": 0,
            },
            "world_keys_sha256": "a" * 64,
        }
    return {
        "schema": "human-h0-counterfactual-row-v1",
        "status": "COMPLETE",
        "row_key": "DESIGN|play|x",
        "split": "DESIGN",
        "surface_type": "play",
        "replay_key": "x",
        "deal_key": "deal-x",
        "player_id": "p",
        "surface": "lead",
        "phase": "early",
        "role": role,
        "human_action": ["H3"],
        "candidate_diagnostics": {
            "live_candidates": 1,
            "analysis_actions": 1,
            "novel_pool": 0,
            "human_in_live_ballot": True,
            "v11_proposed": False,
            "random_proposed": False,
            "v11_random_same": False,
            "v11_score_count": 0,
        },
        "candidates": [candidate],
        "reference": {
            "seed": ctrl.seed_for(
                ctrl.DESIGN.REFERENCE_WORLD_DOMAIN, "DESIGN", "x", "play",
                "live-report-lcb-root"),
            "action": ["H3"],
            "candidates": [["H3"]],
            "candidate_count": 1,
            "reason": "search-free-production-path",
            "selection_means": [],
            "work": {
                "selection_rollouts": 0,
                "report_rollouts": 0,
                "total_rollouts": 0,
                "complete": True,
            },
            "sampler_counters": {
                "sample_attempts": 0,
                "accepted_worlds": 0,
                "failed_worlds": 0,
                "rejected_worlds": 0,
                "impossible_worlds": 0,
            },
        },
        "selection": {
            "seed": selection_seed,
            "sampler": sampler(30),
            "actions": [scored_selection],
            "candidate_worlds": 30,
            "winner_index": 0,
            "winner": ["H3"],
            "winner_sources": ["human_action", "live_production_ballot"],
        },
        "report": {
            "seed": report_seed,
            "sampler": sampler(300),
            "actions": [scored_report],
            "candidate_worlds": 300,
        },
        "estimands": {
            "human_minus_reference_paired_utility": 0.0,
            "selected_minus_reference_paired_utility": 0.0,
            "selected_minus_human_paired_utility": 0.0,
        },
        "work": {
            "reference_candidate_worlds": 0,
            "selection_candidate_worlds": 30,
            "report_candidate_worlds": 300,
            "total_candidate_worlds": 330,
            "max_candidate_worlds": ctrl.DESIGN.PLAY_MAX_CANDIDATE_WORLDS,
            "complete": True,
        },
    }


def test_complete_row_rederives_utility_winner_estimands_and_work() -> None:
    row = _complete_row()
    runtime.validate_complete_row(row)
    drifted = json.loads(json.dumps(row))
    drifted["report"]["actions"][0]["raw_attacker_points"][0] = 0.0
    with pytest.raises(runtime.RuntimeRefused, match="derivation"):
        runtime.validate_complete_row(drifted)
    drifted = json.loads(json.dumps(row))
    drifted["work"]["total_candidate_worlds"] += 1
    with pytest.raises(runtime.RuntimeRefused, match="work accounting"):
        runtime.validate_complete_row(drifted)


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda row: row["selection"].__setitem__("seed", 0), "fold seed"),
    (lambda row: row["selection"]["sampler"].__setitem__("accepted", 29),
     "sampler work"),
    (lambda row: row["reference"]["work"].__setitem__(
        "total_rollouts", 1), "search-free reference"),
    (lambda row: row["candidate_diagnostics"].__setitem__(
        "human_in_live_ballot", False), "diagnostics"),
    (lambda row: row["report"]["actions"][0].__setitem__(
        "sources", ["human_action"]), "report raw/utility"),
])
def test_complete_row_rejects_identity_and_fold_mutations(
        mutate, message: str) -> None:
    row = _complete_row()
    mutate(row)
    with pytest.raises(runtime.RuntimeRefused, match=message):
        runtime.validate_complete_row(row)


def test_searched_reference_record_reconciles_exact_production_dose() -> None:
    candidates = [
        {"cards": ["H3"],
         "sources": ["human_action", "live_production_ballot"]},
        {"cards": ["H4"], "sources": ["live_production_ballot"]},
    ]
    row = {
        "split": "DESIGN", "surface_type": "play", "replay_key": "x",
        "reference": {
            "seed": ctrl.seed_for(
                ctrl.DESIGN.REFERENCE_WORLD_DOMAIN, "DESIGN", "x", "play",
                "live-report-lcb-root"),
            "action": ["H3"],
            "candidates": [["H3"], ["H4"]],
            "candidate_count": 2,
            "reason": "report_lcb_below_min_gain",
            "raw_winner_index": 1,
            "report_candidate_index": 1,
            "played_index": 0,
            "selection_means": [0.0, 1.0],
            "report": {
                "gap": -0.5, "se": 0.1, "worlds": 300,
                "attempts": 300, "rejected": 0, "complete": True,
                "critical": 1.70, "statistic": -0.67,
                "min_gain": 0.0, "rule": "lcb",
            },
            "work": {
                "selection_rollouts": 60, "report_rollouts": 600,
                "total_rollouts": 660, "complete": True,
            },
            "sampler_counters": {
                "sample_attempts": 330, "accepted_worlds": 330,
                "failed_worlds": 0, "rejected_worlds": 0,
                "impossible_worlds": 0,
            },
        },
    }
    assert runtime._validate_reference_record(row, candidates) == 660
    row["reference"]["work"]["total_rollouts"] = 659
    with pytest.raises(runtime.RuntimeRefused, match="reference work"):
        runtime._validate_reference_record(row, candidates)


def test_refused_row_cannot_carry_outcomes_or_utility() -> None:
    refused = {
        "schema": "human-h0-counterfactual-row-v1",
        "status": "REFUSED_SCORE_FREE",
        "row_key": "DESIGN|play|x",
        "split": "DESIGN",
        "surface_type": "play",
        "replay_key": "x",
        "deal_key": "deal-x",
        "player_id": "p",
        "surface": "lead",
        "phase": "early",
        "role": "attacker",
        "reason_class": "RuntimeRefused",
        "reason_sha256": "a" * 64,
        "attempted_work": runtime.RowWorkLedger("play").snapshot(),
        "utility_published": False,
        "outcomes_published": False,
    }
    runtime.validate_complete_row(refused)
    leaked = dict(refused, estimands={})
    with pytest.raises(runtime.RuntimeRefused, match="leaked"):
        runtime.validate_complete_row(leaked)


def test_refused_row_preserves_exact_partial_work_without_outcomes() -> None:
    ledger = runtime.RowWorkLedger("play")
    ledger.enter("selection-sampling")
    ledger.record_sampler("selection", {
        "requested": 30,
        "accepted": 12,
        "attempts": 1_200,
        "attempt_cap": 1_200,
        "counters": {
            "sample_attempts": 1_200,
            "accepted_worlds": 12,
            "failed_worlds": 1_188,
            "rejected_worlds": 7,
            "impossible_worlds": 0,
        },
        "world_keys_sha256": "b" * 64,
    })
    row = runtime._refusal({
        "split": "DESIGN", "surface_type": "play", "replay_key": "x",
        "deal_key": "deal-x", "player_id": "p", "surface": "lead",
        "phase": "early", "role": "attacker",
    }, runtime.RuntimeRefused("underfilled"), ledger)
    runtime.validate_complete_row(row)
    assert row["attempted_work"]["samplers"]["selection"]["accepted"] == 12
    assert "utilities" not in json.dumps(row, sort_keys=True)


def test_incomplete_aggregate_suppresses_all_utility_metrics() -> None:
    packet = {
        "producer": {"git": "a" * 40},
        "schedule": {"schedule_sha256": "b" * 64},
    }
    complete = _complete_row()
    refused = runtime._refusal({
        "split": "AUDIT", "surface_type": "play", "replay_key": "y",
        "deal_key": "deal-y", "player_id": "p2", "surface": "follow",
        "phase": "late", "role": "defender",
    }, runtime.RuntimeRefused("short fold"))
    shard = {"shard_index": 0, "shard_sha256": "c" * 64,
             "rows": [complete, refused]}
    aggregate = runtime.aggregate_payload(packet, "d" * 64, [shard])
    assert aggregate["status"] == "REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY"
    assert aggregate["diagnostic_utility_published"] is False
    assert "metrics" not in aggregate
    assert aggregate["strength_claim"] is False
    assert aggregate["production_promotion"] is False


def test_controller_authority_and_score_free_preflight_cannot_widen() -> None:
    expected = {
        "execution_runtime": {
            "environment": {
                "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"},
            "experimental_sampler_flags": [],
            "fast_engine": True,
            "fast_router_sha256": "a" * 64,
            "compiled_fast_binary_sha256": "b" * 64,
        },
        "result_contract": {
            "durable_one_shot_admission_slot":
                ctrl.admission_slot_logical_path(),
            "admission_slot_published_before_receipt": True,
            "receipt_deletion_cannot_reissue": True,
            "admission_slot_gitignored": True,
            "admit_then_runtime_reopen_required": True,
            "unrelated_git_dirt_refused": True,
        },
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "outcomes_computed": False,
            "counterfactual_execution_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
        "score_free_preflight": {
            "worlds_sampled": 0,
            "candidate_world_rollouts": 0,
            "outcomes_computed": False,
        },
    }
    assert ctrl.packet_problems(expected, expected) == []
    widened = json.loads(json.dumps(expected))
    widened["authority"]["counterfactual_execution_authorized"] = True
    problems = ctrl.packet_problems(widened, expected)
    assert "controller authority widened" in problems
    relaxed = json.loads(json.dumps(expected))
    relaxed["execution_runtime"]["environment"][
        "SHENGJI_REQUIRE_VOIDS"] = "0"
    assert "execution runtime contract drift" in ctrl.packet_problems(
        relaxed, expected)
    reusable = json.loads(json.dumps(expected))
    reusable["result_contract"]["receipt_deletion_cannot_reissue"] = False
    assert "one-shot admission contract drift" in ctrl.packet_problems(
        reusable, expected)


def test_execution_runtime_requires_fast_strict_voids_and_no_experiments(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHENGJI_FAST", raising=False)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(ctrl.ControllerRefused, match="SHENGJI_FAST"):
        ctrl.require_execution_runtime()

    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS", raising=False)
    with pytest.raises(ctrl.ControllerRefused, match="SHENGJI_REQUIRE_VOIDS"):
        ctrl.require_execution_runtime()

    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv("SHENGJI_UNIFORM_DEAL", "1")
    with pytest.raises(ctrl.ControllerRefused, match="experimental"):
        ctrl.require_execution_runtime()
    monkeypatch.delenv("SHENGJI_UNIFORM_DEAL")

    contract = ctrl.require_execution_runtime()
    assert contract["fast_engine"] is True
    assert contract["environment"] == {
        "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"}


def test_runtime_packet_open_is_wired_to_strict_runtime_gate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_runtime() -> dict:
        raise runtime.CTRL.ControllerRefused(
            "synthetic strict-runtime refusal")

    monkeypatch.setattr(
        runtime.CTRL, "require_execution_runtime", refuse_runtime)
    with pytest.raises(runtime.RuntimeRefused, match="strict-runtime"):
        runtime._controller_packet(tmp_path / "missing.json")


def _admission_packet() -> dict:
    return {
        "producer": {"git": "a" * 40},
        "packet_sha256": "b" * 64,
        "schedule": {"schedule_sha256": "c" * 64},
        "inputs": {"fixture": "d" * 64},
        "execution_runtime": {
            "fast_router_sha256": "e" * 64,
            "compiled_fast_binary_sha256": "f" * 64,
        },
    }


def _patch_admission_dependencies(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, packet: dict
) -> tuple[Path, Path, Path]:
    monkeypatch.setattr(runtime, "REPO", tmp_path)
    monkeypatch.setattr(
        runtime, "_controller_packet", lambda *_args, **_kwargs: packet)
    monkeypatch.setattr(
        runtime, "_validate_current_inputs", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        runtime, "_review_claim", lambda *_args, **_kwargs: {
            "one_counterfactual_execution_authorized": True})
    namespace = (tmp_path / "server" / "runs" / "logs" / ctrl.RUN_ID)
    receipt = namespace / "execution-receipt.json"
    slot = tmp_path / ctrl.admission_slot_logical_path()
    return namespace, receipt, slot


def _admit_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                   packet: dict, namespace: Path, receipt: Path) -> dict:
    review = tmp_path / "review.md"
    review.write_text("review\n")
    return runtime.admit(
        packet_path=tmp_path / "controller-packet.json",
        expected_packet_sha256="1" * 64,
        review_record=review,
        receipt_path=receipt,
        namespace=namespace,
        design_path=tmp_path / "design.json",
        corpus=tmp_path / "corpus",
        source_root=tmp_path / "source",
        source_manifest=tmp_path / "source-manifest.json",
        v11_checkpoint=tmp_path / "model.npz",
    )


def test_admission_slot_survives_receipt_deletion_and_blocks_reissue(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _admission_packet()
    namespace, receipt, slot = _patch_admission_dependencies(
        tmp_path, monkeypatch, packet)
    admitted = _admit_fixture(
        tmp_path, monkeypatch, packet, namespace, receipt)
    assert receipt.is_file()
    assert slot.is_file()
    assert admitted["admission_slot"] == str(slot.resolve())
    monkeypatch.setattr(
        runtime, "_expected_review_claim", lambda *_args, **_kwargs: {
            "one_counterfactual_execution_authorized": True})
    assert runtime._receipt(
        receipt, ctrl.sha256_file(receipt), packet, "1" * 64) == admitted
    receipt.unlink()
    with pytest.raises(runtime.RuntimeRefused, match="already consumed"):
        _admit_fixture(tmp_path, monkeypatch, packet, namespace, receipt)


def test_receipt_publication_failure_still_consumes_admission(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _admission_packet()
    namespace, receipt, slot = _patch_admission_dependencies(
        tmp_path, monkeypatch, packet)
    original_publish = runtime.CTRL.publish_exclusive

    def fail_receipt(path: Path, payload: dict) -> None:
        if path.resolve() == receipt.resolve():
            raise OSError("synthetic receipt publication failure")
        original_publish(path, payload)

    monkeypatch.setattr(runtime.CTRL, "publish_exclusive", fail_receipt)
    with pytest.raises(OSError, match="synthetic receipt"):
        _admit_fixture(tmp_path, monkeypatch, packet, namespace, receipt)
    assert slot.is_file()
    assert not receipt.exists()
    with pytest.raises(runtime.RuntimeRefused, match="already consumed"):
        _admit_fixture(tmp_path, monkeypatch, packet, namespace, receipt)


def _init_runtime_git_fixture(tmp_path: Path) -> str:
    (tmp_path / ".gitignore").write_text(
        "logs/\nserver/runs/locks/\n")
    (tmp_path / "tracked.txt").write_text("clean\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "runtime-test@example.invalid"],
        cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Runtime Test"], cwd=tmp_path,
        check=True)
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.txt"], cwd=tmp_path,
        check=True)
    subprocess.run(
        ["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        capture_output=True, text=True).stdout.strip()


def test_real_admit_then_packet_reopen_ignores_only_durable_slot(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: admission must not make every later runtime call refuse."""
    head = _init_runtime_git_fixture(tmp_path)
    monkeypatch.setattr(ctrl, "REPO", tmp_path)
    monkeypatch.setattr(runtime, "REPO", tmp_path)
    monkeypatch.setattr(runtime.CTRL, "REPO", tmp_path)
    execution_runtime = {
        "fast_engine": True,
        "environment": {
            "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"},
        "experimental_sampler_flags": [],
        "fast_router_sha256": "e" * 64,
        "compiled_fast_binary_sha256": "f" * 64,
    }
    monkeypatch.setattr(
        runtime.CTRL, "require_execution_runtime", lambda: execution_runtime)
    monkeypatch.setattr(
        runtime, "_validate_current_inputs", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        runtime, "_review_claim", lambda *_args, **_kwargs: {
            "one_counterfactual_execution_authorized": True})

    namespace = (tmp_path / "server" / "runs" / "logs" / ctrl.RUN_ID)
    namespace.mkdir(parents=True)
    packet_path = namespace / "controller-packet.json"
    review_path = namespace / "review.md"
    receipt_path = namespace / "execution-receipt.json"
    packet = {
        "schema": ctrl.SCHEMA,
        "packet_id": ctrl.PACKET_ID,
        "run_id": ctrl.RUN_ID,
        "producer": {"git": head},
        "inputs": {"fixture": "d" * 64},
        "schedule": {"schedule_sha256": "c" * 64},
        "execution_runtime": execution_runtime,
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "outcomes_computed": False,
            "counterfactual_execution_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = ctrl.sha256_bytes(ctrl.canonical_json(packet))
    packet_path.write_bytes(ctrl.canonical_json(packet))
    packet_file_sha = ctrl.sha256_file(packet_path)
    review_path.write_text("review\n")

    runtime.admit(
        packet_path=packet_path,
        expected_packet_sha256=packet_file_sha,
        review_record=review_path,
        receipt_path=receipt_path,
        namespace=namespace,
        design_path=tmp_path / "design.json",
        corpus=tmp_path / "corpus",
        source_root=tmp_path / "source",
        source_manifest=tmp_path / "source-manifest.json",
        v11_checkpoint=tmp_path / "model.npz",
    )
    assert (tmp_path / ctrl.admission_slot_logical_path()).is_file()
    assert runtime.CTRL._git(
        "status", "--porcelain", "--untracked-files=all") == ""
    assert runtime._controller_packet(packet_path, packet_file_sha) == packet

    (tmp_path / "unexpected.txt").write_text("not runtime state\n")
    with pytest.raises(runtime.RuntimeRefused, match="dirty tree"):
        runtime._controller_packet(packet_path, packet_file_sha)
    (tmp_path / "unexpected.txt").unlink()
    (tmp_path / "tracked.txt").write_text("modified\n")
    with pytest.raises(runtime.RuntimeRefused, match="dirty tree"):
        runtime._controller_packet(packet_path, packet_file_sha)
