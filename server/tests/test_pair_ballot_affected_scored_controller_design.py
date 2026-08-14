from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_scored_controller_design as DESIGN  # noqa: E402


EXPECTED_LANES = (
    (51, 149_940, "e6757756498b8ade7e35d66c55a7974a4ce83073f75e3cb1246fdb39cc0547a8"),
    (59, 173_460, "a191b5e861d6a6a492a15c51878cffa46121bc9d24a268f2cc4ecafdc3148cc9"),
    (60, 176_400, "9c8c8944f112fbe723ff4d92227f8527a419094a61103215a8ad575a0893cb0e"),
    (84, 246_960, "9aa037a427f56e1de8305be92a6d4ef74d567d476d77a0e81b9c04c13164d025"),
    (58, 170_520, "9cbdff9be1368ba92c94b77418808539ef0a6dadfd6072e6a5f68f9d35ac0d05"),
    (74, 217_560, "88437b2f8b972a9f83c6abdf7890aed9547219e1e335a844e7fefb2d7a344873"),
    (61, 179_340, "622e7365db88665eee36707866d8c4c60efa8eb915ae8eb857d4c0e4293bf57b"),
    (47, 138_180, "c256606d12d047c07dffd8dd2170649477eda60b99d27997970b4f5b2112290d"),
    (56, 164_640, "761fd15afe9b37198eabd7c0252e5749f4d8350b93e618bae4841b67b6bdaf97"),
    (50, 147_000, "510f74ca90c1b630b5e98f4ef13c08fad5f0f80bb7dde01a4c6d9549d7cd3a2b"),
    (71, 208_740, "ebfccf9fa0d84a75090474e9e25793343c5d62064fb52638bd7d9f3a7ad6494f"),
    (80, 235_200, "32dec86631f71d60fa08549a3b9bade2a5ce8ddced55859057371ccf42e34558"),
    (77, 226_380, "d9cbfbf46604faed5cbcf8e84b60e61fae392721350c00f4dde2664fa39d08d6"),
    (60, 176_400, "41d2ea14918e3c6072ea012bf45bab7b6b5994cb0a3b210ca59f7a47188695b8"),
    (68, 199_920, "2fa70c0b8a068b05b804eaa93e7c6e08fe2d9b2b291b0e1ab981c55f968de570"),
    (68, 199_920, "e4c6f6eb8f8ee1d21f967eaa8143b2a3734f88b17e2f8de88b32016866c722fa"),
)


@pytest.fixture(scope="module")
def design() -> dict:
    return DESIGN.build_design()


def _rehash(payload: dict) -> None:
    body = dict(payload)
    body.pop("design_sha256", None)
    payload["design_sha256"] = DESIGN._digest(DESIGN._canonical(body))


def test_exact_reviewed_source_is_reconstructed(design):
    assert design["source_packet_design"] == {
        "schema": DESIGN.SOURCE_DESIGN_SCHEMA,
        "git": DESIGN.SOURCE_DESIGN_GIT,
        "source_sha256": DESIGN.SOURCE_DESIGN_SOURCE_SHA256,
        "file_sha256": DESIGN.SOURCE_DESIGN_FILE_SHA256,
        "internal_sha256": DESIGN.SOURCE_DESIGN_INTERNAL_SHA256,
        "run_id": DESIGN.RUN_ID,
        "packet_schema": DESIGN.PACKET_SCHEMA,
        "selection_sha256":
            "3c9993bc8432d2fc419cfb75c2f766119de3aa4eacdf87dc3c238e1a484b29ab",
        "lane_manifest_sha256":
            "75e1ca0fd756083179b3e1943b528063ce53a2ddaab8a44568b498ccf48a6b37",
    }
    assert design["provenance"]["source_design_review_git"] \
        == DESIGN.SOURCE_DESIGN_REVIEW_GIT
    assert design["provenance"]["review_is_design_only"] is True
    assert design["provenance"]["execution_authority_from_review"] is False


def test_lane_population_and_work_are_independently_pinned(design):
    lanes = design["execution_topology"]["lane_manifest"]
    observed = tuple(
        (lane["state_count"], lane["max_candidate_world_rollouts"],
         lane["selection_sha256"])
        for lane in lanes
    )
    assert observed == EXPECTED_LANES
    population = design["population_and_work"]
    assert population["states_by_split"] == {"calib": 512, "dev": 512}
    assert population["states_by_band"] == {
        "early": 896, "mid": 96, "late": 32,
    }
    assert population["states_by_role"] == {
        "attacker": 1, "defender": 1_023,
    }
    assert population["unique_deal_clusters"] == 991
    assert sum(population["lane_work"]) == 3_010_560
    assert all(
        work == lane["state_count"] * 2_940
        for lane, work in zip(lanes, population["lane_work"], strict=True)
    )


def test_request_and_attestation_namespaces_are_all_distinct(design):
    review = design["admission_and_review"]
    prefixes = {
        design["packet_freeze_contract"]["packet_request_prefix"],
        design["packet_freeze_contract"][
            "packet_reviewer_attestation_prefix"],
        review["final_request_prefix"],
        review["final_reviewer_attestation_prefix"],
        review["aggregate_reviewer_attestation_prefix"],
    }
    assert len(prefixes) == 5
    assert all(value.endswith(" ") for value in prefixes)
    assert design["packet_freeze_contract"][
        "request_text_is_never_parsed_as_authority"] is True


def test_all_post_design_authority_is_closed(design):
    assert design["authority"] == {
        "controller_design_review_only": True,
        "controller_implementation_authorized": False,
        "packet_implementation_authorized": False,
        "packet_freeze_authorized": False,
        "packet_run_authorized": False,
        "population_open_authorized": False,
        "capacity_result_open_authorized": False,
        "scored_output_access_authorized": False,
        "aggregation_authorized": False,
        "report_access_authorized": False,
        "champion_dose_census_authorized": False,
        "whole_game_execution_authorized": False,
        "retry_authorized": False,
        "extension_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


@pytest.mark.parametrize(
    "path,value",
    (
        (("authority", "packet_run_authorized"), True),
        (("authority", "report_access_authorized"), True),
        (("execution_topology", "resume_supported"), True),
        (("population_and_work", "max_work_total"), 3_010_559),
        (("capacity_boundary", "average_lane_projection_permitted"), True),
    ),
)
def test_coordinated_self_rehash_mutations_refuse(
        monkeypatch, design, path, value):
    changed = copy.deepcopy(design)
    changed[path[0]][path[1]] = value
    _rehash(changed)
    monkeypatch.setattr(DESIGN, "build_design", lambda: copy.deepcopy(design))
    with pytest.raises(DESIGN.ControllerDesignRefused,
                       match="differs from reconstruction"):
        DESIGN.validate_design(changed)


def test_review_ledger_rewrite_refuses(monkeypatch):
    original = DESIGN._git_bytes

    def rewritten(ref, path):
        value = original(ref, path)
        if ref == DESIGN.SOURCE_DESIGN_REVIEW_GIT and path == DESIGN.REVIEW_LEDGER:
            replacement = b"X" if value[100:101] != b"X" else b"Y"
            return value[:100] + replacement + value[101:]
        return value

    monkeypatch.setattr(DESIGN, "_git_bytes", rewritten)
    with pytest.raises(DESIGN.ControllerDesignRefused,
                       match="ledger statement drift"):
        DESIGN._require_provenance()


def test_reviewer_actor_drift_refuses(monkeypatch):
    original = DESIGN._git

    def wrong_actor(*args, **kwargs):
        if args[:3] == ("show", "-s", "--format=%an <%ae>%n%cn <%ce>"):
            return "Codex <noreply@openai.com>\nCodex <noreply@openai.com>\n"
        return original(*args, **kwargs)

    monkeypatch.setattr(DESIGN, "_git", wrong_actor)
    with pytest.raises(DESIGN.ControllerDesignRefused,
                       match="reviewer identity drift"):
        DESIGN._require_provenance()


def test_source_byte_drift_refuses_before_execution(monkeypatch):
    original = DESIGN._stable_bytes

    def drift(path, *, label, frozen=False):
        value = original(path, label=label, frozen=frozen)
        if label == "source packet design":
            return value + b"\n"
        return value

    monkeypatch.setattr(DESIGN, "_stable_bytes", drift)
    with pytest.raises(DESIGN.ControllerDesignRefused,
                       match="source packet-design bytes drift"):
        DESIGN._require_provenance()


def test_preloaded_source_module_cannot_substitute_authenticated_bytes(
        monkeypatch):
    monkeypatch.setitem(
        sys.modules, "pair_ballot_affected_scored_packet_design", object())
    assert DESIGN._source_design()["design_sha256"] \
        == DESIGN.SOURCE_DESIGN_INTERNAL_SHA256


def test_verify_accepts_only_frozen_canonical_file(tmp_path, design):
    path = tmp_path / "design.json"
    path.write_bytes(DESIGN._canonical(design))
    path.chmod(0o444)
    assert DESIGN.verify_design_file(path) == design

    path.chmod(0o644)
    with pytest.raises(DESIGN.ControllerDesignRefused,
                       match="non-writable"):
        DESIGN.verify_design_file(path)


@pytest.mark.parametrize(
    "raw,match",
    (
        (b'{"schema":"a","schema":"b"}\n', "duplicate key"),
        (b'{"elapsed":NaN}\n', "non-finite"),
        (b'{"schema":"x"} trailing\n', "strict JSON"),
    ),
)
def test_verify_rejects_noncanonical_json(tmp_path, raw, match):
    path = tmp_path / "design.json"
    path.write_bytes(raw)
    path.chmod(0o444)
    with pytest.raises(DESIGN.ControllerDesignRefused, match=match):
        DESIGN.verify_design_file(path)


@pytest.mark.parametrize("kind", ("symlink", "hardlink"))
def test_verify_rejects_linked_inputs(tmp_path, design, kind):
    source = tmp_path / "source.json"
    source.write_bytes(DESIGN._canonical(design))
    source.chmod(0o444)
    target = tmp_path / "target.json"
    if kind == "symlink":
        target.symlink_to(source)
    else:
        os.link(source, target)
    with pytest.raises(DESIGN.ControllerDesignRefused,
                       match="regular, unlinked"):
        DESIGN.verify_design_file(target)


def test_cli_build_and_verify_are_stdout_only(tmp_path, design):
    script = Path(DESIGN.__file__)
    built = subprocess.run(
        [sys.executable, str(script), "build"], cwd=DESIGN.REPO,
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert json.loads(built.stdout) == design
    path = tmp_path / "design.json"
    path.write_text(built.stdout)
    path.chmod(0o444)
    verified = subprocess.run(
        [sys.executable, str(script), "verify", "--design", str(path)],
        cwd=DESIGN.REPO, check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert json.loads(verified.stdout) == {
        "schema": DESIGN.SCHEMA,
        "design_sha256": design["design_sha256"],
        "logical_lanes": 16,
        "sealed_shard_outputs": 32,
        "controller_implementation_authorized": False,
        "packet_run_authorized": False,
    }


def test_module_has_no_execution_or_artifact_writer_surface():
    source = Path(DESIGN.__file__).read_text()
    assert "import shengji" not in source
    assert "multiprocessing" not in source
    assert "systemd-run" not in source
    assert "Popen" not in source
    assert "write_bytes(" not in source
    assert "write_text(" not in source
    assert "open(\"w" not in source
    assert set(DESIGN.main.__code__.co_names).isdisjoint({
        "fork", "execv", "spawn", "system", "Popen",
    })
