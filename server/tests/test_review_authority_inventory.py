"""Keep source-required review authority through ledger compaction."""
from pathlib import Path


REQUIRED_MARKERS = (
    "H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V2_REVIEW",
    "H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V3_REVIEW",
    "H0_HUMAN_COUNTERFACTUAL_DESIGN_V3_REVIEW",
    "S3A_DUEL_SCREEN_PACKET_V1_REVIEW",
    "S3C_EXACT_ROOT_CURRICULUM_V1_REVIEW",
    "S3C_ONE_CARD_CAPACITY_CONTROLLER_V2_REVIEW",
    "S4_POINT_BANKING_DUEL_PACKET_V2_REVIEW",
    "TEACHER_STAGE_C_CONTROLLER_REBIND_V1_REVIEW",
    "TEACHER_STAGE_C_V3_REVIEW",
)


def test_source_required_review_markers_survive_ledger_rotation() -> None:
    repo = Path(__file__).parents[2]
    lines = (repo / "HANDOFF_REVIEW.md").read_text().splitlines()
    for marker in REQUIRED_MARKERS:
        matches = [line for line in lines if line.startswith(marker + " ")]
        assert len(matches) == 1, (marker, len(matches))
