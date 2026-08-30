"""Focused integrity and resume tests for the progressive V2 DAG store."""

from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from shengji.rl.belief_artifacts import publish_exclusive_bytes
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_dag_artifacts import (
    AUTHORITY, NODE_NAMES, ArtifactRefV2, DagArtifactError, publish_node,
    publish_dag_node_from_refs, reopen_dag, reopen_node,
)
from shengji.rl import world_afterstate_v2_dag_artifacts as DAG
from shengji.rl.world_afterstate_v2_terminal_provenance import (
    AUTHORITY as RECONSTRUCTION_AUTHORITY,
    IndependentReconstructionReceiptV2,
    RECONSTRUCTION_SCHEMA,
)


FREEZE = "a" * 64
ADMISSION = "b" * 64


def _publish(root: Path, node: str, parent: object = ()):
    return publish_node(root, node, {f"{node}.bin": node.encode()},
                        freeze_sha256=FREEZE, admission_sha256=ADMISSION,
                        predecessors=parent)


def _prefix(root: Path, *, through: str = "precision-select-power") -> dict:
    values = {}
    for node in NODE_NAMES:
        if node == "terminal":
            break
        if node == "audit-attempt":
            break
        if node == "block-1-action-association-permutation":
            order = (
                "block-1-label-permutation",
                "block-1-complete-world-shuffle",
                "block-1-action-association-permutation",
            )
            for control in order:
                values[control] = _publish(root, control, [values["nested-curve"]])
            continue
        if node == "block-1-label-permutation" or node == "block-1-complete-world-shuffle":
            continue
        parent_names = {
            "population": (),
            "p0-labels-gates": ("population",),
            "optimizer-canary": ("p0-labels-gates",),
            "nested-curve": ("optimizer-canary",),
            "block-1-natural": ("nested-curve",),
            "block-2-natural": ("nested-curve",),
            "block-2-complete-world-shuffle": ("nested-curve",),
            "precision-select-power": (
                "block-1-natural", "block-1-action-association-permutation",
                "block-1-label-permutation", "block-1-complete-world-shuffle",
                "block-2-natural", "block-2-complete-world-shuffle",
            ),
        }[node]
        values[node] = _publish(root, node, [values[name] for name in parent_names])
        if node == through:
            break
    return values


def test_manifest_and_reference_are_canonical_and_all_false(tmp_path: Path):
    manifest = _publish(tmp_path, "population")
    assert manifest.authority == AUTHORITY
    assert manifest.manifest_sha256 == hashlib.sha256(
        canonical_json_bytes({key: value for key, value in manifest.to_dict().items()
                              if key != "manifest_sha256"})).hexdigest()
    assert reopen_node(tmp_path, "population", freeze_sha256=FREEZE,
                       admission_sha256=ADMISSION) == manifest


def test_parallel_block_one_controls_accept_any_order_but_exact_set(tmp_path: Path):
    values = _prefix(tmp_path)
    reopened = reopen_dag(tmp_path, freeze_sha256=FREEZE,
                          admission_sha256=ADMISSION)
    assert set(reopened) == set(values)
    assert set(reopened) >= {
        "block-1-action-association-permutation",
        "block-1-label-permutation", "block-1-complete-world-shuffle",
    }
    # A missing sibling prevents the exact precision join.
    (tmp_path / "nodes" / "block-1-label-permutation" / "manifest.json").unlink()
    with pytest.raises(DagArtifactError, match="dependency|regular|manifest"):
        reopen_node(tmp_path, "precision-select-power", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)


def test_all_six_cohorts_are_nested_siblings_and_precision_is_exact_join(tmp_path: Path):
    values = _prefix(tmp_path)
    cohort_names = {
        "block-1-natural", "block-1-action-association-permutation",
        "block-1-label-permutation", "block-1-complete-world-shuffle",
        "block-2-natural", "block-2-complete-world-shuffle",
    }
    for name in cohort_names:
        assert tuple(Path(ref.relative_path).parts[-2]
                     for ref in values[name].predecessors) == ("nested-curve",)
    assert {Path(ref.relative_path).parts[-2]
            for ref in values["precision-select-power"].predecessors} == cohort_names


def test_missing_dependency_and_duplicate_output_are_refused(tmp_path: Path):
    with pytest.raises(DagArtifactError, match="exact|dependency"):
        _publish(tmp_path, "p0-labels-gates", [])
    population = _publish(tmp_path, "population")
    with pytest.raises(DagArtifactError, match="duplicate"):
        publish_node(tmp_path, "p0-labels-gates",
                     [("x.bin", b"x"), ("x.bin", b"x")],
                     freeze_sha256=FREEZE, admission_sha256=ADMISSION,
                     predecessors=[population])


def test_tamper_hash_identity_symlink_and_hardlink_are_refused(tmp_path: Path):
    _publish(tmp_path, "population")
    output = tmp_path / "nodes" / "population" / "population.bin"
    os.chmod(output, 0o600)
    with pytest.raises(DagArtifactError, match="stable|regular"):
        reopen_node(tmp_path, "population", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)

    second = tmp_path / "second"
    second.mkdir()
    _publish(second, "population")
    output2 = second / "nodes" / "population" / "population.bin"
    hardlink = second / "nodes" / "population" / "hardlink.bin"
    os.link(output2, hardlink)
    with pytest.raises(DagArtifactError, match="population|stable"):
        reopen_node(second, "population", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)

    third = tmp_path / "third"
    third.mkdir()
    _publish(third, "population")
    output3 = third / "nodes" / "population" / "population.bin"
    output3.unlink()
    output3.symlink_to("../population.bin")
    with pytest.raises(DagArtifactError, match="regular|population"):
        reopen_node(third, "population", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)


def test_reference_path_traversal_and_wrong_output_hash_are_refused(tmp_path: Path):
    with pytest.raises(DagArtifactError, match="path"):
        ArtifactRefV2("../outside.bin", "schema", "a" * 64, 1)
    with pytest.raises(DagArtifactError, match="path"):
        publish_node(tmp_path, "population", {"../outside.bin": b"x"},
                     freeze_sha256=FREEZE, admission_sha256=ADMISSION)

    other = tmp_path / "other"
    other.mkdir()
    manifest = _publish(other, "population")
    path = other / "nodes" / "population" / "manifest.json"
    forged = manifest.to_dict()
    forged["outputs"][0]["sha256"] = "c" * 64
    body = {key: value for key, value in forged.items()
            if key != "manifest_sha256"}
    forged["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    os.chmod(path, 0o600)
    path.write_bytes(canonical_json_bytes(forged))
    os.chmod(path, 0o400)
    with pytest.raises(DagArtifactError, match="output bytes|self"):
        reopen_node(other, "population", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)


def test_wrong_hash_or_identity_and_immutable_replay_are_refused(tmp_path: Path):
    manifest = _publish(tmp_path, "population")
    assert publish_node(tmp_path, "population", {"population.bin": b"population"},
                       freeze_sha256=FREEZE, admission_sha256=ADMISSION) == manifest
    with pytest.raises(DagArtifactError, match="divergent|replay"):
        publish_node(tmp_path, "population", {"population.bin": b"different"},
                     freeze_sha256=FREEZE, admission_sha256=ADMISSION)
    manifest_path = tmp_path / "nodes" / "population" / "manifest.json"
    value = manifest.to_dict()
    value["freeze_sha256"] = "c" * 64
    os.chmod(manifest_path, 0o600)
    manifest_path.write_bytes(canonical_json_bytes(value))
    os.chmod(manifest_path, 0o400)
    with pytest.raises(DagArtifactError, match="identity|stable|self"):
        reopen_node(tmp_path, "population", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)


def test_concurrent_identical_node_publication_accepts_one_winner(tmp_path: Path):
    barrier = threading.Barrier(2)

    def publish():
        barrier.wait(timeout=2)
        return _publish(tmp_path, "population")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: publish(), range(2)))
    assert results[0] == results[1]
    assert not tuple(tmp_path.rglob("*.tmp"))
    assert reopen_node(tmp_path, "population", freeze_sha256=FREEZE,
                       admission_sha256=ADMISSION) == results[0]


def test_dependency_manifest_is_reread_at_recursive_boundary(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    population = _publish(tmp_path, "population")
    _publish(tmp_path, "p0-labels-gates", [population])
    population_path = tmp_path / "nodes" / "population" / "manifest.json"
    original_read = DAG._read
    count = 0

    def changed_between_reads(path: Path, label: str) -> bytes:
        nonlocal count
        raw = original_read(path, label)
        if path == population_path:
            count += 1
            if count == 2:
                return raw[:-2] + b"x\n"
        return raw

    monkeypatch.setattr(DAG, "_read", changed_between_reads)
    with pytest.raises(DagArtifactError, match="changed across dependency"):
        reopen_node(tmp_path, "p0-labels-gates", freeze_sha256=FREEZE,
                    admission_sha256=ADMISSION)


def test_present_corruption_raises_but_absent_future_is_omitted(tmp_path: Path):
    _publish(tmp_path, "population")
    aggregate = reopen_dag(tmp_path, freeze_sha256=FREEZE,
                           admission_sha256=ADMISSION)
    assert set(aggregate) == {"population"}
    manifest = tmp_path / "nodes" / "population" / "manifest.json"
    os.chmod(manifest, 0o600)
    manifest.write_bytes(b"corrupt\n")
    os.chmod(manifest, 0o400)
    with pytest.raises(DagArtifactError):
        reopen_dag(tmp_path, freeze_sha256=FREEZE, admission_sha256=ADMISSION)


def test_terminal_accepts_canonical_early_p0_and_audit_frontiers(tmp_path: Path):
    population = _publish(tmp_path, "population")
    p0 = _publish(tmp_path, "p0-labels-gates", [population])
    early = _publish(tmp_path, "terminal", [p0])
    aggregate = reopen_dag(tmp_path, freeze_sha256=FREEZE,
                           admission_sha256=ADMISSION)
    assert aggregate["terminal"] == early

    cohort_root = tmp_path / "cohorts"
    cohort_root.mkdir()
    values = _prefix(cohort_root)
    six = tuple(values[name] for name in (
        "block-1-natural", "block-1-action-association-permutation",
        "block-1-label-permutation", "block-1-complete-world-shuffle",
        "block-2-natural", "block-2-complete-world-shuffle"))
    six_terminal = _publish(cohort_root, "terminal", six)
    assert reopen_dag(cohort_root, freeze_sha256=FREEZE,
                      admission_sha256=ADMISSION)["terminal"] == six_terminal

    bad_root = tmp_path / "bad-frontier"
    bad_root.mkdir()
    population = _publish(bad_root, "population")
    p0 = _publish(bad_root, "p0-labels-gates", [population])
    with pytest.raises(DagArtifactError, match="canonical|exact"):
        _publish(bad_root, "terminal", [p0, population])

    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    values = _prefix(audit_root)
    audit = _publish(audit_root, "audit-attempt", [values["precision-select-power"]])
    terminal = _publish(audit_root, "terminal", [audit])
    aggregate = reopen_dag(audit_root, freeze_sha256=FREEZE,
                           admission_sha256=ADMISSION)
    assert aggregate["terminal"] == terminal


def test_external_output_refs_and_identical_resume_without_copy(tmp_path: Path):
    external = tmp_path / "sealed" / "population.bin"
    external.parent.mkdir()
    raw = b"already sealed output"
    digest = publish_exclusive_bytes(external, raw)
    ref = ArtifactRefV2("sealed/population.bin", "population-v2", digest, len(raw))
    first = publish_dag_node_from_refs(
        tmp_path, "population", output_refs=[ref], freeze_sha256=FREEZE,
        admission_sha256=ADMISSION)
    second = publish_dag_node_from_refs(
        tmp_path, "population", output_refs=[ref], freeze_sha256=FREEZE,
        admission_sha256=ADMISSION)
    assert second == first
    assert not (tmp_path / "nodes" / "population" / "population.bin").exists()

    alias_root = tmp_path / "alias"
    alias_root.mkdir()
    alias_file = alias_root / "sealed" / "population.bin"
    alias_file.parent.mkdir()
    alias_digest = publish_exclusive_bytes(alias_file, raw)
    alias_ref = ArtifactRefV2(
        "sealed/population.bin", "population-v2", alias_digest, len(raw))
    via_documented_argument = publish_dag_node_from_refs(
        alias_root, "population", outputs=[alias_ref], freeze_sha256=FREEZE,
        admission_sha256=ADMISSION)
    assert via_documented_argument.outputs == (alias_ref,)

    divergent = ArtifactRefV2("sealed/population.bin", "other-schema", digest, len(raw))
    with pytest.raises(DagArtifactError, match="replay|divergent"):
        publish_dag_node_from_refs(
            tmp_path, "population", output_refs=[divergent], freeze_sha256=FREEZE,
            admission_sha256=ADMISSION)


def test_reconstruction_is_only_the_terminal_bound_matched_receipt(tmp_path: Path):
    population = _publish(tmp_path, "population")
    p0 = _publish(tmp_path, "p0-labels-gates", [population])
    terminal_dir = tmp_path / "terminal"
    terminal_dir.mkdir()
    same = "c" * 64
    receipt = IndependentReconstructionReceiptV2(
        provenance_sha256="d" * 64,
        sealed_terminal_result_sha256=same,
        independently_derived_terminal_result_sha256=same,
        matched=True, verifier_sha256="e" * 64,
        source_sha256="f" * 64, runtime_sha256="1" * 64,
        authority=RECONSTRUCTION_AUTHORITY)
    receipt_path = terminal_dir / "independent-reconstruction.json"
    raw = receipt.canonical_bytes()
    digest = publish_exclusive_bytes(receipt_path, raw)
    receipt_ref = ArtifactRefV2(
        "terminal/independent-reconstruction.json", RECONSTRUCTION_SCHEMA,
        digest, len(raw))
    terminal = publish_dag_node_from_refs(
        tmp_path, "terminal", outputs=[receipt_ref], predecessors=[p0],
        freeze_sha256=FREEZE, admission_sha256=ADMISSION)
    reconstruction = publish_dag_node_from_refs(
        tmp_path, "reconstruction", outputs=[receipt_ref],
        predecessors=[terminal], freeze_sha256=FREEZE,
        admission_sha256=ADMISSION)
    assert reconstruction.outputs == (receipt_ref,)

    wrong_root = tmp_path / "wrong"
    wrong_root.mkdir()
    population = _publish(wrong_root, "population")
    p0 = _publish(wrong_root, "p0-labels-gates", [population])
    terminal = _publish(wrong_root, "terminal", [p0])
    with pytest.raises(DagArtifactError, match="receipt-only"):
        _publish(wrong_root, "reconstruction", [terminal])


def test_partial_resume_and_early_terminal_do_not_require_audit(tmp_path: Path):
    _prefix(tmp_path, through="p0-labels-gates")
    partial = reopen_dag(tmp_path, freeze_sha256=FREEZE,
                         admission_sha256=ADMISSION)
    assert set(partial) == {"population", "p0-labels-gates"}

    full = tmp_path / "full"
    full.mkdir()
    values = _prefix(full)
    terminal = _publish(full, "terminal", [values["precision-select-power"]])
    reopened = reopen_dag(full, freeze_sha256=FREEZE,
                          admission_sha256=ADMISSION)
    assert reopened["terminal"] == terminal
    assert "audit-attempt" not in reopened
    assert "reconstruction" not in reopened
