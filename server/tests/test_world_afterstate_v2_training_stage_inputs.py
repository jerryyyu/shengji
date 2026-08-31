from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import dataclasses
import hashlib

import numpy as np
import pytest

import shengji.rl.world_afterstate_v2_training_stage_inputs as inputs
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_continuation import ContinuationOutcomeV2
from shengji.rl.world_afterstate_v2_execution import (
    StageStateV2, StageSupervisorV2,
)
from shengji.rl.world_afterstate_v2_inference import ValueInferenceRootV2
from shengji.rl.world_afterstate_v2_model import collate_world_afterstate_tensors
from shengji.rl.world_afterstate_v2_protocol import (
    StateCandidateV2, TIER_SPECS, build_population_slot_ledger,
)
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingExample,
)
from shengji.rl.belief_contract import canonical_json_bytes


class _Arm:
    def __init__(self, stage: str, variant: int):
        self.stage = stage
        self.variant = variant

    def validate(self):
        return None


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _tensor(seed: int) -> WorldAfterstateTensorsV0:
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    public[seed % PUBLIC_DIM] = 1.0
    return WorldAfterstateTensorsV0(
        public=public,
        history=np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
        world=np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
        perspective=np.array([1.0, 0.0], dtype=np.float32),
    )


def _fit_material(slot, *, suffix: str = "") -> SimpleNamespace:
    if slot.source == "mechanics":
        phase, position, role = "early", "lead", "attacker"
        mechanics_surfaces = (slot.mechanics_surface,)
    else:
        phase, position, role = slot.cell
        mechanics_surfaces = ()
    deal = _hex(f"fit:{slot.slot_sha256}:{suffix}")
    state = StateCandidateV2(
        deal_sha256=deal, slot_sha256=slot.slot_sha256,
        state_sha256=_hex(f"state:{deal}"), source=slot.source,
        split="fit", phase=phase, position=position, role=role,
        trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
        select_subfold=None, mechanics_surfaces=mechanics_surfaces,
        legal_candidate_count=2,
    )
    state.validate()
    return SimpleNamespace(deal_sha256=deal, state=state)


def _fit_rows(material: SimpleNamespace) \
        -> tuple[WorldAfterstateV2TrainingExample, ...]:
    deal = material.deal_sha256
    slot = getattr(material.state, "slot_sha256", _hex(f"{deal}:slot"))
    state = _hex(f"{deal}:state")
    successors = tuple(_hex(f"{deal}:successor:{index}") for index in range(2))
    candidate_set = _hex(canonical_json_bytes({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state,
        "successor_sha256s": list(successors),
    }).decode("ascii"))
    return tuple(
        WorldAfterstateV2TrainingExample(
            deal_sha256=deal, slot_sha256=slot, state_sha256=state,
            candidate_set_sha256=candidate_set, candidate_index=candidate,
            protected_incumbent=candidate == 0,
            successor_sha256=successors[candidate],
            continuation_sha256=_hex(f"{deal}:crn:{replica}"),
            replica=replica, source=material.state.source, split="fit",
            role="attacker", phase="early", position="lead", trump_rank="2",
            trump_mode="S", points_bucket="0-39", tensors=_tensor(candidate),
            signed_level_category=100 + candidate,
        )
        for candidate in range(2) for replica in range(8))


def _select_root_and_outcomes(index: int) \
        -> tuple[ValueInferenceRootV2, tuple[ContinuationOutcomeV2, ...]]:
    deal = _hex(f"select:{index}:deal")
    slot, state = _hex(f"select:{index}:slot"), _hex(f"select:{index}:state")
    successors = tuple(_hex(f"select:{index}:successor:{candidate}")
                       for candidate in range(2))
    candidate_set = hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state,
        "successor_sha256s": list(successors),
    })).hexdigest()
    tensors = (_tensor(0), _tensor(1))
    root = ValueInferenceRootV2(
        deal_sha256=deal, slot_sha256=slot, state_sha256=state,
        candidate_set_sha256=candidate_set, split="select", source="natural",
        role="attacker", phase="early", position="lead", trump_rank="2",
        trump_mode="S", select_subfold="epoch-select", points_bucket="0-39",
        successor_sha256s=successors,
        tensor_sha256s=tuple(_hex(f"select:{index}:tensor:{candidate}")
                             for candidate in range(2)),
        tensors=collate_world_afterstate_tensors(tensors),
    )
    outcomes = tuple(
        ContinuationOutcomeV2(
            deal_sha256=deal, slot_sha256=slot, state_sha256=state,
            candidate_set_sha256=candidate_set, source="natural", split="select",
            role="attacker", phase="early", position="lead", trump_rank="2",
            trump_mode="S", points_bucket="0-39", candidate_index=candidate,
            protected_incumbent=candidate == 0,
            successor_sha256=successors[candidate],
            continuation_sha256=_hex(f"select:{index}:crn:{replica}"),
            replica=replica, signed_level_category=100 + candidate,
        )
        for candidate in range(2) for replica in range(8))
    root.validate()
    for outcome in outcomes:
        outcome.validate()
    return root, outcomes


def test_reviewed_capacity_arms_bind_training_resources():
    receipt = SimpleNamespace(selected_arms=(
        _Arm("member-concurrency", 2),
        _Arm("inference-batch", 256),), torch_threads=1)
    assert inputs._capacity_resources(receipt) == (2, 1, 256, 256)


def test_inference_arm_does_not_change_reviewed_training_batch_cap():
    receipt = SimpleNamespace(selected_arms=(
        _Arm("member-concurrency", 2),
        _Arm("inference-batch", 64),), torch_threads=1)
    assert inputs._capacity_resources(receipt) == (2, 1, 256, 64)


@pytest.mark.parametrize("torch_threads", (2, 4))
def test_training_resource_adapter_refuses_cross_width_torch_threads(
        torch_threads):
    receipt = SimpleNamespace(selected_arms=(
        _Arm("member-concurrency", 2),
        _Arm("inference-batch", 256),), torch_threads=torch_threads)
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="resource arm"):
        inputs._capacity_resources(receipt)


def test_capacity_arm_drift_fails_closed():
    receipt = SimpleNamespace(selected_arms=(
        _Arm("member-concurrency", 2),
        _Arm("member-concurrency", 4),
        _Arm("inference-batch", 256),
    ), torch_threads=1)
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="missing or duplicated"):
        inputs._capacity_resources(receipt)


def test_training_resource_adapter_refuses_missing_torch_layout_field():
    receipt = SimpleNamespace(selected_arms=(
        _Arm("member-concurrency", 2),
        _Arm("inference-batch", 256),))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="resource arm"):
        inputs._capacity_resources(receipt)


def test_p0_diagnostic_sd_is_not_accepted_as_training_sigma(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = {"incumbent_relative_bessel_s_microlevels": 123}
    path = tmp_path / "p0.json"
    path.write_bytes(canonical_json_bytes(payload))
    path.chmod(0o444)
    monkeypatch.setattr(inputs, "validate_precision_label", lambda value: None)
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="sound sigma field"):
        inputs._p0_sigma(path)


def test_p0_caller_metric_cannot_supply_sigma(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = {"caller_sigma_pair_squared": 7.0}
    path = tmp_path / "p0.json"
    path.write_bytes(canonical_json_bytes(payload))
    path.chmod(0o444)
    monkeypatch.setattr(inputs, "validate_precision_label", lambda value: None)
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="sound sigma field"):
        inputs._p0_sigma(path)


def test_p0_exact_pair_target_population_variance_is_the_training_sigma(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = {
        "pair_target_population_variance": {
            "numerator": 25, "denominator": 4},
        "incumbent_relative_bessel_s_microlevels": 999_999,
    }
    path = tmp_path / "p0.json"
    raw = canonical_json_bytes(payload)
    path.write_bytes(raw)
    path.chmod(0o444)
    monkeypatch.setattr(inputs, "validate_precision_label", lambda value: None)
    sigma, digest = inputs._p0_sigma(path)
    assert sigma == 6.25
    assert digest == inputs._sha_bytes(raw)


def test_p0_sigma_fraction_must_be_reduced(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = {"pair_target_population_variance": {
        "numerator": 50, "denominator": 8}}
    path = tmp_path / "p0.json"
    path.write_bytes(canonical_json_bytes(payload))
    path.chmod(0o444)
    monkeypatch.setattr(inputs, "validate_precision_label", lambda value: None)
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="not reduced"):
        inputs._p0_sigma(path)


def test_p0_sigma_is_bound_to_this_supervisors_verified_shard(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / inputs.P0_REPORT_RELATIVE
    path.parent.mkdir(parents=True)
    raw = canonical_json_bytes({"pair_target_population_variance": {
        "numerator": 25, "denominator": 4}})
    path.write_bytes(raw)
    path.chmod(0o400)
    digest = hashlib.sha256(raw).hexdigest()
    freeze = SimpleNamespace(sha256=lambda: "f" * 64)
    supervisor = object.__new__(StageSupervisorV2)
    supervisor.root = tmp_path
    supervisor.freeze = freeze
    supervisor._state = StageStateV2(
        completed_stages=("population", "p0-labels-gates"),
        verified_shards=(("p0-labels-gates:receipt", digest),))
    monkeypatch.setattr(inputs, "validate_precision_label", lambda value: None)
    assert inputs._bound_p0_sigma(
        tmp_path, supervisor, freeze=freeze) == (6.25, digest)

    foreign = object.__new__(StageSupervisorV2)
    foreign.root = tmp_path
    foreign.freeze = freeze
    foreign._state = StageStateV2(
        completed_stages=("population", "p0-labels-gates"),
        verified_shards=(("p0-labels-gates:receipt", "0" * 64),))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="digest drift"):
        inputs._bound_p0_sigma(tmp_path, foreign, freeze=freeze)


def test_p0_sigma_refuses_duck_typed_or_foreign_supervisor(
        tmp_path: Path):
    freeze = SimpleNamespace(sha256=lambda: "f" * 64)
    duck = SimpleNamespace(root=tmp_path, freeze=freeze,
                           state=SimpleNamespace(completed_stages=(
                               "population", "p0-labels-gates"),
                               verified_shards=()))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="identity drift"):
        inputs._bound_p0_sigma(tmp_path, duck, freeze=freeze)

    foreign = object.__new__(StageSupervisorV2)
    foreign.root = tmp_path / "foreign"
    foreign.freeze = freeze
    foreign._state = StageStateV2()
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="identity drift"):
        inputs._bound_p0_sigma(tmp_path, foreign, freeze=freeze)


def test_d256_fit_uses_all_128_natural_and_32_mechanics_deals():
    slots = tuple(slot for slot in build_population_slot_ledger(TIER_SPECS[0])
                  if slot.split == "fit")
    population = tuple(_fit_material(slot) for slot in slots)
    natural = tuple(row for row in population if row.state.source == "natural")
    mechanics = tuple(row for row in population
                      if row.state.source == "mechanics")
    assert inputs._d256_fit_materials(population) == population

    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="population drift"):
        inputs._d256_fit_materials((*natural, *mechanics[:-1]))
    forged_state = dataclasses.replace(mechanics[-1].state, source="natural")
    forged = (*natural, *mechanics[:-1], SimpleNamespace(
        deal_sha256=mechanics[-1].deal_sha256, state=forged_state))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="metadata binding"):
        inputs._d256_fit_materials(forged)
    unpaired = list(population)
    unpaired[1] = SimpleNamespace(
        deal_sha256=unpaired[1].deal_sha256,
        state=dataclasses.replace(
            unpaired[1].state, slot_sha256=unpaired[2].state.slot_sha256))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="metadata binding|pair population drift"):
        inputs._d256_fit_materials(tuple(unpaired))

    natural_axis = next(row for row in population
                        if row.state.source == "natural")
    bad_axis = SimpleNamespace(
        deal_sha256=natural_axis.deal_sha256,
        state=dataclasses.replace(
            natural_axis.state,
            phase="middle" if natural_axis.state.phase != "middle" else "late"))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="metadata binding"):
        inputs._d256_fit_materials(tuple(
            bad_axis if row is natural_axis else row for row in population))

    mechanics_surface = next(row for row in population
                             if row.state.source == "mechanics")
    bad_surface = SimpleNamespace(
        deal_sha256=mechanics_surface.deal_sha256,
        state=dataclasses.replace(
            mechanics_surface.state, mechanics_surfaces=()))
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="metadata binding"):
        inputs._d256_fit_materials(tuple(
            bad_surface if row is mechanics_surface else row
            for row in population))


def test_real_training_input_builder_closes_full_d256_and_epoch_select_wiring(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Witness the production builder, not only its individual helpers."""
    fit_slots = tuple(
        slot for slot in build_population_slot_ledger(TIER_SPECS[0])
        if slot.split == "fit")
    fit = tuple(_fit_material(slot) for slot in fit_slots)

    epoch = []
    bundles = []
    roots_by_deal = {}
    for index in range(24):
        root, outcomes = _select_root_and_outcomes(index)
        material = SimpleNamespace(
            deal_sha256=root.deal_sha256,
            state=SimpleNamespace(
                source="natural", split="select",
                select_subfold="epoch-select"))
        epoch.append(material)
        roots_by_deal[root.deal_sha256] = root
        bundles.append(SimpleNamespace(
            deal_sha256=root.deal_sha256, candidates=outcomes,
            bundle_sha256=_hex(f"select:{index}:bundle")))
    precision = tuple(
        SimpleNamespace(
            deal_sha256=_hex(f"precision:{index}"),
            state=SimpleNamespace(
                source="natural", split="select",
                select_subfold="precision-select"))
        for index in range(24))
    select = (*epoch, *precision)
    bundles_by_deal = {
        row.deal_sha256: SimpleNamespace(
            deal_sha256=row.deal_sha256, candidates=(),
            bundle_sha256=_hex(f"{row.deal_sha256}:bundle"))
        for row in (*fit, *precision)}
    bundles_by_deal.update({row.deal_sha256: row for row in bundles})

    receipt = SimpleNamespace(selected_arms=(
        _Arm("member-concurrency", 2),
        _Arm("inference-batch", 256),), torch_threads=1)
    freeze = SimpleNamespace(
        evidence_root=tmp_path, population_tier="D256")
    supervisor = object()

    monkeypatch.setattr(inputs, "_freeze_sha", lambda _freeze: "f" * 64)
    monkeypatch.setattr(
        inputs, "_capacity", lambda _freeze, _root: (receipt, "c" * 64))
    monkeypatch.setattr(
        inputs, "_bound_p0_sigma",
        lambda _root, _supervisor, freeze: (6.25, "a" * 64))
    monkeypatch.setattr(
        inputs, "_population_namespace",
        lambda _freeze, _root, _repo: "n" * 64)

    def reopen_population(_root, **kwargs):
        if kwargs["expected_split"] == "fit":
            return fit
        assert kwargs["expected_split"] == "select"
        return select

    monkeypatch.setattr(inputs, "reopen_population_manifest", reopen_population)
    monkeypatch.setattr(
        inputs, "reopen_continuation_manifest",
        lambda _root, materials: tuple(
            bundles_by_deal[row.deal_sha256] for row in materials))
    monkeypatch.setattr(inputs, "build_training_examples_v2",
                        lambda material, _bundle: _fit_rows(material))
    monkeypatch.setattr(inputs, "build_inference_root_v2",
                        lambda material: roots_by_deal[material.deal_sha256])
    monkeypatch.setattr(inputs, "material_sha256",
                        lambda material: _hex(f"material:{material.deal_sha256}"))

    result = inputs.build_training_stage_inputs(
        freeze, supervisor=supervisor, evidence_root=tmp_path)

    result.validate()
    assert len(result.training_examples) == 160 * 2 * 8
    assert len(result.epoch_select_population.roots) == 24
    assert len(result.epoch_select_population.outcomes) == 24 * 2 * 8
    assert (result.member_workers, result.torch_threads,
            result.batch_example_cap, result.inference_batch_cap) == (2, 1, 256, 256)
    assert result.manifest()["training_root_count"] == 160
    assert result.manifest()["inference_batch_cap"] == 256
    with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                       match="inference batch source binding"):
        dataclasses.replace(result, inference_batch_cap=64).validate()
    for torch_threads in (2, 4):
        with pytest.raises(inputs.WorldAfterstateV2TrainingStageInputError,
                           match="resource configuration"):
            dataclasses.replace(result, torch_threads=torch_threads).validate()
