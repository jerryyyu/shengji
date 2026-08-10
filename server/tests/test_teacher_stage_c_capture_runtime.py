from __future__ import annotations

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


def test_cell_assignment_is_deterministic_and_in_split() -> None:
    packet = _packet()
    first = [runtime._cell_for_seed(packet, "DESIGN", seed)["cell_id"]
             for seed in range(170_000_000, 170_001_000)]
    second = [runtime._cell_for_seed(packet, "DESIGN", seed)["cell_id"]
              for seed in range(170_000_000, 170_001_000)]
    assert first == second
    assert len(set(first)) > 10
    assert all(value.startswith("DESIGN:") for value in first)


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
