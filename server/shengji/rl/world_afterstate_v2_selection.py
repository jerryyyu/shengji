"""Sealed epoch-select scoring for Value-Afterstate V2.

This module can read only complete ``select`` roots and their already-opened
continuation rows.  It returns one typed score bound to the exact model state,
root population, and prediction bytes.  It cannot train, choose an audit
route, or consume audit/report rows.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import category_signed_level
from .world_afterstate_v2_continuation import ContinuationOutcomeV2
from .world_afterstate_v2_inference import ValueInferenceRootV2
from .world_afterstate_v2_model import (
    WorldAfterstateValueV2, expected_signed_utility)
from .world_afterstate_v2_training import LOSS_SCALE, model_state_sha256
from .world_afterstate_v2_selection_contract import EpochSelectScoreV2


REPLICATES = tuple(range(8))


class WorldAfterstateV2SelectionError(ValueError):
    """An epoch-select model, root, or outcome population drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _root_population_sha(roots: Sequence[ValueInferenceRootV2]) -> str:
    return _sha([root.target_free_body()
                 for root in sorted(roots, key=lambda item: item.root_sha256)])


def _validate_population(
        roots: Sequence[ValueInferenceRootV2],
        outcomes: Sequence[ContinuationOutcomeV2]) \
        -> tuple[tuple[ValueInferenceRootV2, ...],
                 dict[str, dict[int, tuple[ContinuationOutcomeV2, ...]]]]:
    if type(roots) not in (tuple, list) or not roots \
            or type(outcomes) not in (tuple, list) or not outcomes:
        raise WorldAfterstateV2SelectionError(
            "epoch-select population drift")
    root_map: dict[str, ValueInferenceRootV2] = {}
    deal_ids: set[str] = set()
    for root in roots:
        if type(root) is not ValueInferenceRootV2:
            raise WorldAfterstateV2SelectionError(
                "epoch-select root type drift")
        try:
            root.validate()
        except Exception as exc:
            raise WorldAfterstateV2SelectionError(
                "epoch-select root refused") from exc
        if root.split != "select" \
                or root.select_subfold != "epoch-select" \
                or root.root_sha256 in root_map \
                or root.deal_sha256 in deal_ids:
            raise WorldAfterstateV2SelectionError(
                "epoch-select root population drift")
        root_map[root.root_sha256] = root
        deal_ids.add(root.deal_sha256)
    grouped: dict[str, dict[int, list[ContinuationOutcomeV2]]] = {
        root_sha: {} for root_sha in root_map}
    seen: set[tuple[str, int, int]] = set()
    by_state = {root.state_sha256: root_sha
                for root_sha, root in root_map.items()}
    if len(by_state) != len(root_map):
        raise WorldAfterstateV2SelectionError(
            "epoch-select state population drift")
    for row in outcomes:
        if type(row) is not ContinuationOutcomeV2:
            raise WorldAfterstateV2SelectionError(
                "epoch-select outcome type drift")
        try:
            row.validate()
        except Exception as exc:
            raise WorldAfterstateV2SelectionError(
                "epoch-select outcome refused") from exc
        root_sha = by_state.get(row.state_sha256)
        if root_sha is None:
            raise WorldAfterstateV2SelectionError(
                "epoch-select foreign outcome")
        root = root_map[root_sha]
        key = (root_sha, row.candidate_index, row.replica)
        if key in seen or row.split != "select" \
                or row.candidate_index >= root.candidate_count \
                or row.protected_incumbent != (row.candidate_index == 0) \
                or (row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256, row.successor_sha256) != (
                        root.deal_sha256, root.slot_sha256,
                        root.state_sha256, root.candidate_set_sha256,
                        root.successor_sha256s[row.candidate_index]):
            raise WorldAfterstateV2SelectionError(
                "epoch-select outcome binding drift")
        seen.add(key)
        grouped[root_sha].setdefault(row.candidate_index, []).append(row)
    expected = {
        (root_sha, candidate, replica)
        for root_sha, root in root_map.items()
        for candidate in range(root.candidate_count)
        for replica in REPLICATES}
    if seen != expected:
        raise WorldAfterstateV2SelectionError(
            "epoch-select outcome drop")
    frozen = {}
    for root_sha, candidates in grouped.items():
        frozen[root_sha] = {}
        for candidate, rows in candidates.items():
            ordered = tuple(sorted(rows, key=lambda item: item.replica))
            continuation = {row.replica: row.continuation_sha256
                            for row in grouped[root_sha][0]}
            if tuple(row.replica for row in ordered) != REPLICATES \
                    or any(row.continuation_sha256 != continuation[row.replica]
                           for row in ordered):
                raise WorldAfterstateV2SelectionError(
                    "epoch-select CRN binding drift")
            frozen[root_sha][candidate] = ordered
    return tuple(sorted(root_map.values(), key=lambda item: item.root_sha256)), frozen


@dataclass(frozen=True)
class EpochSelectPopulationV2:
    """The only selection-label object accepted by the cohort controller."""

    roots: tuple[ValueInferenceRootV2, ...]
    outcomes: tuple[ContinuationOutcomeV2, ...]

    def _validated_plan(self):
        if type(self.roots) is not tuple or type(self.outcomes) is not tuple:
            raise WorldAfterstateV2SelectionError(
                "epoch-select sealed population type drift")
        ordered_roots, grouped = _validate_population(
            self.roots, self.outcomes)
        return ordered_roots, grouped, _root_population_sha(ordered_roots)

    def validate(self) -> None:
        self._validated_plan()

    @property
    def population_sha256(self) -> str:
        return self._validated_plan()[2]

    def _score_validated(self, model: WorldAfterstateValueV2, *, epoch: int,
                         seed_block: int, member_index: int,
                         control_name: str, sigma_pair_squared: float,
                         plan) -> EpochSelectScoreV2:
        _validate_score_request(
            model, epoch=epoch, sigma_pair_squared=sigma_pair_squared)
        ordered_roots, grouped, population_sha256 = plan
        return _score_epoch_select_validated(
            model, ordered_roots=ordered_roots, grouped=grouped,
            population_sha256=population_sha256, epoch=epoch,
            seed_block=seed_block, member_index=member_index,
            control_name=control_name,
            sigma_pair_squared=sigma_pair_squared)

    def score(self, model: WorldAfterstateValueV2, *, epoch: int,
              seed_block: int, member_index: int, control_name: str,
              sigma_pair_squared: float) -> EpochSelectScoreV2:
        plan = self._validated_plan()
        return self._score_validated(
            model, epoch=epoch, seed_block=seed_block,
            member_index=member_index, control_name=control_name,
            sigma_pair_squared=sigma_pair_squared, plan=plan)


def _validate_score_request(
        model: object, *, epoch: object,
        sigma_pair_squared: object) -> None:
    if type(model) is not WorldAfterstateValueV2 \
            or isinstance(epoch, bool) or not isinstance(epoch, int) \
            or epoch < 1 \
            or isinstance(sigma_pair_squared, bool) \
            or not isinstance(sigma_pair_squared, (int, float)) \
            or not math.isfinite(sigma_pair_squared) \
            or sigma_pair_squared < 0:
        raise WorldAfterstateV2SelectionError(
            "epoch-select score request drift")


def _score_epoch_select_validated(
        model: WorldAfterstateValueV2, *,
        ordered_roots: tuple[ValueInferenceRootV2, ...],
        grouped: dict[str, dict[int, tuple[ContinuationOutcomeV2, ...]]],
        population_sha256: str, epoch: int, seed_block: int,
        member_index: int, control_name: str,
        sigma_pair_squared: float) -> EpochSelectScoreV2:
    """Score one model after the immutable selection population was checked."""
    before = model_state_sha256(model)
    root_losses = []
    prediction_rows = []
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            for root in ordered_roots:
                candidate_count = len(root.successor_sha256s)
                logits = model._forward_validated(root.tensors)
                if logits.shape[0] != candidate_count \
                        or not bool(torch.all(torch.isfinite(logits))):
                    raise WorldAfterstateV2SelectionError(
                        "epoch-select model output drift")
                log_probability = torch.log_softmax(logits, dim=1)
                absolute_rows = []
                for candidate in range(candidate_count):
                    categories = tuple(
                        row.signed_level_category
                        for row in grouped[root.root_sha256][candidate])
                    absolute_rows.extend(
                        -log_probability[candidate, category]
                        for category in categories)
                    prediction_rows.append({
                        "root_sha256": root.root_sha256,
                        "candidate_index": candidate,
                        "probability_sha256": _sha([
                            float(value) for value in torch.softmax(
                                logits[candidate], dim=0).tolist()]),
                    })
                absolute = torch.stack(absolute_rows).mean()
                pair_rows = []
                for candidate in range(1, candidate_count):
                    prediction = expected_signed_utility(
                        logits[candidate:candidate + 1]).mean() \
                        - expected_signed_utility(logits[0:1]).mean()
                    target = sum(
                        category_signed_level(candidate_row.signed_level_category)
                        - category_signed_level(incumbent_row.signed_level_category)
                        for candidate_row, incumbent_row in zip(
                            grouped[root.root_sha256][candidate],
                            grouped[root.root_sha256][0], strict=True)
                    ) / len(REPLICATES)
                    pair_rows.append(
                        (prediction - target).square()
                        / max(1.0, float(sigma_pair_squared)))
                root_losses.append(
                    absolute + torch.stack(pair_rows).mean())
    finally:
        model.train(was_training)
    if model_state_sha256(model) != before or not root_losses:
        raise WorldAfterstateV2SelectionError(
            "epoch-select model mutation/empty drift")
    loss = float(torch.stack(root_losses).mean())
    if not math.isfinite(loss) or loss < 0:
        raise WorldAfterstateV2SelectionError(
            "epoch-select loss drift")
    result = EpochSelectScoreV2(
        epoch=epoch, seed_block=seed_block, member_index=member_index,
        control_name=control_name, model_state_sha256=before,
        selection_population_sha256=population_sha256,
        prediction_manifest_sha256=_sha(prediction_rows),
        loss_nano=round(loss * LOSS_SCALE))
    result.validate()
    return result


def score_epoch_select_v2(
        model: WorldAfterstateValueV2, *,
        roots: Sequence[ValueInferenceRootV2],
        outcomes: Sequence[ContinuationOutcomeV2], epoch: int,
        seed_block: int, member_index: int, control_name: str,
        sigma_pair_squared: float) -> EpochSelectScoreV2:
    """Score one immutable model on the complete epoch-select population."""
    _validate_score_request(
        model, epoch=epoch, sigma_pair_squared=sigma_pair_squared)
    ordered_roots, grouped = _validate_population(roots, outcomes)
    return _score_epoch_select_validated(
        model, ordered_roots=ordered_roots, grouped=grouped,
        population_sha256=_root_population_sha(ordered_roots), epoch=epoch,
        seed_block=seed_block, member_index=member_index,
        control_name=control_name,
        sigma_pair_squared=sigma_pair_squared)


__all__ = [
    "EpochSelectPopulationV2", "WorldAfterstateV2SelectionError",
    "score_epoch_select_v2",
]
