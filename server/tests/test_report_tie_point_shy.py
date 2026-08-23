"""ARM 0 witnesses (STRENGTH_STACK_PROPOSAL.md): report-stage point-shy
tie-break.

Each test fails against the pre-ARM-0 restore path (verified by removing the
hook and re-running). The exemplar numbers are the production TZGK round 6
seat 2 decision record, quoted from logs, not invented.
"""
from shengji.ai.registry import REGISTRY, make_bot
from shengji.ai.mcbot import MCBot

# The production record this whole lane traces to: report fold measured a
# statistical tie (gap 0.25, se 1.379, critical 1.70) between the incumbent
# H10 (10 points at risk) and the challenger S3 (0 points at risk); the
# champion restored H10.
TZGK_GAP = 0.25
TZGK_SE = 1.379
TZGK_CRITICAL = 1.70


def _bot(name):
    return make_bot(name, seed=7)


def test_champion_flag_is_off_and_variant_on():
    """Adoption discipline: the champion is untouched; the arm is a variant."""
    champion = _bot("mc-s0-report-lcb")
    assert champion.REPORT_TIE_POINT_SHY is False
    arm = _bot("mc-s0-report-lcb-pointshy")
    assert arm.REPORT_TIE_POINT_SHY is True
    # Work-matched null exists for the duel.
    assert "mc-s0-report-lcb-pointshy-null" in REGISTRY


def test_champion_never_fires_the_tie_break():
    """Byte-identity half 1: with the flag off the helper returns None even
    on a perfect tie, so the champion's restore path is unreachable-changed."""
    champion = _bot("mc-s0-report-lcb")
    assert champion._report_tie_point_shy_pick(
        0.0, 1.0, TZGK_CRITICAL, ["H10"], ["S3"]) is None


def test_exemplar_tie_flips_to_the_safer_card():
    """The TZGK r6 s2 exemplar: tie + challenger risks fewer points ->
    challenger. This is the entire verified 26-case harm class in one row."""
    arm = _bot("mc-s0-report-lcb-pointshy")
    shy = arm._report_tie_point_shy_pick(
        TZGK_GAP, TZGK_SE, TZGK_CRITICAL, ["H10"], ["S3"])
    assert shy is not None
    assert shy["incumbent_points_at_risk"] == 10
    assert shy["challenger_points_at_risk"] == 0
    assert shy["pick"] == "challenger"


def test_off_class_decisions_are_untouched():
    """Byte-identity half 2: outside the tie window (|gap| > critical*se)
    the helper declines, so every non-tie restore is exactly the champion's.
    k = 1.70 exactly: the class is defined by gap < 1.70*se, so any smaller
    window would exclude class members (review correction #4)."""
    arm = _bot("mc-s0-report-lcb-pointshy")
    # Incumbent convincingly better: gap far negative.
    assert arm._report_tie_point_shy_pick(
        -5.0, 1.0, TZGK_CRITICAL, ["H10"], ["S3"]) is None
    # Just outside the window on the positive side.
    assert arm._report_tie_point_shy_pick(
        1.71, 1.0, TZGK_CRITICAL, ["H10"], ["S3"]) is None
    # Exactly on the boundary is INSIDE the class (gap < 1.70*se defines the
    # restores; |gap| <= critical*se must cover it).
    assert arm._report_tie_point_shy_pick(
        1.70, 1.0, TZGK_CRITICAL, ["H10"], ["S3"]) is not None


def test_risk_tie_keeps_the_incumbent():
    """Equal points at risk -> incumbent, so the arm changes nothing it has
    no opinion about (the 79-equal stratum of the corpus flip table)."""
    arm = _bot("mc-s0-report-lcb-pointshy")
    shy = arm._report_tie_point_shy_pick(
        0.1, 1.0, TZGK_CRITICAL, ["S3"], ["D4"])
    assert shy is not None and shy["pick"] == "incumbent"
    # And a *pair* of point cards outweighs a single: 20 > 10 flips.
    shy = arm._report_tie_point_shy_pick(
        0.1, 1.0, TZGK_CRITICAL, ["S10", "S10"], ["HK"])
    assert shy is not None and shy["pick"] == "challenger"


def test_incomplete_fold_declines():
    """No critical/se (incomplete report fold) -> never fires; the
    report_underfilled path stays exactly the champion's."""
    arm = _bot("mc-s0-report-lcb-pointshy")
    assert arm._report_tie_point_shy_pick(
        0.0, None, None, ["H10"], ["S3"]) is None


def test_evaluation_margin_fields_present():
    """Stage 1 harness fields: measurement-only margin/bracket recording.
    Brackets must match MCBot's LEVEL_OBJECTIVE convention exactly."""
    import io
    import json
    from shengji.evaluation import run_arm

    fh = io.StringIO()
    recs = run_arm("witness", "smart", "smart", 1, 424242, fh, "t",
                   progress=False)
    assert len(recs) == 2
    for rec in recs:
        for key in ("attacker_points", "arm_attacking", "attacker_bracket",
                    "arm_point_margin", "level_change"):
            assert key in rec, key
        pts = rec["attacker_points"]
        expected = (min(3, (pts - 80) // 40) if pts >= 80
                    else -3 if pts == 0 else -(1 + (79 - pts) // 40))
        assert rec["attacker_bracket"] == expected
        sign = 1 if rec["arm_attacking"] else -1
        assert rec["arm_point_margin"] == (pts - 80) * sign
        # Binary gate field unchanged and still present.
        assert rec["won"] in (0, 1)
    # Round-trips through the JSONL the harness writes.
    for line in fh.getvalue().splitlines():
        json.loads(line)
