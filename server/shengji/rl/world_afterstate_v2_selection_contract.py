"""Typed, authority-free epoch-select receipt for Value V2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EPOCH_SELECTION_SCHEMA = "world-afterstate-v2-epoch-select-score-v1"
CONTROL_NAMES = (
    "natural", "action-association-permutation", "label-permutation",
    "complete-world-shuffle")


class WorldAfterstateV2SelectionContractError(ValueError):
    """An epoch-select receipt identity or boundary drifted."""


def _strict_int(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2SelectionContractError(f"{label} drift")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2SelectionContractError(f"{label} drift")
    return value


@dataclass(frozen=True)
class EpochSelectScoreV2:
    """One model score from the sealed epoch-select population only."""

    epoch: int
    seed_block: int
    member_index: int
    control_name: str
    model_state_sha256: str
    selection_population_sha256: str
    prediction_manifest_sha256: str
    loss_nano: int
    split: str = "select"
    select_subfold: str = "epoch-select"
    metric: str = "mean-root-total-loss-nano"
    audit_rows_opened: bool = False
    report_rows_opened: bool = False
    schema: str = EPOCH_SELECTION_SCHEMA

    def validate(self) -> None:
        if self.schema != EPOCH_SELECTION_SCHEMA \
                or self.split != "select" \
                or self.select_subfold != "epoch-select" \
                or self.metric != "mean-root-total-loss-nano" \
                or self.seed_block not in (1, 2) \
                or self.control_name not in CONTROL_NAMES \
                or self.audit_rows_opened is not False \
                or self.report_rows_opened is not False:
            raise WorldAfterstateV2SelectionContractError(
                "epoch-select score identity drift")
        _strict_int(self.epoch, "epoch-select epoch", 1)
        _strict_int(self.member_index, "epoch-select member")
        if self.member_index >= 4:
            raise WorldAfterstateV2SelectionContractError(
                "epoch-select member drift")
        _strict_int(self.loss_nano, "epoch-select loss")
        for label, value in (
                ("epoch-select model state", self.model_state_sha256),
                ("epoch-select population", self.selection_population_sha256),
                ("epoch-select prediction manifest",
                 self.prediction_manifest_sha256)):
            _digest(value, f"{label} SHA-256")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return dict(self.__dict__)


__all__ = [
    "CONTROL_NAMES", "EPOCH_SELECTION_SCHEMA", "EpochSelectScoreV2",
    "WorldAfterstateV2SelectionContractError",
]
