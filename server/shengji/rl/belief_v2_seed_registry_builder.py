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

# Keep reviewed source-line identities stable while replacing the old heuristic.
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
    reviewed_nonpopulation = dict(_REVIEWED_NONPOPULATION_CLASSIFICATIONS)
    if len(reviewed_nonpopulation) \
            != len(_REVIEWED_NONPOPULATION_CLASSIFICATIONS) \
            or any(classification not in {
                "non-population-context", "derived-rng-stream"}
                for classification in reviewed_nonpopulation.values()):
        raise BeliefV2SeedRegistryError(
            "reviewed nonpopulation classification table drift")
    for candidate in scan["candidates"]:
        candidate_id = candidate["candidate_id"]
        classification = reviewed_nonpopulation.get(candidate_id)
        if classification is None:
            continue
        if not candidate["explicit_classification_required"] \
                or candidate_id in by_id:
            raise BeliefV2SeedRegistryError(
                "reviewed nonpopulation classification binding drift")
        by_id[candidate_id] = SeedClassificationV1(
            candidate_id=candidate_id,
            classification=classification,
            note=f"reviewed:explicit:{classification}")
    required = {
        candidate["candidate_id"] for candidate in scan["candidates"]
        if candidate["explicit_classification_required"]}
    if not required.issubset(by_id):
        raise BeliefV2SeedRegistryError(
            "unclassified explicit seed candidate")
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


# Exact candidate identities reviewed as non-population constants or derived
# RNG/model/test streams at source head 0949404.  A changed or newly introduced
# explicit-required candidate receives a new identity and refuses above instead
# of being inferred from its spelling.
_REVIEWED_NONPOPULATION_CLASSIFICATIONS = (
    ("0fe8997e2f4e1828334eaae6a5cf65d12a738e2594746d3e05af29795afa73a7", "non-population-context"),
    ("974f4a252423738d3ae0a5e49973e3ff30c1c9a34718558a0b4584c1508b3b81", "non-population-context"),
    ("e1fb5dc2913689d01b2c51b8f8b6ca02e4a81b5452ba152c06e280b977b7bb16", "non-population-context"),
    ("89bb9b967e07bf0e4fa8ed8fc93caab710b811aea477c1428fd97bc7ac517586", "derived-rng-stream"),
    ("3cdf27a07ec9c536b55d3f019612383b4030a6eab567dfd9051431e674406981", "non-population-context"),
    ("30babb8263f2d317b2c3e8b4ae270e7c69489d764365bcaef487aa44081800d2", "derived-rng-stream"),
    ("1cf24c6f568f22457f4e0c31aabd2155f183fbb9d5e5f213206aaaf6f1297e22", "derived-rng-stream"),
    ("567fc32495dbdddcd3e62fe7b6b1f1f2e8621d055ffa4d3b44c4fcfff706b3dc", "derived-rng-stream"),
    ("862bed85346793ac2c60c314ad8c9e175895064ab428e9ae9988d3bd621ce421", "derived-rng-stream"),
    ("3edcf99c17683587894123c1b685e1c3b56a4b7924b2d772c748dbfc2fff56d2", "non-population-context"),
    ("92aa97d6629ad52b20c724d9e7db57145f42a796d0a263cd70e7b79a1e69891b", "non-population-context"),
    ("c183669b03e0cd391b758a9b36d97e486cf41c60f29d67d2964a6f3e67ba9ecb", "non-population-context"),
    ("d69108221044dc755f041f35e7e5f33c720975f535ad4969ae1f486e7da9fc15", "non-population-context"),
    ("319e4aa51a00a1347310d09dcf8625dc36ccf0d3cc44168f954392ea6a03e105", "non-population-context"),
    ("8acdb4170862e2ff8c536ff6e7ca4757ca96941e5976ae186fce0b9850e208a4", "derived-rng-stream"),
    ("6b1e3dbaaf5d1d0e61c23cf705072dc7bc403666fcdee2a421eb00aba6e97a5d", "non-population-context"),
    ("2c7e170e6a0dd472bf3dfd346f660a5469cfadc8ec243bd1499beca16a41f23c", "non-population-context"),
    ("a77353882f3807ed364209d28746e368d424e268475d9240cb25cf4ebbc751ef", "derived-rng-stream"),
    ("123c8415652bec7652c0d59ce584404ec21386ce861588645e6b6c34ec7ee421", "non-population-context"),
    ("339cb623bb184f0f2e665e7ae461067dc8dd6db6e4fb8f7b82ea019f5f03aa04", "non-population-context"),
    ("5010284aa90ff2fe406de885399f2922a866217b417ebde70448a7f7a1043841", "derived-rng-stream"),
    ("736ebbb9cdb57d0ac0f586eb006c139c0bbbaae203f4441d8b997c18c5edf28e", "derived-rng-stream"),
    ("10a67d2bc918e1afb1a6d8b7345f8b68faa937e7bfcaee649e0767d848c30b28", "derived-rng-stream"),
    ("732e44a805b2ccc63d524ac29f050c55f228101e6bbd13b5097ae267c3e6f628", "derived-rng-stream"),
    ("9613caf08e9ab7a6d85d7ad61e4b6f2bc5bacabfbd22639d3ce62ae536fdc8bb", "derived-rng-stream"),
    ("db59c26dea4d74a90d3c2101bca79b72a599f9116fccdd56eff99fac3ab62a12", "derived-rng-stream"),
    ("b392b666861e98c0ad572ddd6dda11afa3a16080a22bbd59d5eda2f5825bf3b4", "derived-rng-stream"),
    ("ce21bf469e64e3827b8f810a2aae7c59aeaa623970a76603ff8a0683946b29b6", "derived-rng-stream"),
    ("b2723dd5d01943f6c58213e725d96651f325523bdb76342951ccab7c83c55ff4", "derived-rng-stream"),
    ("59d148d2f8c120e0a877cbb670fb6028f5859afbfb6435d9b66cce15a61df866", "derived-rng-stream"),
    ("fbcfd29db995d7cd8c61ade0b5074687646c6153c0cc8d9ac40cb68f8bfad634", "derived-rng-stream"),
    ("dcef7a9341436b5d4d9ac2dbd843389e7ec3aac0d1321c83b60c0d588174c34f", "derived-rng-stream"),
    ("7169faa65f4144d092eadc8d7f7687a2c5acc8415aa0554171f8fc25371c7e4e", "derived-rng-stream"),
    ("dd5c266f87c499569589d1013f29b8905c866cb2e86fc8a92b7d6956baa663d5", "non-population-context"),
    ("a1e5ce4c3f786b60d1e6e3141405f558b2b737a3d08e10d3895f52110905b8ef", "derived-rng-stream"),
    ("d123627913a035840003fcfcb4c2084e424f07f11c02e20f4fd6094dea5bba13", "derived-rng-stream"),
    ("7e4a0c24466fbd6bbdca15090680f87732c5065bc735ffdabee5e25f1b07c537", "derived-rng-stream"),
    ("f5dc5cc7b96667f37e836738baf2c0c105f55ecdc4346e14f731f15e84aba61b", "derived-rng-stream"),
    ("d97afaf9454e914d14b5cd853d3bb79af04a4a39f45258310dc7b6f392ea69a5", "non-population-context"),
    ("f20147dda53d9f351fe31ec4e923105c577a5ab181f2dbaf97b2430d9f62199a", "non-population-context"),
    ("c795fdfedd4763aba7964e8a21597966611c3da0fe0e5d98e4fb42451a737879", "derived-rng-stream"),
    ("8ee579b490d2bba99ad32a9f92cc0d7fd4795bc37ce76184028777b184c4d975", "derived-rng-stream"),
    ("a2ec540e9f3d24d63e1b7ce7ed64405e411ef4574a8e9068c4057501d2dcef37", "derived-rng-stream"),
    ("42267880ae577772e7ee63643a21a8200564464d82f990a6c5a1a73f9a6346c8", "derived-rng-stream"),
    ("43c27463163659550f57090486397510742f273bb4df1cfa0cd218c5c4b501a8", "derived-rng-stream"),
    ("49afbe10228ecdf8c747c3da1fbb9fb1ebe67b1d90932f03cebb160061b4a709", "derived-rng-stream"),
    ("e613f55b5ff32c46f5530c35e74c5d49286ca8f02076f2050e705ae9abd1ebaf", "derived-rng-stream"),
    ("1c635c70847581fa7ee912e9ef6c125fe8017ca0bf7b01cb876f4c74ea7856b8", "derived-rng-stream"),
    ("2cfd2a62631a8c68f70efb0080e88cac3319adc6481dbafc4d48395f85e56065", "derived-rng-stream"),
    ("2ac008ae8ad58092aa1544247744ee177c59606b94731e3e5dc080d6571f0f00", "derived-rng-stream"),
    ("0f0508005a228bf0fcc2979b4e642239e425d2fd599d28a4de12a9de39b0cf4e", "derived-rng-stream"),
    ("3528096e433372addbd53e9110d87c7b86834d1b2cc95d518b0bd90495158ea1", "derived-rng-stream"),
    ("9a80b20098af7efacad1193f0ae86f0207571b329e534c05c933191c2ed8688b", "derived-rng-stream"),
    ("8c36375728eced2d41bf6bd7dcb480bd8b52547c7d476167c96032ea4f13f8bb", "derived-rng-stream"),
    ("dfa8efd43c9acdaa51ebc9d2346bbb7d6ff22f85aa94a2f8fed14483da440c96", "derived-rng-stream"),
    ("8769e2f14ec077f03cbe5a6dba27967b019f881634f1109a99701a97a396425c", "derived-rng-stream"),
    ("c3e8464a0d02ed495232bc995083e01e115843da0b692cf1d92eb2b26b556dcb", "derived-rng-stream"),
    ("835043e440f2f2e0e261913655f2d784baef832427edd02b7aa500a7efb17239", "derived-rng-stream"),
    ("ba9bd4da3c1539ce60f4a1477bd90f030a9bb4ecf01e5438b0c317102d6dfb64", "derived-rng-stream"),
    ("68d34afeb44a125088575255fc524457cfb292939d3e3ebfa2ee76d65674a3c1", "derived-rng-stream"),
    ("c9dfad7772f885b53087ec523493428492f73b8c046603805b1b2b628a215e19", "derived-rng-stream"),
    ("ed096e9fecfeb3086927052ec86f45c55e4bc4117530b47db5e993b43a1ad95e", "derived-rng-stream"),
    ("930926076c8017abbb70a7abd681ad8d0ea1a40d1210db7ae020861e4b88d17b", "derived-rng-stream"),
    ("3441ec7eb9f2d1890056c544ae994cc6eccad9ac6a059ce73988c9fa9f4e83bb", "derived-rng-stream"),
    ("9158389fbcee5e3a65c46cc1b87c1fc2b33d5e9d03ed886bfc95e4dc5dc4db2a", "derived-rng-stream"),
    ("6ce0d090746e869a380f1c4ca73db83b7aac5c506696a4198febca7f49bac3c5", "derived-rng-stream"),
)
