from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/s4_capture_generation_replay.py"
SPEC = importlib.util.spec_from_file_location("s4_generation_replay", SCRIPT)
assert SPEC and SPEC.loader
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def test_target_identity_is_the_frozen_score_free_v2() -> None:
    assert replay.TARGET_GIT == \
        "1b35fb7c6234fb6022181b54ce8210c796cc35c3"
    assert replay.TARGET_STATES_SHA256 == \
        "4538be8573a4d4bcf50524afe83c5dac25c5269b3ed95ab15f645343d0ff6b5f"
    assert replay.TARGET_MATERIAL_SHA256 == \
        "5eeb1b507efc6645c7121fb9214b3e269f48fd251d815b7b029eabffa385c6a8"
    replay.verify_target_material()


def test_independent_allocator_keeps_first_trigger_per_role(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class Round:
        def __init__(self, role: str):
            self.role = role

        def is_attacker(self, _seat: int) -> bool:
            return self.role == "attacker"

    found = {
        10: (Round("defender"), 0, ["D2"], ["D5"], {"delta": {}}),
        12: (Round("defender"), 0, ["D3"], ["D10"], {"delta": {}}),
        13: (Round("attacker"), 1, ["H2"], ["H5"], {"delta": {}}),
        14: (Round("defender"), 0, ["D4"], ["DK"], {"delta": {}}),
        15: (Round("attacker"), 1, ["H3"], ["H10"], {"delta": {}}),
    }
    monkeypatch.setattr(replay.S4, "_drive_to_trigger",
                        lambda seed: found.get(seed))
    monkeypatch.setattr(
        replay.S4, "state_record",
        lambda rnd, _seat, seed, null, treatment, _telemetry: {
            "seed": seed, "role": rnd.role,
            "null": null, "treatment": treatment,
        })
    result = replay.regenerate_population(
        seed0=10, max_deals=20,
        role_quota={"attacker": 2, "defender": 2}, progress=False)
    assert result["deals_scanned"] == 6
    assert result["accepted_by_role"] == {"defender": 2, "attacker": 2}
    assert result["observed_triggers_by_role"] == {
        "defender": 3, "attacker": 2}
    assert [row["seed"] for row in result["states"]] == [10, 12, 13, 15]


def test_regeneration_underfill_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay.S4, "_drive_to_trigger", lambda _seed: None)
    with pytest.raises(replay.GenerationReplayError, match="underfilled"):
        replay.regenerate_population(
            seed0=1, max_deals=3,
            role_quota={"attacker": 1, "defender": 1}, progress=False)
