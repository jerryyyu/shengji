from __future__ import annotations

import copy
import importlib.util
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "teacher_stage_c_capture_runtime.py")
SPEC = importlib.util.spec_from_file_location("stage_c_capture_runtime", SCRIPT)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
ctrl = runtime.CTRL


def _repo() -> Path:
    return Path(__file__).parents[2]


def _base() -> dict:
    return ctrl.load_json(
        _repo() / "server/runs/logs/teacher-v3-hard-tail-stage-c-design-v1/"
        "design_packet.json")


def _packet() -> dict:
    return {"schedule": ctrl.build_schedule(_base())}


def _real_parent_packet() -> dict:
    base_path, rebind_path, h0_path, s3c_path, _assets = (
        runtime._logical_inputs())
    base = ctrl.load_json(base_path)
    rebind = ctrl.load_json(rebind_path)
    h0 = ctrl.load_json(h0_path)
    s3c = ctrl.load_json(s3c_path)
    return {
        "parents": {
            "base_stage_c": {
                "internal_sha256": base["packet_sha256"],
                "curriculum_commitments": (
                    ctrl.REBIND.curriculum_commitments(base)),
            },
            "controller_rebind": {
                "internal_sha256": rebind["packet_sha256"],
            },
            "h0_v3": {"internal_sha256": h0["packet_sha256"]},
            "s3c_v2": {"internal_sha256": s3c["packet_sha256"]},
        },
        "inputs": {"v11pair": h0["inputs"]["v11pair"]},
    }


def _valid_shard() -> tuple[dict, dict, str]:
    schedule = copy.deepcopy(ctrl.build_schedule(_base()))
    seed = 170_000_000
    while True:
        cell = runtime._cell_for_seed({"schedule": schedule}, "DESIGN", seed)
        if cell["stratum"] == "ordinary_anchor":
            break
        seed += 1
    shard_schedule = copy.deepcopy(schedule["shards"][0])
    shard_schedule.update({
        "seed_start": seed, "scan_deals": 1, "first_seed": seed,
        "seed_stride": 8, "seed_count": 1,
    })
    schedule["shards"][0] = shard_schedule
    schedule["scan_deals"] = 1
    schedule["schedule_sha256"] = ctrl.sha256_bytes(ctrl.canonical_json({
        key: value for key, value in schedule.items()
        if key != "schedule_sha256"
    }))
    packet = {
        "external_sha256": "a" * 64,
        "producer": {"git": "b" * 40},
        "schedule": schedule,
    }
    actor_identity = runtime._actor_identity()
    surface_type = str(cell["surface_type"])
    seat = 0
    ply = 0
    state_id = runtime._canonical_state_id(
        split="DESIGN", seed=seed, surface_type=surface_type,
        seat=seat, ply=ply)
    state = {
        "schema": "teacher-stage-c-replay-state-v1",
        "experiment_id": ctrl.EXPERIMENT_ID,
        "capture_packet_id": ctrl.PACKET_ID,
        "split": "DESIGN",
        "surface_type": surface_type,
        "stratum": cell["stratum"],
        "cell_id": cell["cell_id"],
        "seed": seed,
        "seat": seat,
        "state_id": state_id,
        "actor_policy": ctrl.ACTOR_POLICY,
        "actor_identity": actor_identity,
        "actor_streams": [{
            "seat": actor_seat,
            "seed": runtime._seed(
                ctrl.EXPERIMENT_ID, "DESIGN", seed, "actor", actor_seat,
                ctrl.ACTOR_POLICY),
            "policy": ctrl.ACTOR_POLICY,
        } for actor_seat in range(4)],
        "setup": {},
        "plays": [],
        "ply": ply,
        "phase": "early" if cell["phase"] == "any" else cell["phase"],
        "surface": cell["surface"],
        "role": cell["role"],
        "selection_priority": runtime._priority(
            "DESIGN", str(cell["cell_id"]), seed, state_id),
        "candidates": [{"cards": ["C2"], "sources": ["synthetic"]}],
    }
    scan_records = [runtime._scan_record(
        1, seed, str(cell["cell_id"]), "eligible", state)]
    diagnostic_records = [runtime._diagnostic_record(
        cell_id=str(cell["cell_id"]), state=state,
        status="eligible", eligible=True, diagnostic=None)]
    witness = {
        "schema": ctrl.GENERATION_WITNESS_SCHEMA,
        "complete": True,
        "scan_records": scan_records,
        "scan_records_sha256": runtime._records_sha256(scan_records),
        "diagnostic_records": diagnostic_records,
        "diagnostic_records_sha256": runtime._records_sha256(
            diagnostic_records),
    }
    witness["witness_sha256"] = runtime._self_hash(
        witness, "witness_sha256")
    counts, cell_counts, work = runtime._reconcile_generation_witness(
        packet, shard_schedule, witness, [state])
    receipt = "c" * 64
    shard = {
        "schema": ctrl.SHARD_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet["external_sha256"],
        "capture_receipt_sha256": receipt,
        "schedule_sha256": schedule["schedule_sha256"],
        "shard_index": 0,
        "split": "DESIGN",
        "schedule": shard_schedule,
        "actor_identity": actor_identity,
        "scan": {
            "seed_count": 1, "first_seed": seed, "seed_stride": 8,
            "stop_exclusive": seed + 1,
            "ledger_sha256": witness["scan_records_sha256"],
            "generation_witness_sha256": witness["witness_sha256"],
        },
        "counts": counts,
        "cell_counts": cell_counts,
        "uncertainty_work": work,
        "generation_witness": witness,
        "retained_states": [state],
        "retained_state_ids_sha256": ctrl.sha256_bytes(
            ctrl.canonical_json([state_id])),
        "complete": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    shard["shard_sha256"] = runtime._self_hash(shard, "shard_sha256")
    return packet, shard, receipt


def _rehash_witness_and_shard(shard: dict) -> None:
    witness = shard["generation_witness"]
    witness["scan_records_sha256"] = runtime._records_sha256(
        witness["scan_records"])
    witness["diagnostic_records_sha256"] = runtime._records_sha256(
        witness["diagnostic_records"])
    witness["witness_sha256"] = runtime._self_hash(
        witness, "witness_sha256")
    shard["scan"]["ledger_sha256"] = witness["scan_records_sha256"]
    shard["scan"]["generation_witness_sha256"] = witness["witness_sha256"]
    shard["retained_state_ids_sha256"] = ctrl.sha256_bytes(
        ctrl.canonical_json([
            state["state_id"] for state in shard["retained_states"]
        ]))
    shard["shard_sha256"] = runtime._self_hash(shard, "shard_sha256")


def test_cell_assignment_is_deterministic_and_in_split() -> None:
    packet = _packet()
    first = [runtime._cell_for_seed(packet, "DESIGN", seed)["cell_id"]
             for seed in range(170_000_000, 170_001_000)]
    second = [runtime._cell_for_seed(packet, "DESIGN", seed)["cell_id"]
              for seed in range(170_000_000, 170_001_000)]
    assert first == second
    assert len(set(first)) > 10
    assert all(value.startswith("DESIGN:") for value in first)


def test_terminal_shard_validation_reconstructs_complete_witness() -> None:
    packet, shard, receipt = _valid_shard()
    reopened = json.loads(ctrl.canonical_json(shard))
    runtime.validate_shard(reopened, packet, receipt, 0)


def test_terminal_shard_rejects_predeal_cell_retag() -> None:
    packet, shard, receipt = _valid_shard()
    state = shard["retained_states"][0]
    correct = runtime._cell_for_seed(
        packet, "DESIGN", int(state["seed"]))
    wrong = next(cell for cell in packet["schedule"]["quota_cells"]["DESIGN"]
                 if cell["surface_type"] == correct["surface_type"]
                 and cell["phase"] == correct["phase"]
                 and cell["role"] == correct["role"]
                 and cell["surface"] == correct["surface"]
                 and cell["cell_id"] != correct["cell_id"])
    state["cell_id"] = wrong["cell_id"]
    state["stratum"] = wrong["stratum"]
    priority = runtime._priority(
        "DESIGN", wrong["cell_id"], state["seed"], state["state_id"])
    state["selection_priority"] = priority
    scan = shard["generation_witness"]["scan_records"][0]
    scan["cell_id"] = wrong["cell_id"]
    scan["selection_priority"] = priority
    diagnostic = shard["generation_witness"]["diagnostic_records"][0]
    diagnostic["cell_id"] = wrong["cell_id"]
    diagnostic["selection_priority"] = priority
    _rehash_witness_and_shard(shard)
    with pytest.raises(runtime.RuntimeRefused,
                       match="cell assignment|schedule/cell"):
        runtime.validate_shard(shard, packet, receipt, 0)


def test_terminal_shard_rejects_fabricated_state_id_or_priority() -> None:
    packet, shard, receipt = _valid_shard()
    mutated = copy.deepcopy(shard)
    state = mutated["retained_states"][0]
    state["state_id"] += ":forged"
    scan = mutated["generation_witness"]["scan_records"][0]
    scan["state_id"] = state["state_id"]
    diagnostic = mutated["generation_witness"]["diagnostic_records"][0]
    diagnostic["state_id"] = state["state_id"]
    _rehash_witness_and_shard(mutated)
    with pytest.raises(runtime.RuntimeRefused, match="canonical state ID"):
        runtime.validate_shard(mutated, packet, receipt, 0)

    mutated = copy.deepcopy(shard)
    mutated["retained_states"][0]["selection_priority"] = "0" * 64
    mutated["generation_witness"]["scan_records"][0][
        "selection_priority"] = "0" * 64
    mutated["generation_witness"]["diagnostic_records"][0][
        "selection_priority"] = "0" * 64
    _rehash_witness_and_shard(mutated)
    with pytest.raises(runtime.RuntimeRefused, match="selection priority"):
        runtime.validate_shard(mutated, packet, receipt, 0)

    mutated = copy.deepcopy(shard)
    state = mutated["retained_states"][0]
    wrong_surface = "bury" if state["surface_type"] == "play" else "play"
    wrong_state_id = runtime._canonical_state_id(
        split=state["split"], seed=state["seed"],
        surface_type=wrong_surface, seat=state["seat"], ply=state["ply"])
    wrong_priority = runtime._priority(
        state["split"], state["cell_id"], state["seed"], wrong_state_id)
    scan = mutated["generation_witness"]["scan_records"][0]
    scan.update({
        "surface_type": wrong_surface,
        "state_id": wrong_state_id,
        "selection_priority": wrong_priority,
    })
    diagnostic = mutated["generation_witness"]["diagnostic_records"][0]
    diagnostic.update({
        "state_id": wrong_state_id,
        "selection_priority": wrong_priority,
    })
    _rehash_witness_and_shard(mutated)
    with pytest.raises(runtime.RuntimeRefused, match="surface assignment"):
        runtime._reconcile_generation_witness(
            packet, mutated["schedule"], mutated["generation_witness"],
            mutated["retained_states"])


def test_terminal_shard_rejects_fabricated_actor_identity() -> None:
    packet, shard, receipt = _valid_shard()
    fake = {"policy": ctrl.ACTOR_POLICY, "sources": {},
            "identity_sha256": "0" * 64}
    shard["actor_identity"] = fake
    shard["retained_states"][0]["actor_identity"] = fake
    _rehash_witness_and_shard(shard)
    with pytest.raises(runtime.RuntimeRefused, match="actor identity"):
        runtime.validate_shard(shard, packet, receipt, 0)


def test_terminal_shard_rejects_incomplete_or_fabricated_scan_ledger() -> None:
    packet, shard, receipt = _valid_shard()
    missing = copy.deepcopy(shard)
    missing["generation_witness"]["scan_records"].clear()
    _rehash_witness_and_shard(missing)
    with pytest.raises(runtime.RuntimeRefused, match="seed coverage"):
        runtime.validate_shard(missing, packet, receipt, 0)

    fabricated = copy.deepcopy(shard)
    fabricated["scan"]["ledger_sha256"] = "f" * 64
    fabricated["shard_sha256"] = runtime._self_hash(
        fabricated, "shard_sha256")
    with pytest.raises(runtime.RuntimeRefused, match="scan ledger"):
        runtime.validate_shard(fabricated, packet, receipt, 0)


def test_terminal_shard_rejects_unreconciled_or_negative_work() -> None:
    packet, shard, receipt = _valid_shard()
    negative = copy.deepcopy(shard)
    negative["generation_witness"]["diagnostic_records"][0][
        "candidate_worlds"] = -1
    _rehash_witness_and_shard(negative)
    with pytest.raises(runtime.RuntimeRefused, match="nonnegative integer"):
        runtime.validate_shard(negative, packet, receipt, 0)

    drift = copy.deepcopy(shard)
    drift["counts"]["candidate_eligible"] = -1
    drift["shard_sha256"] = runtime._self_hash(drift, "shard_sha256")
    with pytest.raises(runtime.RuntimeRefused, match="counters drift"):
        runtime.validate_shard(drift, packet, receipt, 0)

    missing = copy.deepcopy(shard)
    missing["generation_witness"]["diagnostic_records"].clear()
    _rehash_witness_and_shard(missing)
    with pytest.raises(runtime.RuntimeRefused, match="population drift"):
        runtime.validate_shard(missing, packet, receipt, 0)


def test_shard_seed_schedule_partitions_exact_split() -> None:
    schedule = ctrl.build_schedule(_base())
    for split_index, split in enumerate(schedule["split_order"]):
        blocks = [set(runtime._shard_seeds(schedule["shards"][
            split_index * 8 + local])) for local in range(8)]
        assert not any(blocks[left] & blocks[right]
                       for left in range(8) for right in range(left + 1, 8))
        union = set().union(*blocks)
        start = _base()["population_contract"]["splits"][split]["seed_start"]
        assert union == set(range(start, start + 250_000))


def test_bury_capture_replays_and_candidate_union_is_exact() -> None:
    base = _base()
    cell = next(cell for cell in ctrl.quota_cells(base)["DESIGN"]
                if cell["surface_type"] == "bury"
                and cell["stratum"] == "ordinary_anchor")
    state, reason = runtime.capture_deal(
        170_000_011, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    assert rnd.phase == "bury"
    net = runtime._load_npnet(str(_repo() / runtime.V11_PATH))
    hydrated, reason = runtime.hydrate_candidates(state, net)
    assert reason == "eligible" and hydrated is not None
    replayed = runtime.replay_state(hydrated)
    runtime._validate_candidates(hydrated, replayed, net)
    assert hydrated["candidates"][0]["sources"]
    assert len(hydrated["candidates"]) <= 33


def test_one_card_exact_late_capture_replays() -> None:
    base = _base()
    cells = [cell for cell in ctrl.quota_cells(base)["DESIGN"]
             if cell["stratum"] == "exact_late_eligible"]
    found = None
    for offset in range(16):
        for cell in cells:
            state, reason = runtime.capture_deal(
                170_010_000 + offset, "DESIGN", cell,
                runtime._actor_identity())
            if state is not None:
                found = state
                break
        if found is not None:
            break
    assert found is not None
    rnd = runtime.replay_state(found)
    assert all(len(hand) == 1 for hand in rnd.hands)
    assert len(rnd.history) >= 12
    assert found["phase"] == "late"


def test_candidate_mutation_is_red() -> None:
    base = _base()
    cell = next(cell for cell in ctrl.quota_cells(base)["DESIGN"]
                if cell["surface_type"] == "bury")
    state, _ = runtime.capture_deal(
        170_000_019, "DESIGN", cell, runtime._actor_identity())
    assert state is not None
    net = runtime._load_npnet(str(_repo() / runtime.V11_PATH))
    hydrated, _ = runtime.hydrate_candidates(state, net)
    assert hydrated is not None
    hydrated["candidates"][0]["cards"] = ["BJ"] * 8
    with pytest.raises(runtime.RuntimeRefused, match="candidate union replay drift"):
        runtime._validate_candidates(hydrated, runtime.replay_state(hydrated), net)


def test_uncertainty_diagnostic_is_exact_and_selection_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRound:
        @staticmethod
        def is_attacker(_seat):
            return True

    class FakeBot:
        MARGIN = 5.0

        def __init__(self):
            self.rng = random.Random(0)
            self.sample_attempts = 0
            self.accepted_worlds = 0
            self.failed_worlds = 0
            self.rejected_worlds = 0
            self.impossible_worlds = 0

        def _sample_hands(self, _rnd, _seat, _mem):
            self.sample_attempts += 1
            self.accepted_worlds += 1
            return (None, None)

        @staticmethod
        def _rollout(_rnd, _seat, _hands, _buried, action):
            return 0.0 if action == ["C2"] else 5.0

        @staticmethod
        def _score(value):
            return value

        @staticmethod
        def _pick_index(_actions, means, indices):
            return max(indices, key=lambda index: means[index])

    monkeypatch.setattr(runtime, "replay_state", lambda _state: FakeRound())
    monkeypatch.setattr(runtime, "Memory", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "make_bot", lambda *_args, **_kwargs: FakeBot())
    diagnostic, reason = runtime.uncertainty_diagnostic({
        "split": "DESIGN", "state_id": "s", "seat": 0,
        "candidates": [{"cards": ["C2"]}, {"cards": ["C3"]}],
    })
    assert reason == "eligible" and diagnostic is not None
    assert diagnostic["worlds"] == 30
    assert diagnostic["candidate_worlds"] == 60
    assert diagnostic["eligible"] is True
    assert diagnostic["may_train_or_label"] is False


def test_uncertainty_underfill_reports_every_failed_attempt(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRound:
        @staticmethod
        def is_attacker(_seat):
            return True

    class FailingBot:
        MARGIN = 5.0

        def __init__(self):
            self.rng = random.Random(0)
            self.sample_attempts = 0
            self.accepted_worlds = 0
            self.failed_worlds = 0
            self.rejected_worlds = 0
            self.impossible_worlds = 0

        def _sample_hands(self, _rnd, _seat, _mem):
            self.sample_attempts += 1
            self.failed_worlds += 1
            return None

    monkeypatch.setattr(runtime, "replay_state", lambda _state: FakeRound())
    monkeypatch.setattr(runtime, "Memory", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "make_bot",
                        lambda *_args, **_kwargs: FailingBot())
    diagnostic, reason = runtime.uncertainty_diagnostic({
        "split": "DESIGN", "state_id": "underfill", "seat": 0,
        "candidates": [{"cards": ["C2"]}, {"cards": ["C3"]}],
    })
    assert reason == "uncertainty_underfilled"
    assert diagnostic is not None
    assert diagnostic["evaluation_complete"] is False
    assert diagnostic["attempts"] == 300
    assert diagnostic["worlds"] == 0
    assert diagnostic["candidate_worlds"] == 0
    assert diagnostic["sampler_counters"] == {
        "sample_attempts": 300,
        "accepted_worlds": 0,
        "failed_worlds": 300,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }


def test_generation_witness_reconciles_underfill_attempt_work() -> None:
    schedule = copy.deepcopy(ctrl.build_schedule(_base()))
    seed = 170_000_000
    while True:
        cell = runtime._cell_for_seed({"schedule": schedule}, "DESIGN", seed)
        if cell["stratum"] == "champion_uncertainty":
            break
        seed += 1
    shard_schedule = copy.deepcopy(schedule["shards"][0])
    shard_schedule.update({
        "seed_start": seed, "scan_deals": 1, "first_seed": seed,
        "seed_stride": 8, "seed_count": 1,
    })
    packet = {"schedule": schedule}
    state_id = runtime._canonical_state_id(
        split="DESIGN", seed=seed, surface_type="play", seat=0, ply=0)
    state = {
        "surface_type": "play", "seat": 0, "ply": 0,
        "state_id": state_id,
        "selection_priority": runtime._priority(
            "DESIGN", str(cell["cell_id"]), seed, state_id),
        "candidates": [{"cards": ["C2"]}, {"cards": ["C3"]}],
    }
    scan_records = [runtime._scan_record(
        1, seed, str(cell["cell_id"]), "eligible", state)]
    diagnostic = {
        "schema": "teacher-stage-c-uncertainty-selection-v1",
        "selection_only": True,
        "may_train_or_label": False,
        "evaluation_complete": False,
        "worlds": 0,
        "attempts": 300,
        "candidate_worlds": 0,
        "sampler_counters": {
            "sample_attempts": 300, "accepted_worlds": 0,
            "failed_worlds": 300, "rejected_worlds": 0,
            "impossible_worlds": 0,
        },
        "means": None,
        "raw_best_index": None,
        "paired_gap_vs_candidate0": None,
        "paired_se_vs_candidate0": None,
        "production_margin": 5.0,
        "margin_window": runtime.UNCERTAINTY_MARGIN_WINDOW,
        "eligible": False,
    }
    diagnostic_records = [runtime._diagnostic_record(
        cell_id=str(cell["cell_id"]), state=state,
        status="uncertainty_underfilled", eligible=False,
        diagnostic=diagnostic)]
    witness = {
        "schema": ctrl.GENERATION_WITNESS_SCHEMA,
        "complete": True,
        "scan_records": scan_records,
        "scan_records_sha256": runtime._records_sha256(scan_records),
        "diagnostic_records": diagnostic_records,
        "diagnostic_records_sha256": runtime._records_sha256(
            diagnostic_records),
    }
    witness["witness_sha256"] = runtime._self_hash(
        witness, "witness_sha256")
    counts, _cells, work = runtime._reconcile_generation_witness(
        packet, shard_schedule, witness, [])
    assert counts["diagnostic_rejected"] == 1
    assert work == {"attempts": 300, "worlds": 0, "candidate_worlds": 0}

    diagnostic["sampler_counters"]["sample_attempts"] = 299
    diagnostic_records[0]["selection_diagnostic"] = diagnostic
    witness["diagnostic_records_sha256"] = runtime._records_sha256(
        diagnostic_records)
    witness["witness_sha256"] = runtime._self_hash(
        witness, "witness_sha256")
    with pytest.raises(runtime.RuntimeRefused,
                       match="sampler counters do not reconcile"):
        runtime._reconcile_generation_witness(
            packet, shard_schedule, witness, [])


def test_real_uncertainty_path_consumes_exact_30_worlds() -> None:
    base = _base()
    cells = [cell for cell in ctrl.quota_cells(base)["DESIGN"]
             if cell["stratum"] == "champion_uncertainty"]
    raw = None
    for offset in range(32):
        for cell in cells:
            state, _reason = runtime.capture_deal(
                190_100_000 + offset, "DESIGN", cell,
                runtime._actor_identity())
            if state is not None:
                raw = state
                break
        if raw is not None:
            break
    assert raw is not None
    net = runtime._load_npnet(str(_repo() / runtime.V11_PATH))
    hydrated, reason = runtime.hydrate_candidates(raw, net)
    assert reason == "eligible" and hydrated is not None
    diagnostic, reason = runtime.uncertainty_diagnostic(hydrated)
    assert diagnostic is not None
    assert reason in {"eligible", "outside_uncertainty_window"}
    assert diagnostic["worlds"] == 30
    assert diagnostic["candidate_worlds"] == 30 * len(hydrated["candidates"])
    assert diagnostic["sampler_counters"]["accepted_worlds"] == 30
    assert diagnostic["sampler_counters"]["failed_worlds"] == 0


def test_parent_files_and_v11_binding_reopen_exactly() -> None:
    runtime._validate_parent_files(_real_parent_packet())


@pytest.mark.parametrize("mutation,match", [
    (("parents", "h0_v3", "internal_sha256"), "parent identity/self-hash"),
    (("inputs", "v11pair", "sha256"), "V11 parent drift"),
])
def test_parent_or_v11_binding_mutation_is_red(
        mutation: tuple[str, ...], match: str) -> None:
    packet = _real_parent_packet()
    target = packet
    for key in mutation[:-1]:
        target = target[key]
    target[mutation[-1]] = "0" * 64
    with pytest.raises(runtime.RuntimeRefused, match=match):
        runtime._validate_parent_files(packet)


def test_parent_file_byte_mutation_is_red(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base_path, rebind_path, h0_path, s3c_path, _assets = (
        runtime._logical_inputs())
    copies = []
    for index, path in enumerate((base_path, rebind_path, h0_path, s3c_path)):
        copy_path = tmp_path / f"{index}-{path.name}"
        shutil.copyfile(path, copy_path)
        copies.append(copy_path)
    copies[2].write_bytes(copies[2].read_bytes() + b"\n")
    monkeypatch.setattr(
        runtime, "_logical_inputs",
        lambda: (*copies, []),
    )
    with pytest.raises(runtime.RuntimeRefused,
                       match="H0-v3 parent external SHA-256 drift"):
        runtime._validate_parent_files(_real_parent_packet())


def _synthetic_dataset_inputs() -> tuple[dict, list[dict]]:
    schedule = ctrl.build_schedule(_base())
    packet = {
        "external_sha256": "a" * 64,
        "producer": {"git": "b" * 40},
        "schedule": schedule,
        "parents": {},
        "result_contract": {
            "required_states": 2048,
            "required_split_states": {"DESIGN": 1024, "CALIB": 512,
                                      "REPORT": 512},
            "required_play_states": 1920,
            "required_bury_states": 128,
        },
    }
    shards = [{
        "shard_index": index, "external_sha256": f"{index:064x}",
        "scan": {"ledger_sha256": f"{index + 100:064x}"},
        "generation_witness": {
            "witness_sha256": f"{index + 200:064x}",
            "diagnostic_records_sha256": f"{index + 300:064x}",
        },
        "retained_states": [],
    } for index in range(24)]
    seed = 170_000_000
    for split_index, split in enumerate(schedule["split_order"]):
        target = shards[split_index * 8]
        for cell in schedule["quota_cells"][split]:
            for rank in range(cell["quota"]):
                state_id = f"{split}:{cell['index']}:{rank}"
                target["retained_states"].append({
                    "split": split,
                    "surface_type": cell["surface_type"],
                    "stratum": cell["stratum"],
                    "cell_id": cell["cell_id"],
                    "seed": seed,
                    "state_id": state_id,
                    "selection_priority": runtime._priority(
                        split, cell["cell_id"], seed, state_id),
                })
                seed += 1
    return packet, shards


def test_dataset_freeze_fills_exact_cells_and_report_audit() -> None:
    packet, shards = _synthetic_dataset_inputs()
    payload = runtime._dataset_payload(packet, "c" * 64, shards)
    assert payload["state_count"] == 2048
    assert payload["split_counts"] == {
        "CALIB": 512, "DESIGN": 1024, "REPORT": 512}
    assert payload["surface_counts"] == {"play": 1920, "bury": 128}
    assert len(payload["report_audit_state_ids"]) == 256
    assert len(set(payload["report_audit_state_ids"])) == 256
    assert payload["labels_authorized"] is False
    assert payload["training_authorized"] is False


def test_dataset_underfill_is_terminal_without_extension() -> None:
    packet, shards = _synthetic_dataset_inputs()
    shards[0]["retained_states"].pop()
    with pytest.raises(runtime.RuntimeRefused,
                       match="TERMINAL_HOLD_NO_EXTENSION"):
        runtime._dataset_payload(packet, "c" * 64, shards)


def test_ignored_admission_reopens_but_unrelated_dirt_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path,
                   check=True)
    (tmp_path / ".gitignore").write_text("server/runs/locks/\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path,
                   check=True)
    slot = tmp_path / "server/runs/locks/test.json"
    slot.parent.mkdir(parents=True)
    slot.write_text("{}\n")
    monkeypatch.setattr(runtime, "REPO", tmp_path)
    runtime._require_clean_tree()
    (tmp_path / "unrelated.txt").write_text("dirty\n")
    with pytest.raises(runtime.RuntimeRefused, match="dirty tree"):
        runtime._require_clean_tree()


def test_runtime_cli_requires_replay_flag() -> None:
    with pytest.raises(runtime.RuntimeRefused, match="every selected-state"):
        runtime.verify_dataset(
            packet_path=Path("missing"), expected_packet_sha256="a" * 64,
            receipt_path=Path("missing"), expected_receipt_sha256="b" * 64,
            shard_paths=[], dataset_path=Path("missing"),
            replay_every_selected_state=False)
