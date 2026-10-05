"""S10 reader-to-rank seam: one real secondary history-primed panel.

The authorization and recipe/model/runtime checks are synthetic boundary
inputs.  The selected reader, public root reconstruction, card conservation,
single fixed-tape predictor call, dual-arm projection, and exclusive
publication are deliberately real.  This is not a collection or readout
test: its retained panel is a test-owned JSON snapshot.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import observation_worker as helper
from scripts import panel_rank_worker as worker
from shengji.eval import m9_panel_recipe
from shengji.eval import m9_panel_readout
from shengji.eval import m9_panel_worker
from shengji.eval import selected_panel_reader
from shengji.eval import tactical
from shengji.eval.ballot_full_pool import summarize_full_pool_matrix
from shengji.eval.m9_panel_plan import (
    CHECKPOINT_SHA256,
    ROOTS,
    build_m9_panel_plan,
)
from shengji.eval.panel_rank_root import bind_panel_rank_root
from shengji.eval.public_refusal_history import public_root_with_ledger
from shengji.harvest.legal import enumerate_legal
from test_m9_panel_readout import _records
from test_m9_panel_completion import receipts
from test_refusal_constraints import served


def _write_json(path: Path, value: object) -> dict[str, str]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _real_selected_bundle(tmp_path: Path, *, supplied_bot=None):
    """Build one reader-valid retained record around a real public root."""
    fixtures_path = (Path(__file__).parent / "tactical" /
                     "public_observations.jsonl")
    fixtures = tactical.load_fixtures(fixtures_path)
    fixture = next(fx for fx in fixtures
                   if fx.id == ROOTS[1])  # 4-action secondary root
    root, _, ledger_receipt = public_root_with_ledger(
        fixture, mode="history-primed", fill_seed=0)

    # The helper gives us the real PVSearchBot shape and sampler; its predictor
    # is replaced below with a deterministic test-owned 54-column policy.
    bot = supplied_bot if supplied_bot is not None else served(seed=0, worlds=64)
    if supplied_bot is None:
        bot.config = replace(bot.config, checkpoint_sha256=CHECKPOINT_SHA256)
        bot.checkpoint_sha256 = CHECKPOINT_SHA256
    calls: list[int] = []

    def predict(batch):
        calls.append(len(batch))
        return np.tile(np.arange(54, dtype=np.float64), (len(batch), 1))

    if supplied_bot is None:
        bot.predict = predict
    legal = enumerate_legal(root, fixture.seat, cap=bot.cap)
    assert legal.complete and legal.count == 4

    # Reuse the existing synthetic analysis/plan/capture shape, but replace
    # this one saved secondary ballot with the actual legal root actions.
    analysis, records = _records()
    root_analysis = next(item for item in analysis["roots"]
                         if item["id"] == fixture.id)
    seed_row = next(item for item in root_analysis["seeds"] if item["seed"] == 0)
    for arm in ("control", "treatment"):
        decision = seed_row[arm]["decision"]
        decision["admitted"] = copy.deepcopy(legal.actions)
        decision["admitted_indices"] = list(range(len(legal.actions)))
        decision["selected_index"] = len(legal.actions) - 1
        decision["value_means"] = [float(i) for i in range(len(legal.actions))]
    plan = build_m9_panel_plan(analysis)
    selected_job = plan[6]  # ROOTS[1], history-primed, seed 0
    assert selected_job["fixture_id"] == fixture.id

    values = [float(i) for i in range(len(legal.actions))]
    matrix = [values[:] for _ in range(64)]
    points = [[0] * len(legal.actions) for _ in range(64)]
    capture = {
        "schema": "fixed-tape-same-leaf-capture-v1",
        "actions": copy.deepcopy(legal.actions),
        "world_count": 64,
        "value_matrix": matrix,
        "signed_trick_points": points,
        "serving_value_means": values,
        "batches": (64 * len(legal.actions) + bot.batch_size - 1) // bot.batch_size,
    }
    collection = {
        "schema": "fixed-tape-history-primed-panel-v1",
        "full_pool_capture": capture,
        "shared_matrix_summary": summarize_full_pool_matrix(
            legal.actions, selected_job["control_ballot"],
            selected_job["treatment_ballot"], matrix),
        "union_is_projection": True,
        "saved_ballots_generated_under_this_sampler": False,
    }
    panel = {
        "schema": "public-fixture-panel-v1",
        "fixture_id": fixture.id,
        "mode": "history-primed",
        "seed": 0,
        "fill_seed": 0,
        "config": asdict(bot.config),
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "effective": {key: getattr(bot, key)
                      for key in ("worlds", "cap", "batch_size", "candidates")},
        "legal_count": legal.count,
        "actions": copy.deepcopy(legal.actions),
        # Repeated public-root placeholders are valid deterministic worlds for
        # this seam: root binding and the conservation validator still inspect
        # every one, while no sampled/model/history artifact is introduced.
        "worlds": [[copy.deepcopy(root.hands), list(root.buried)]
                    for _ in range(64)],
        "tape_receipt": {
            "schema": "public-refusal-tape-v1",
            "mode": "history-primed",
            "seed": 0,
            "fill_seed": 0,
            "world_count": 64,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "ledger_receipt": ledger_receipt,
        },
        "collection": collection,
    }
    # Run the real root binding once while preparing the fixture; this also
    # proves the deterministic world tape is compatible with public voids.
    bind_panel_rank_root(panel, fixture, bot)
    records[6] = {
        "job": copy.deepcopy(selected_job),
        "panel": panel,
        "replay_consistency": None,
        "validation_status": "passed",
        "replay_failure": None,
        "ledger_cadence": "single-seat-actor-turns",
    }
    return fixtures, fixture, bot, analysis, records, calls


def _authorization_bundle(tmp_path: Path, analysis, records, fixture, fixtures,
                          *, model_bytes=b"test-owned-synthetic-model"):
    collection_dir = tmp_path / "collection"
    evidence_dir = tmp_path / "evidence"
    collection_dir.mkdir()
    evidence_dir.mkdir()
    owner, process, terminal = receipts()
    owner_path = tmp_path / "owner.json"
    process_path = evidence_dir / "process.json"
    terminal_path = collection_dir / "terminal.json"
    owner_pin = _write_json(owner_path, owner)
    process_pin = _write_json(process_path, process)
    _write_json(terminal_path, terminal)
    saved_path = tmp_path / "saved-readout.json"
    saved_pin = _write_json(saved_path, {"analysis": analysis, "provenance": {}})
    plan_path = collection_dir / "plan.json"
    plan = build_m9_panel_plan(analysis)
    plan_pin = _write_json(plan_path, {
        "schema": "m9-panel-attempt-v1",
        "jobs": plan,
        "analysis_sha256": hashlib.sha256(
            selected_panel_reader.guards._canonical(analysis)).hexdigest(),
        "provenance_verified": False,
    })
    panel_path = collection_dir / "validated-006.json"
    # The caller supplies the selected record through this temporary marker;
    # the record itself is written by the test after this helper returns.

    model_path = tmp_path / "synthetic-model.npz"
    model_path.write_bytes(model_bytes)
    fixture_path = tmp_path / "fixtures.jsonl"
    fixture_path.write_bytes(b"\n".join(
        json.dumps(fx.to_json(), sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode() for fx in fixtures))
    packet_recipe = {
        "fixtures": str(fixture_path),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "model": str(model_path),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "output_dir": str(collection_dir),
        "evidence": str(evidence_dir),
        "saved_readout": str(saved_path),
        "saved_readout_sha256": saved_pin["sha256"],
    }
    packet_path = tmp_path / "packet.json"
    packet = {"schema": "m9-panel-admission-v1",
              "status": str(owner_path), "recipe": packet_recipe}
    packet_pin = _write_json(packet_path, packet)
    owner["packet_sha256"] = packet_pin["sha256"]
    owner_pin = _write_json(owner_path, owner)

    def pin(name):
        return {"path": str(tmp_path / f"unused-{name}.json"),
                "sha256": "a" * 64}

    files = {"owner": owner_pin, "process": process_pin,
             "collection": {"path": str(terminal_path),
                             "sha256": hashlib.sha256(terminal_path.read_bytes()).hexdigest()},
             "saved_readout": saved_pin, "plan": plan_pin}
    files.update({f"validated-{index:03d}.json":
                  ({"path": str(panel_path), "sha256": "PANEL_SHA"}
                   if index == 6 else pin(f"validated-{index:03d}"))
                  for index in range(15)})
    # Replace the temporary marker with the actual record bytes after the
    # complete bundle has been assembled by the caller.
    files["validated-006.json"] = {"path": str(panel_path), "sha256": ""}
    controls = {name: pin(name) for name in
                ("release", "claim", "reservation", "process_claim")}
    runtime = pin("runtime")
    terminal_seal = pin("terminal-seal")
    old_runtime = pin("old-runtime")
    receipt = {
        "schema": "m9-panel-readout-receipt-v1",
        "packet_sha256": packet_pin["sha256"],
        "collection_packet": packet_pin,
        "controls": controls,
        "terminal_seal": terminal_seal,
        "input_sha256": {name: pin_value["sha256"]
                         for name, pin_value in files.items()},
        "result_sha256": "b" * 64,
        "invocation_sha256": "c" * 64,
        "runtime": old_runtime,
        "provenance_verified": False,
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_pin = _write_json(receipt_path, receipt)
    spec = {
        "schema": "panel-rank-invocation-v1",
        "index": 6,
        "timeout_seconds": 30,
        "output_dir": str(tmp_path / "rank-output"),
        "ownership_dir": str(tmp_path / "rank-owner"),
        "files": files,
        "packet_sha256": packet_pin["sha256"],
        "collection_packet": packet_pin,
        "controls": controls,
        "runtime": runtime,
        "terminal_seal": terminal_seal,
        "receipt": receipt_pin,
    }
    invocation_path = tmp_path / "invocation.json"
    invocation_pin = _write_json(invocation_path, spec)
    release = {"schema": "panel-rank-release-v1", "decision": "RELEASE",
               "invocation_sha256": invocation_pin["sha256"],
               "ownership_dir": spec["ownership_dir"],
               "packet_sha256": spec["packet_sha256"], "index": spec["index"]}
    release_pin = _write_json(tmp_path / "release.json", release)
    return (fixture_path, packet_recipe, panel_path, files,
            invocation_pin, release_pin, spec)


@pytest.mark.parametrize("damage", [False, True])
def test_real_selected_reader_root_capture_projection_and_publication(tmp_path, monkeypatch, damage):
    fixtures, fixture, bot, analysis, records, calls = _real_selected_bundle(tmp_path)
    (fixture_path, recipe, panel_path, files,
     invocation_pin, release_pin, spec) = _authorization_bundle(
         tmp_path, analysis, records, fixture, fixtures)
    if damage:
        from shengji.ai.memory import Memory
        from shengji.eval.public_refusal_history import public_root_with_ledger
        root, _, _ = public_root_with_ledger(fixture, mode="history-primed", fill_seed=0)
        memory = Memory(root, fixture.seat,
                        own_kitty=getattr(bot.sampler, "BANKER_KITTY", True))
        hands = records[6]["panel"]["worlds"][0][0]
        buried = records[6]["panel"]["worlds"][0][1]
        target_seat = next((seat for seat in range(4)
                            if seat != fixture.seat and memory.voids[seat]), None)
        assert target_seat is not None, memory.voids
        source = next(
            (("hand", seat, index)
             for seat in range(4) if seat != target_seat
             for index, card in enumerate(hands[seat])
             if root.ordering.eff_suit(card) in memory.voids[target_seat]),
            None)
        if source is None:
            source = next(
                (("buried", None, index)
                 for index, card in enumerate(buried)
                 if root.ordering.eff_suit(card) in memory.voids[target_seat]),
                None)
        assert source is not None, memory.voids[target_seat]
        kind, seat, index = source
        if kind == "hand":
            hands[seat][index], hands[target_seat][0] = (
                hands[target_seat][0], hands[seat][index])
        else:
            buried[index], hands[target_seat][0] = (
                hands[target_seat][0], buried[index])
    panel_bytes = json.dumps(records[6], sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode()
    panel_path.write_bytes(panel_bytes)
    files["validated-006.json"]["sha256"] = hashlib.sha256(panel_bytes).hexdigest()
    # The invocation/receipt were written before the final panel pin was known;
    # rewrite the dependent canonical documents with the final inventory.
    spec["files"] = files
    receipt_path = Path(spec["receipt"]["path"])
    receipt = json.loads(receipt_path.read_bytes())
    receipt["input_sha256"] = {name: pin["sha256"] for name, pin in files.items()}
    spec["receipt"] = _write_json(receipt_path, receipt)
    invocation_pin = _write_json(Path(invocation_pin["path"]), spec)
    release = {"schema": "panel-rank-release-v1", "decision": "RELEASE",
               "invocation_sha256": invocation_pin["sha256"],
               "ownership_dir": spec["ownership_dir"],
               "packet_sha256": spec["packet_sha256"], "index": spec["index"]}
    release_pin = _write_json(Path(release_pin["path"]), release)

    # Frozen recipe/model admission and factory/runtime are the only synthetic
    # boundaries.  No selected-reader, root, tape, projection, or I/O seam is
    # replaced.
    monkeypatch.setattr(m9_panel_recipe, "validate_panel_recipe", lambda _: None)
    monkeypatch.setattr(m9_panel_recipe, "panel_model_environ", lambda _: {})
    monkeypatch.setattr(tactical, "bot_from_environ",
                        lambda env, *, seed: ("synthetic-model", bot))
    def forbidden(*args, **kwargs):
        raise AssertionError("collection, resampling, values and full readout are forbidden")
    monkeypatch.setattr(m9_panel_readout, "summarize_m9_panels", forbidden)
    monkeypatch.setattr(m9_panel_readout, "read_completed_m9_panels", forbidden)
    monkeypatch.setattr(m9_panel_worker, "collect_m9_panels", forbidden)
    monkeypatch.setattr(bot, "_worlds", forbidden)
    monkeypatch.setattr(bot, "_score_leaves", forbidden)
    monkeypatch.setattr(bot.evaluator, "score", forbidden)
    before_record = copy.deepcopy(records[6])
    before_rng = bot.sampler.rng.getstate()
    panel_reads = []
    original_read = selected_panel_reader.guards._stable_read

    def track_panel_read(path, limit):
        if Path(path) == panel_path:
            panel_reads.append(Path(path))
        return original_read(path, limit)

    monkeypatch.setattr(selected_panel_reader.guards, "_stable_read", track_panel_read)
    selected = worker.read_rank_authorization(helper, invocation_pin, release_pin)[1]
    assert selected["panel"]["path"] == str(panel_path)
    if damage:
        with pytest.raises(ValueError):
            worker.execute_rank_once(
                helper, spec, selected, {"recipe": recipe}, SimpleNamespace(check=lambda: True),
                invocation_sha256=invocation_pin["sha256"], release_pin=release_pin,
                check_authorization=lambda: True)
        assert panel_reads == [panel_path]
        assert calls == []
        assert not (tmp_path / "rank-output" / "receipt.json").exists()
        refusal = json.loads((tmp_path / "rank-output" / "refusal.json").read_bytes())
        assert refusal["stage"] == "rank-projection"
        assert "public voids" in refusal["reason"]
        return
    receipt = worker.execute_rank_once(
        helper, spec, selected, {"recipe": recipe},
        SimpleNamespace(check=lambda: True),
        invocation_sha256=invocation_pin["sha256"], release_pin=release_pin,
        check_authorization=lambda: True)

    result_path = tmp_path / "rank-output" / "result.json"
    result = json.loads(result_path.read_bytes())
    assert panel_reads == [panel_path]
    assert calls == [64]
    assert records[6] == before_record
    assert panel_path.read_bytes() == panel_bytes
    assert bot.sampler.rng.getstate() == before_rng
    assert result["capture"]["world_count"] == 64
    assert set(result["projections"]) == {"control", "treatment"}
    assert result["provenance_verified"] is False
    assert receipt["result_sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert json.loads((tmp_path / "rank-output" / "receipt.json").read_bytes()) == receipt
