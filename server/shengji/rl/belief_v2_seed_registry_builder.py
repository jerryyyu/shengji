"""Source-pinned construction of the real BELIEF-V1 V2 seed registry.

The generic registry module deliberately knows nothing about project history.
This companion closes that operational gap: it names every finite deal/round
population still present in active source, represents large historical blocks
as compact inclusive ranges, binds the non-contiguous C4/preflight/V2 sets to
their exact derivation code, and classifies every scan candidate that requires
an explicit decision.

It reads no game data, generates no deal, writes no artifact, and grants no
capture, training, test, gameplay, strength, or deployment authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .belief_synthetic import _training_seeds as c4_training_seeds
from .belief_v2_preflight import preflight_coordinates
from .belief_v2_protocol import v2_round_coordinates
from .belief_v2_seed_registry import (
    BeliefV2SeedRegistryError,
    SeedClassificationV1,
    SeedPopulationV1,
    build_seed_registry,
    complete_seed_classifications,
    validate_seed_scan,
)


v2_population_id = "belief-v1-v2-production-rounds"

# S6's reviewed controller was intentionally removed after the lane closed, so
# its numeric population no longer appears in the active source tree.  Preserve
# the exact reviewed historical source identity here instead of silently
# treating file deletion as seed-namespace deletion.  The constants reproduce
# a93c2f58d2e152adfd854c4416e9a92c5a005e68:
# server/scripts/s6_throw_full_hand_preflight_controller.py, whose SHA-256 was
# 130b108b5fbe2de28c16ed1d812350abddb10199debe210142d6574e7ad9bf28.
S6_PREFLIGHT_SEED0 = 436_000_000_000
S6_PREFLIGHT_CLUSTERS = 4
S6_SCREEN_SEED0 = 437_000_000_000
S6_SCREEN_CLUSTERS = 7_168
S6_STREAM_STRIDE = 3_000_017


@dataclass(frozen=True)
class _PopulationSpec:
    population: SeedPopulationV1
    selectors: tuple[tuple[str, str], ...]


def _range(start: int, count: int) -> tuple[int, int]:
    if type(start) is not int or type(count) is not int or count <= 0:
        raise BeliefV2SeedRegistryError(
            "reviewed seed range input drift")
    return start, start + count - 1


def _spec(
        population_id: str, source_paths: tuple[str, ...], *,
        ranges: tuple[tuple[int, int], ...] = (),
        seeds: tuple[int, ...] = (),
        selectors: tuple[tuple[str, str], ...]) -> _PopulationSpec:
    return _PopulationSpec(
        population=SeedPopulationV1(
            population_id=population_id,
            source_paths=tuple(sorted(source_paths)),
            ranges=tuple(sorted(ranges)), seeds=tuple(sorted(seeds))),
        selectors=selectors)


def reviewed_population_specs() -> tuple[_PopulationSpec, ...]:
    """Return the exact active-source population table.

    Ranges are conservative reserved deal domains when a historical selector
    used a rejection/split walk.  A conservative superset can only refuse an
    otherwise-free V2 namespace; it cannot hide a real collision.
    """
    v2_seeds = tuple(sorted(
        coordinate.round_seed for coordinate in v2_round_coordinates()))
    preflight_seeds = tuple(sorted(
        coordinate.round_seed for coordinate in preflight_coordinates()))
    c4_seeds = tuple(sorted(c4_training_seeds()))
    return (
        _spec(
            "teacher-stage-c-state-scan",
            ("HANDOFF_REVIEW.md",),
            ranges=(_range(188_000_000, 16_384),),
            selectors=((
                "HANDOFF_REVIEW.md",
                "TEACHER_STAGE_C_MIDLATE_STATE_SCREEN_CONTROLLER_V1_REVIEW"),)),
        _spec(
            "t4-midlate-composition-screen",
            ("HANDOFF_REVIEW.md",),
            ranges=(
                _range(192_000_000, 4),
                _range(193_000_000, 2_048)),
            selectors=((
                "HANDOFF_REVIEW.md",
                "TEACHER_STAGE_C_MIDLATE_COMPOSITION_SCREEN_CONTROLLER_V1_REVIEW"),)),
        _spec(
            "s6-full-hand-preflight-and-screen",
            ("server/shengji/rl/belief_v2_seed_registry_builder.py",),
            # The actual deal population is strided.  Reserving the enclosing
            # intervals is deliberately conservative and compact: it may
            # refuse a future namespace unnecessarily, but cannot hide a
            # collision with an S6 deal.
            ranges=(
                (S6_PREFLIGHT_SEED0,
                 S6_PREFLIGHT_SEED0
                 + S6_STREAM_STRIDE * (S6_PREFLIGHT_CLUSTERS - 1)),
                (S6_SCREEN_SEED0,
                 S6_SCREEN_SEED0
                 + S6_STREAM_STRIDE * (S6_SCREEN_CLUSTERS - 1))),
            selectors=(
                ("server/shengji/rl/belief_v2_seed_registry_builder.py",
                 "S6_PREFLIGHT_SEED0 = 436_000_000_000"),
                ("server/shengji/rl/belief_v2_seed_registry_builder.py",
                 "S6_SCREEN_SEED0 = 437_000_000_000"))),
        _spec(
            "s4-future-c2-retired-and-reseeded",
            ("HANDOFF_REVIEW.md",),
            # The retired interval is literal canonical-ledger evidence.  The
            # reseeded interval applies the same reviewed cluster count,
            # stride, and maximum role offset at the new 360b seed0.
            ranges=(
                (300_000_000_000, 349_150_778_511),
                (360_000_000_000, 409_150_778_511)),
            selectors=((
                "HANDOFF_REVIEW.md",
                "S4_POINT_BANKING_FUTURE_C2_RESEED_CONTROLLER_V1_REVIEW"),)),
        _spec(
            "pair-retention-census-10m",
            ("server/scripts/pair_ballot_retention_census_review.py",),
            ranges=(_range(10_000_000, 1_000_000),),
            selectors=((
                "server/scripts/pair_ballot_retention_census_review.py",
                "EXPECTED_SEED0 = 10_000_000"),)),
        _spec(
            "deep-lead-capture-92m",
            ("server/scripts/capture_deep_leads.py",),
            ranges=(_range(92_000_000, 60_000),),
            selectors=(
                ("server/scripts/capture_deep_leads.py",
                 "SEED0 = 92_000_000"),
                ("server/scripts/capture_deep_leads.py",
                 "MAX_SEEDS = 60_000"))),
        _spec(
            "teacher-capture-blocks",
            ("server/shengji/teacher_v1.py",),
            ranges=(
                _range(120_000_000, 1_024),
                _range(143_000_000, 1_024),
                _range(149_000_000, 1_024)),
            selectors=(
                ("server/shengji/teacher_v1.py", "SEED_START = 149_000_000"),
                ("server/shengji/teacher_v1.py", "CAPTURE_SEED_END ="),
                ("server/shengji/teacher_v1.py", '"seed0": 120_000_000'),
                ("server/shengji/teacher_v1.py", '"seed0": 143_000_000'))),
        _spec(
            "v11-direct-revalidation-121m",
            ("server/scripts/v11_revalidate.py",),
            ranges=(_range(121_000_000, 2_048),),
            selectors=(
                ("server/scripts/v11_revalidate.py", "SEED0 = 121_000_000"),
                ("server/scripts/v11_revalidate.py", "SEED_HI ="))),
        _spec(
            "s0-original-screen-confirm-blocks",
            ("server/scripts/s0_run.py",),
            ranges=(
                _range(132_000_000, 2_048),
                _range(133_000_000, 2_048),
                _range(134_000_000, 2_048),
                _range(135_000_000, 8_192)),
            selectors=tuple(("server/scripts/s0_run.py", needle) for needle in (
                '"seed0": 132_000_000', '"seed0": 133_000_000',
                '"seed0": 134_000_000', '"seed0": 135_000_000'))),
        _spec(
            "s0-dependency-audit-135m",
            ("server/scripts/s0_dependency_audit.py",),
            ranges=(_range(135_000_000, 8_192),),
            selectors=(
                ("server/scripts/s0_dependency_audit.py",
                 "SEED0 = 135_000_000"),
                ("server/scripts/s0_dependency_audit.py", "SEED_HI ="))),
        _spec(
            "s3a-bury-pilot-136m",
            ("server/scripts/s3a_bury_pilot.py",),
            ranges=(_range(136_000_000, 512),),
            selectors=(
                ("server/scripts/s3a_bury_pilot.py", "SEED0 = 136_000_000"),
                ("server/scripts/s3a_bury_pilot.py", "SEED_HI ="))),
        _spec(
            "v11-anchor-screen-confirm",
            ("server/scripts/v11_anchor_composition.py",
             "server/scripts/v11_anchor_composition_v2.py"),
            ranges=(
                _range(137_000_000, 2_048),
                _range(138_000_000, 8_192)),
            selectors=tuple(
                (path, needle)
                for path in (
                    "server/scripts/v11_anchor_composition.py",
                    "server/scripts/v11_anchor_composition_v2.py")
                for needle in (
                    '"seed0": 137_000_000',
                    '"seed0": 138_000_000'))),
        _spec(
            "s3b-endgame-screen-confirm-preflight",
            ("server/scripts/s3b_endgame_strength.py",),
            ranges=(
                _range(139_000_000, 2_048),
                _range(140_000_000, 8_192),
                _range(141_000_000, 2)),
            selectors=(
                ("server/scripts/s3b_endgame_strength.py",
                 '"seed0": 139_000_000'),
                ("server/scripts/s3b_endgame_strength.py",
                 '"seed0": 140_000_000'),
                ("server/scripts/s3b_endgame_strength.py",
                 "PREFLIGHT_SEED0 = 141_000_000"))),
        _spec(
            "v11-direct-revalidation-v2-142m",
            ("server/scripts/v11_revalidate_v2.py",),
            ranges=(_range(142_000_000, 2_048),),
            selectors=(
                ("server/scripts/v11_revalidate_v2.py",
                 "SEED0 = 142_000_000"),
                ("server/scripts/v11_revalidate_v2.py", "SEED_HI ="))),
        _spec(
            "douzero-probe-report",
            ("server/shengji/rl/douzero_learning_screen.py",),
            ranges=(
                _range(145_100_000, 128),
                _range(146_000_000, 256)),
            selectors=(
                ("server/shengji/rl/douzero_learning_screen.py",
                 "PROBE_SEED0 = 145_100_000"),
                ("server/shengji/rl/douzero_learning_screen.py",
                 "REPORT_SEED0 = 146_000_000"))),
        _spec(
            "s0-deployment-choice-147m",
            ("server/scripts/s0_deployment_choice.py",),
            ranges=(_range(147_000_000, 16_384),),
            selectors=(
                ("server/scripts/s0_deployment_choice.py",
                 "SEED0 = 147_000_000"),
                ("server/scripts/s0_deployment_choice.py", "SEED_HI ="))),
        _spec(
            "s0-deployment-parent-148m",
            ("server/scripts/s0_deployment_choice_v2_parent.py",),
            ranges=(_range(148_000_000, 16_384),),
            selectors=(
                ("server/scripts/s0_deployment_choice_v2_parent.py",
                 "SEED0 = 148_000_000"),
                ("server/scripts/s0_deployment_choice_v2_parent.py",
                 "SEED_HI ="))),
        _spec(
            "rlcb-confirmation-150m",
            ("server/scripts/rlcb_c1.py",),
            ranges=(_range(150_000_000, 2_048),),
            selectors=(
                ("server/scripts/rlcb_c1.py", "SEED0 = 150_000_000"),
                ("server/scripts/rlcb_c1.py", "SEED_HI ="),
                ("server/scripts/rlcb_c1.py", '"seed0": 150_000_000'))),
        _spec(
            "s3a-sizing-throughput",
            ("server/scripts/s3a_bury_duel.py",
             "server/scripts/s3a_bury_throughput.py"),
            ranges=(_range(151_000_000, 4),),
            selectors=(
                ("server/scripts/s3a_bury_duel.py",
                 "CONSUMED_SIZING_DEAL_SEEDS ="),
                ("server/scripts/s3a_bury_throughput.py",
                 "SEED0 = 151_000_002"),
                ("server/scripts/s3a_bury_throughput.py", "SEED_HI ="))),
        _spec(
            "s3a-screen-confirm-preflight",
            ("server/scripts/s3a_bury_duel.py",),
            ranges=(
                _range(153_000_003, 2_048),
                _range(20_000_000_000, 8_192),
                _range(18_000_000_000, 4)),
            selectors=(
                ("server/scripts/s3a_bury_duel.py",
                 '"seed0": 153_000_003'),
                ("server/scripts/s3a_bury_duel.py",
                 '"seed0": 20_000_000_000'),
                ("server/scripts/s3a_bury_duel.py",
                 "PREFLIGHT_SEED0 = 18_000_000_000"))),
        _spec(
            "suphx-o0-dev-160m",
            ("server/shengji/rl/suphx_o0_screen.py",),
            ranges=(_range(160_100_000, 128),),
            selectors=(
                ("server/shengji/rl/suphx_o0_screen.py",
                 "DEV_SEED0 = 160_100_000"),
                ("server/shengji/rl/suphx_o0_screen.py",
                 "CURRENT_RESERVED_DEAL_SEED_CEILING ="))),
        _spec(
            "s4-state-census-161m",
            ("server/scripts/s4_point_banking_screen.py",),
            ranges=(_range(161_000_000, 200_000),),
            selectors=((
                "server/scripts/s4_point_banking_screen.py",
                "SEED0 = 161_000_000"),)),
        _spec(
            "s3c-natural-prefix-bands",
            ("server/scripts/s3c_exact_root_design.py",),
            ranges=tuple(_range(start, 4_096) for start in (
                173_000_000, 174_000_000, 175_000_000)),
            selectors=((
                "server/scripts/s3c_exact_root_design.py",
                "BAND_SEED_STARTS ="),)),
        _spec(
            "s4-screen-confirm-preflight",
            ("server/scripts/s4_point_banking_duel.py",),
            ranges=(
                _range(96_000_000_000, 4),
                _range(100_000_000_000, 2_048),
                _range(120_000_000_000, 8_192)),
            selectors=(
                ("server/scripts/s4_point_banking_duel.py",
                 "PREFLIGHT_SEED0 = 96_000_000_000"),
                ("server/scripts/s4_point_banking_duel.py",
                 '"seed0": 100_000_000_000'),
                ("server/scripts/s4_point_banking_duel.py",
                 '"seed0": 120_000_000_000'))),
        _spec(
            "pair-affected-state-capture",
            ("server/scripts/pair_ballot_affected_states.py",),
            ranges=(_range(310_000_000, 12_000_000),),
            selectors=((
                "server/scripts/pair_ballot_affected_states.py",
                "SEED0 = 310_000_000"),)),
        _spec(
            "pair-reserved-domains",
            ("server/scripts/pair_ballot_champion_natural_dose_design.py",),
            ranges=(
                (310_000_000, 321_999_999),
                (445_300_000_000, 466_802_621_839),
                (499_000_000_000, 499_382_502_159),
                (500_000_000_000, 521_502_621_839),
                (620_000_000_000, 620_022_500_119),
                (621_000_000_000, 634_824_078_319)),
            selectors=((
                "server/scripts/pair_ballot_champion_natural_dose_design.py",
                "KNOWN_PAIR_SEED_DOMAINS ="),)),
        _spec(
            "pair-champion-dose-reserved-domain",
            ("server/scripts/pair_ballot_champion_natural_dose_design.py",),
            ranges=((600_000_000_000, 600_000_008_341),),
            selectors=(
                ("server/scripts/pair_ballot_champion_natural_dose_design.py",
                 "CANDIDATE_SEED0 ="),
                ("server/scripts/pair_ballot_champion_natural_dose_design.py",
                 "POPULATION_SEED_HI ="))),
        _spec(
            "belief-v1-b2-production-rounds",
            ("server/shengji/rl/belief_b2_protocol.py",
             "server/shengji/rl/belief_v2_protocol.py"),
            ranges=((
                6_104_125_432_620_400_640,
                6_104_125_432_620_404_735),),
            selectors=(
                ("server/shengji/rl/belief_b2_protocol.py",
                 "B2_SEED_START ="),
                ("server/shengji/rl/belief_v2_protocol.py",
                 "V1_B2_SEED_START ="),
                ("server/shengji/rl/belief_v2_protocol.py",
                 "V1_B2_SEED_END ="))),
        _spec(
            "belief-v1-c4-synthetic-training",
            ("server/shengji/rl/belief_synthetic.py",),
            seeds=c4_seeds,
            selectors=((
                "server/shengji/rl/belief_synthetic.py",
                "C4_SEED_START ="),)),
        _spec(
            "belief-v1-v2-capacity-preflight",
            ("server/shengji/rl/belief_v2_preflight.py",),
            seeds=preflight_seeds,
            selectors=((
                "server/shengji/rl/belief_v2_preflight.py",
                "PREFLIGHT_SEED_NAMESPACE ="),)),
        _spec(
            v2_population_id,
            ("server/shengji/rl/belief_v2_protocol.py",),
            seeds=v2_seeds,
            selectors=((
                "server/shengji/rl/belief_v2_protocol.py",
                "V2_SEED_NAMESPACE ="),)),
    )


def _matching_candidates(
        scan: dict[str, Any], *, path: str, needle: str) \
        -> tuple[dict[str, Any], ...]:
    rows = tuple(row for row in scan["candidates"]
                 if row["path"] == path and needle in row["line"])
    if not rows:
        raise BeliefV2SeedRegistryError(
            f"reviewed seed selector is absent: {path}:{needle}")
    return rows


def reviewed_seed_classifications(
        scan: dict[str, Any],
        specs: tuple[_PopulationSpec, ...]) \
        -> tuple[SeedClassificationV1, ...]:
    """Bind finite selectors and explicitly adjudicate every required row."""
    validate_seed_scan(scan)
    by_id: dict[str, SeedClassificationV1] = {}
    for spec in specs:
        for path, needle in spec.selectors:
            for candidate in _matching_candidates(
                    scan, path=path, needle=needle):
                candidate_id = candidate["candidate_id"]
                existing = by_id.get(candidate_id)
                if existing is not None \
                        and existing.population_id \
                        != spec.population.population_id:
                    raise BeliefV2SeedRegistryError(
                        "reviewed seed selector population overlap")
                by_id[candidate_id] = SeedClassificationV1(
                    candidate_id=candidate_id,
                    classification="finite-population",
                    population_id=spec.population.population_id,
                    note=f"reviewed:{spec.population.population_id}")
    for candidate in scan["candidates"]:
        if not candidate["explicit_classification_required"] \
                or candidate["candidate_id"] in by_id:
            continue
        line = candidate["line"]
        non_population = re.search(
            r"(?:MAX_|MIN_|OFFSET|DOMAIN|MATERIAL|IDENTIT|COUNT|CEILING)",
            line) is not None
        by_id[candidate["candidate_id"]] = SeedClassificationV1(
            candidate_id=candidate["candidate_id"],
            classification=("non-population-context" if non_population
                            else "derived-rng-stream"),
            note=("reviewed:bound-or-context" if non_population
                  else "reviewed:derived-model-policy-test-or-output-seed"))
    return complete_seed_classifications(scan, explicit=tuple(by_id.values()))


def build_reviewed_seed_registry(scan: dict[str, Any]) -> dict[str, Any]:
    """Build and independently close the one real V2 registry artifact."""
    specs = reviewed_population_specs()
    populations = tuple(spec.population for spec in specs)
    if len({row.population_id for row in populations}) != len(populations):
        raise BeliefV2SeedRegistryError(
            "reviewed seed population identifier drift")
    classifications = reviewed_seed_classifications(scan, specs)
    return build_seed_registry(
        scan, classifications=classifications, populations=populations,
        v2_population_id=v2_population_id)
