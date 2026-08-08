"""Falsification tests for outcome-blind Stage-B gate readiness."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "scripts" / \
        "teacher_stage_b_readiness.py"
    spec = importlib.util.spec_from_file_location("teacher_readiness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R = _module()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path):
    source = (("scripts/teacher_v1_label.py", b"label\n"),
              ("scripts/teacher_v1_gate.py", b"gate\n"))
    parents = (("runs/frozen/states.json", b"states\n"),
               ("runs/frozen/receipt.json", b"receipt\n"))
    contract = R.ReadinessContract(
        producer_git="a" * 40,
        namespace="runs/frozen",
        shard_count=2,
        records_per_shard=16,
        original_pids=(10, 11),
        source_sha256s=tuple((name, _sha(raw)) for name, raw in source),
        parent_sha256s=tuple((name, _sha(raw)) for name, raw in parents),
    )
    for name, raw in (*source, *parents):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for shard in range(contract.shard_count):
        final_name = R._expected_final(contract, shard)
        final = tmp_path / final_name
        # Deliberately not JSON: readiness must not parse/open outcome fields.
        final.write_bytes(b"opaque gold outcome bytes\n")
        log = tmp_path / R._expected_log(contract, shard)
        log.write_text(
            f"{{\"event\":\"progress\"}}\n"
            f"wrote {final_name}: 16 records, digest {'b' * 64}, 12.3s\n"
        )
    return contract


def _problems(tmp_path: Path, contract, *, processes=(), status=""):
    return R.readiness_problems(
        tmp_path,
        contract=contract,
        git_head=contract.producer_git,
        tree_status=status,
        processes=processes,
    )


def test_ready_fixture_is_outcome_blind_and_accepts_exact_success_boundary(
        tmp_path):
    contract = _fixture(tmp_path)
    assert _problems(tmp_path, contract) == []


def test_process_parser_counts_python_but_not_caffeinate_wrapper():
    command = (
        ".venv/bin/python scripts/teacher_v1_label.py gold "
        "--out runs/frozen/stage_b_gold_v2_shard00.json"
    )
    rows = [f"10 {command}", f"11 caffeinate -dimsu {command}"]
    assert R.gold_python_workers(rows) == {
        10: "runs/frozen/stage_b_gold_v2_shard00.json"}


@pytest.mark.parametrize(
    "mutation,needle",
    [
        ("dirty", "tree is dirty"),
        ("source", "SHA drift"),
        ("parent_partial", "partial exists"),
        ("missing_final", "missing/nonregular gold final"),
        ("final_symlink", "missing/nonregular gold final"),
        ("final_partial", "gold partial remains"),
        ("refusal", "log contains refusal"),
        ("sentinel", "lacks terminal success"),
        ("gate", "gate or partial already exists"),
        ("extra", "unexpected gold finals"),
        ("worker", "workers remain live"),
    ],
)
def test_every_readiness_boundary_fails_closed(
        tmp_path, mutation, needle):
    contract = _fixture(tmp_path)
    status = ""
    processes = []
    namespace = tmp_path / contract.namespace
    if mutation == "dirty":
        status = " M scripts/teacher_v1_label.py"
    elif mutation == "source":
        (tmp_path / contract.source_sha256s[0][0]).write_bytes(b"drift\n")
    elif mutation == "parent_partial":
        Path(str(tmp_path / contract.parent_sha256s[0][0])
             + ".partial").write_bytes(b"partial")
    elif mutation == "missing_final":
        (tmp_path / R._expected_final(contract, 0)).unlink()
    elif mutation == "final_symlink":
        final = tmp_path / R._expected_final(contract, 0)
        target = tmp_path / "target"
        final.rename(target)
        final.symlink_to(target)
    elif mutation == "final_partial":
        Path(str(tmp_path / R._expected_final(contract, 0))
             + ".partial").write_bytes(b"partial")
    elif mutation == "refusal":
        log = tmp_path / R._expected_log(contract, 0)
        log.write_text(log.read_text() + "REFUSING: late drift\n")
    elif mutation == "sentinel":
        (tmp_path / R._expected_log(contract, 0)).write_text("progress\n")
    elif mutation == "gate":
        (namespace / "stage_b_gate_v2.json").write_bytes(b"existing")
    elif mutation == "extra":
        (namespace / "stage_b_gold_v2_shard99.json").write_bytes(b"extra")
    elif mutation == "worker":
        processes = [
            "10 .venv/bin/python scripts/teacher_v1_label.py gold "
            "--out runs/frozen/stage_b_gold_v2_shard00.json"]
    problems = _problems(
        tmp_path, contract, processes=processes, status=status)
    assert any(needle in problem for problem in problems), problems


def test_wrong_git_and_malformed_process_rows_fail_safely(tmp_path):
    contract = _fixture(tmp_path)
    problems = R.readiness_problems(
        tmp_path,
        contract=contract,
        git_head="c" * 40,
        tree_status="",
        processes=["bad", "12 'unterminated"],
    )
    assert any("producer git" in problem for problem in problems)
    assert not any("workers remain live" in problem for problem in problems)


def test_creator_pid_population_is_exact(tmp_path):
    contract = _fixture(tmp_path)
    bad = R.ReadinessContract(
        **{**contract.__dict__, "original_pids": (10, 10)})
    assert any("PID population" in problem
               for problem in _problems(tmp_path, bad))
