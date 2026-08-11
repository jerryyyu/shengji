from __future__ import annotations

import copy

import pytest

from shengji.rl import stage_c_state_capture as CAPTURE
from shengji.rl import stage_c_state_screen as SCREEN
from test_stage_c_state_screen import _factories, _replay, _state


def _candidate(seed: int, phase: str, role: str):
    return _state(
        phase=phase, role=role, seed=seed,
        state_id=f"fresh:{seed}"), "eligible"


def _selector(state):
    treatment, null, champion, _seen = _factories()
    return SCREEN.select_state(
        state, replay=_replay,
        treatment_factory=treatment,
        matched_null_factory=null,
        champion_factory=champion)


def test_scan_population_freezes_exact_decisions_without_evaluation() -> None:
    progress = []
    result = CAPTURE.scan_population(
        seed0=2_000_000, scan_deals=512, forbidden_deal_seeds=[],
        candidate=_candidate, selector=_selector,
        progress=lambda scanned, counts: progress.append((scanned, counts)))
    CAPTURE.validate_population(result, forbidden_deal_seeds=[])
    assert result["complete"] is True
    assert result["deals_scanned"] == 256
    assert result["selected_states"] == 256
    assert result["cell_counts"] == {
        cell: 64 for cell in SCREEN.CELL_KEYS}
    assert result["selection_states_attempted"] == 256
    assert result["evaluation_folds_opened"] == 0
    assert result["evaluation_launch_authorized"] is False
    assert all(entry["selection"]["evaluation_opened"] is False
               for entry in result["entries"])
    assert progress[-1][1] == {cell: 64 for cell in SCREEN.CELL_KEYS}


def test_scan_population_skips_forbidden_and_ineligible_deals() -> None:
    forbidden = [3_000_000]

    def selector(state):
        if state["seed"] % 8 == 4:
            raise SCREEN.StageCStateIneligible("model_kept_live_incumbent")
        return _selector(state)

    result = CAPTURE.scan_population(
        seed0=3_000_000, scan_deals=1_024,
        forbidden_deal_seeds=forbidden,
        candidate=_candidate, selector=selector)
    CAPTURE.validate_population(result, forbidden_deal_seeds=forbidden)
    assert result["complete"] is True
    assert result["deals_scanned"] > 256
    assert result["forbidden_deal_overlap"] == 0
    assert all(entry["state"]["seed"] not in forbidden
               for entry in result["entries"])
    assert any("not_triggered" in key for key in result["dispositions"])
    assert result["selection_states_attempted"] > result["selected_states"]


def test_scan_population_reports_finite_insufficient_supply() -> None:
    def never(_state):
        raise SCREEN.StageCStateIneligible("outside_scope")

    result = CAPTURE.scan_population(
        seed0=4_000_000, scan_deals=256, forbidden_deal_seeds=[],
        candidate=_candidate, selector=never)
    CAPTURE.validate_population(result, forbidden_deal_seeds=[])
    assert result["complete"] is False
    assert result["decision"] == "INSUFFICIENT_TRIGGER_SUPPLY"
    assert result["selected_states"] == 0


def test_scan_population_refuses_candidate_cell_or_selector_failure() -> None:
    def wrong(seed, _phase, _role):
        return _state(
            phase="mid", role="attacker", seed=seed,
            state_id=f"wrong:{seed}"), "eligible"

    with pytest.raises(CAPTURE.StageCStateCaptureError,
                       match="assigned deal/cell"):
        CAPTURE.scan_population(
            seed0=5_000_000, scan_deals=256,
            forbidden_deal_seeds=[], candidate=wrong, selector=_selector)

    def broken(_state):
        raise SCREEN.StageCStateScreenError("bad work")

    with pytest.raises(CAPTURE.StageCStateCaptureError,
                       match="protected selection failed"):
        CAPTURE.scan_population(
            seed0=5_000_000, scan_deals=256,
            forbidden_deal_seeds=[], candidate=_candidate, selector=broken)


def test_population_validator_recomputes_nested_hashes_and_freshness() -> None:
    result = CAPTURE.scan_population(
        seed0=6_000_000, scan_deals=256, forbidden_deal_seeds=[],
        candidate=_candidate, selector=_selector)
    forged = copy.deepcopy(result)
    forged["entries"][0]["selection"]["evaluation_opened"] = True
    forged["entries"][0]["selection"]["selection_sha256"] = \
        SCREEN._self_hash(
            forged["entries"][0]["selection"], "selection_sha256")
    forged["entries"][0]["entry_sha256"] = CAPTURE._self_hash(
        forged["entries"][0], "entry_sha256")
    forged["population_sha256"] = CAPTURE._self_hash(
        forged, "population_sha256")
    with pytest.raises(CAPTURE.StageCStateCaptureError,
                       match="screen contract"):
        CAPTURE.validate_population(forged, forbidden_deal_seeds=[])

    with pytest.raises(CAPTURE.StageCStateCaptureError,
                       match="freshness/quota"):
        CAPTURE.validate_population(
            result, forbidden_deal_seeds=[result["entries"][0]["state"]["seed"]])


def test_population_validator_reconciles_dispositions_and_seed_cells() -> None:
    result = CAPTURE.scan_population(
        seed0=7_000_000, scan_deals=256, forbidden_deal_seeds=[],
        candidate=_candidate, selector=_selector)
    forged = copy.deepcopy(result)
    key = next(iter(forged["dispositions"]))
    forged["dispositions"][key] += 1
    forged["population_sha256"] = CAPTURE._self_hash(
        forged, "population_sha256")
    with pytest.raises(CAPTURE.StageCStateCaptureError,
                       match="freshness/quota"):
        CAPTURE.validate_population(forged, forbidden_deal_seeds=[])

    forged = copy.deepcopy(result)
    first = forged["entries"][0]
    first["state"]["seed"] += 1
    first["selection"]["deal_seed"] += 1
    first["selection"]["policy_seed"] = SCREEN._seed({
        "state_id": first["selection"]["state_id"],
        "seed": first["selection"]["deal_seed"],
    }, "decision")
    first["selection"]["selection_sha256"] = SCREEN._self_hash(
        first["selection"], "selection_sha256")
    first["entry_sha256"] = CAPTURE._self_hash(first, "entry_sha256")
    forged["population_sha256"] = CAPTURE._self_hash(
        forged, "population_sha256")
    with pytest.raises(CAPTURE.StageCStateCaptureError,
                       match="freshness/quota"):
        CAPTURE.validate_population(forged, forbidden_deal_seeds=[])
