"""Synthetic preflight seam: authenticated panel-rank bootstrap to reader.

This is not a qualified Linux CLI lane or scientific validation.  The packet,
historical controls, old runtime, terminal seal, selected reader, public-root
binding, fixed-tape prediction, projections, and publication are exercised as
one path.  Interpreter admission/current-runtime authentication, frozen recipe
digest constants are explicitly test-owned boundaries. Most cases fake the
model factory; the real-NumPy case exercises loading and inference using a
tiny synthetic package instead of historical model bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import m9_panel_readout_worker as bootstrap_source
from scripts import panel_rank_worker as worker
from shengji.eval import m9_panel_recipe, selected_panel_reader, tactical

from test_m9_panel_recipe import recipe as valid_recipe
from test_m9_panel_readout_worker import _load_actual_helper
from test_panel_rank_worker_reader_integration import (
    _authorization_bundle,
    _real_selected_bundle,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _pin(path: Path, value: object) -> dict[str, str]:
    raw = _canonical(value)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _complete_authenticated_bundle(tmp_path: Path, monkeypatch, *,
                                   supplied_bot=None,
                                   model_bytes=b"test-owned-synthetic-model"):
    """Complete the reader-integration partial bundle for the real bootstrap."""
    fixtures, fixture, bot, analysis, records, predict_calls = \
        _real_selected_bundle(tmp_path, supplied_bot=supplied_bot)
    (fixture_path, _partial_recipe, panel_path, files,
     _old_invocation_pin, _old_release_pin, spec) = _authorization_bundle(
         tmp_path, analysis, records, fixture, fixtures, model_bytes=model_bytes)

    collection_dir = tmp_path / "collection"
    evidence_dir = tmp_path / "evidence"
    owner_path = Path(files["owner"]["path"])
    saved_path = Path(files["saved_readout"]["path"])
    packet_path = Path(spec["collection_packet"]["path"])

    # Use the full frozen recipe contract, replacing only test-owned paths and
    # the three frozen content digests with bytes staged in this bundle.
    model_path = tmp_path / "synthetic-model.npz"
    model_path.write_bytes(model_bytes)
    saved_sha = hashlib.sha256(saved_path.read_bytes()).hexdigest()
    model_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    fixture_sha = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    recipe = valid_recipe()
    recipe.update(
        fixtures=str(fixture_path), fixture_sha256=fixture_sha,
        model=str(model_path), model_sha256=model_sha,
        output_dir=str(collection_dir), evidence=str(evidence_dir),
        saved_readout=str(saved_path), saved_readout_sha256=saved_sha,
    )

    # The recipe validator remains real; only its frozen digest constants are
    # rebound to the synthetic bytes used by this seam.
    monkeypatch.setattr(m9_panel_recipe, "FIXTURE_SHA256", fixture_sha)
    monkeypatch.setattr(m9_panel_recipe, "MODEL_SHA256", model_sha)
    monkeypatch.setattr(m9_panel_recipe, "SAVED_READOUT_SHA256", saved_sha)

    helper = _load_actual_helper()
    helper_sha = hashlib.sha256(Path(helper.__file__).read_bytes()).hexdigest()
    bootstrap_sha = hashlib.sha256(
        Path(bootstrap_source.__file__).read_bytes()).hexdigest()

    # The collection packet's old runtime is sealed historical evidence; the
    # rank invocation has a distinct current-runtime pin below.
    old_runtime = _pin(collection_dir / "collection-runtime.json", {
        "schema": "shengji-m9-runtime-v1",
        "source_root": "/source/server",
        "source_files": {"scripts/observation_worker.py": helper_sha},
    })
    command = [recipe["python"], "-I", "-B",
               "/source/server/scripts/observation_worker.py", "--panel",
               "--packet", str(packet_path), "--sha256", "PENDING"]
    # The packet digest is needed by all historical controls, so write the
    # packet once with a placeholder-free recipe and then construct controls.
    packet = {
        "schema": "m9-panel-admission-v1", "recipe": recipe,
        "environment": {}, "source_commit": "synthetic-test",
        "hostname": "synthetic-test", "runtime": old_runtime,
        "watchdog": {}, "queue": {}, "release": str(collection_dir / "release.json"),
        "hold": str(collection_dir / "hold.json"),
        "host_lock": "/root/.claude-host.lock",
        "other_locks": ["/root/.claude-peer.lock"],
        "reservation": str(collection_dir / "reservation.json"),
        "status": str(owner_path), "claim": str(collection_dir / "claim.json"),
        "timeout_seconds": 800, "process_timeout_seconds": 900,
    }
    packet_pin = _pin(packet_path, packet)
    digest = packet_pin["sha256"]
    command[-1] = digest

    owner = json.loads(owner_path.read_bytes())
    owner["packet_sha256"] = digest
    files["owner"] = _pin(owner_path, owner)

    controls = {
        "release": _pin(Path(packet["release"]), {
            "schema": "m9-panel-release-v1", "packet_sha256": digest}),
        "claim": _pin(Path(packet["claim"]), {
            "schema": "m9-panel-owner-attempt-v1", "packet_sha256": digest,
            "status": "spent_no_retry", "comparison_validated": False,
            "owner_pid": 123, "inner_command": command,
            "queue_snapshot": {}, "deadline_monotonic": 12345.0}),
        "reservation": _pin(Path(packet["reservation"]), {
            "schema": "codex-m9-panel-reservation-v1", "lane": "m9-panel",
            "packet_sha256": digest, "pid": 123, "count": 15,
            "seeds": [0, 1, 2], "status": packet["status"],
            "output": recipe["output_dir"], "output_root": recipe["output_dir"],
            "result": recipe["output_dir"], "evidence": recipe["evidence"],
            "launcher": command[3], "launcher_sha256": helper_sha}),
        "process_claim": _pin(evidence_dir / "claim.json", {
            "schema": "m9-process-attempt-v1", "command": command,
            "timeout_seconds": 900, "comparison_validated": False}),
    }
    spec["controls"] = controls
    spec["packet_sha256"] = digest
    spec["collection_packet"] = packet_pin
    # This is the current rank-runtime pin.  The receipt deliberately carries
    # the same pin, while the collection packet carries old_runtime above.
    current_runtime = _pin(tmp_path / "rank-runtime.json", {})
    spec["runtime"] = current_runtime
    files["collection"] = {
        "path": str(collection_dir / "terminal.json"),
        "sha256": hashlib.sha256(
            (collection_dir / "terminal.json").read_bytes()).hexdigest(),
    }
    files["owner"] = _pin(owner_path, owner)

    # The selected record was staged by the existing helper after its panel
    # pin was provisionally assembled; bind its final bytes now.
    panel_bytes = _canonical(records[6])
    panel_path.write_bytes(panel_bytes)
    files["validated-006.json"] = {
        "path": str(panel_path), "sha256": hashlib.sha256(panel_bytes).hexdigest()}
    spec["files"] = files

    # Historical receipt inventory is exactly the twenty reader files.  Its
    # runtime is the new invocation's current pin, not the collection runtime.
    receipt = {
        "schema": "m9-panel-readout-receipt-v1",
        "packet_sha256": digest, "collection_packet": packet_pin,
        "controls": controls,
        "terminal_seal": None,
        "input_sha256": {name: pin["sha256"] for name, pin in files.items()},
        "result_sha256": "b" * 64, "invocation_sha256": "c" * 64,
        "runtime": current_runtime, "provenance_verified": False,
    }

    # The seal covers the exact twenty reader pins, four controls, collection
    # packet, and old collection runtime: 26 entries, no outcomes.
    seal_path = tmp_path / "historical-SHA256SUMS"
    seal_refs = [*files.values(), *controls.values(), packet_pin, old_runtime]
    seal_raw = ("".join(f'{entry["sha256"]}  {entry["path"]}\n'
                         for entry in seal_refs)).encode()
    seal_path.write_bytes(seal_raw)
    seal_pin = {"path": str(seal_path), "sha256": hashlib.sha256(seal_raw).hexdigest()}
    receipt["terminal_seal"] = seal_pin
    receipt_pin = _pin(tmp_path / "receipt.json", receipt)
    spec["receipt"] = receipt_pin
    spec["terminal_seal"] = seal_pin

    invocation_pin = _pin(tmp_path / "invocation.json", spec)
    # New rank RELEASE is intentionally distinct from historical packet release.
    release_pin = _pin(tmp_path / "fresh-rank-release.json", {
        "schema": "panel-rank-release-v1", "decision": "RELEASE",
        "invocation_sha256": invocation_pin["sha256"],
        "ownership_dir": spec["ownership_dir"], "packet_sha256": digest,
        "index": spec["index"],
    })
    return {
        "fixtures": fixtures, "fixture": fixture, "bot": bot,
        "records": records, "predict_calls": predict_calls,
        "files": files, "panel_path": panel_path, "spec": spec,
        "packet": packet, "packet_pin": packet_pin, "controls": controls,
        "seal_path": seal_path, "seal_pin": seal_pin,
        "invocation_pin": invocation_pin, "release_pin": release_pin,
        "helper_sha": helper_sha, "bootstrap_sha": bootstrap_sha,
        "current_runtime": current_runtime,
    }


def _install_allowed_boundaries(monkeypatch, bundle):
    """Keep only interpreter/current-runtime/factory boundaries synthetic."""
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)

    real_load_bootstrap = worker._load_bootstrap

    def load_bootstrap(digest):
        bootstrap = real_load_bootstrap(digest)
        real_load_helper = bootstrap._load_helper

        def load_helper(helper_sha):
            helper = real_load_helper(helper_sha)
            # Current source/runtime authentication is an explicit synthetic
            # boundary; historical collection-runtime auth remains real.
            helper._read_runtime = lambda *_: {
                "source_files": {
                    "scripts/observation_worker.py": bundle["helper_sha"],
                    "scripts/m9_panel_readout_worker.py": bundle["bootstrap_sha"],
                }
            }
            return helper

        bootstrap._load_helper = load_helper
        return bootstrap

    monkeypatch.setattr(worker, "_load_bootstrap", load_bootstrap)

    from shengji.eval import observation_runtime
    monkeypatch.setattr(observation_runtime, "ObservationRuntime",
                        lambda *args, **kwargs: type(
                            "SyntheticRuntime", (), {"check": lambda self: True})())

    factory_calls = []

    def factory(environment, *, seed):
        factory_calls.append(seed)
        return "synthetic-model", bundle["bot"]

    monkeypatch.setattr(tactical, "bot_from_environ", factory)
    return factory_calls


@pytest.mark.parametrize("scenario", ["success", "corrupt-seal", "owner-claim"])
def test_synthetic_preflight_authenticated_bootstrap_to_real_reader(
        tmp_path, monkeypatch, scenario):
    """Synthetic preflight seam, not full qualified Linux CLI/scientific validation."""
    bundle = _complete_authenticated_bundle(tmp_path, monkeypatch)
    if scenario == "corrupt-seal":
        bundle["seal_path"].write_bytes(b"corrupted historical seal\n")
    elif scenario == "owner-claim":
        claim_path = Path(bundle["controls"]["claim"]["path"])
        claim = json.loads(claim_path.read_bytes())
        claim["owner_pid"] = 124
        bundle["controls"]["claim"] = _pin(claim_path, claim)
        bundle["spec"]["controls"] = bundle["controls"]
        # Repin the historical receipt and exact 26-entry seal after the claim
        # mutation; the packet's owner claim is still intentionally rejected.
        receipt_path = Path(bundle["spec"]["receipt"]["path"])
        receipt = json.loads(receipt_path.read_bytes())
        receipt["controls"] = bundle["controls"]
        receipt["terminal_seal"] = None
        seal_refs = [*bundle["files"].values(), *bundle["controls"].values(),
                     bundle["packet_pin"], bundle["packet"]["runtime"]]
        raw = ("".join(f'{entry["sha256"]}  {entry["path"]}\n'
                       for entry in seal_refs)).encode()
        bundle["seal_path"].write_bytes(raw)
        bundle["seal_pin"] = {"path": str(bundle["seal_path"]),
                               "sha256": hashlib.sha256(raw).hexdigest()}
        receipt["terminal_seal"] = bundle["seal_pin"]
        bundle["spec"]["terminal_seal"] = bundle["seal_pin"]
        bundle["spec"]["receipt"] = _pin(receipt_path, receipt)
        bundle["invocation_pin"] = _pin(
            Path(bundle["invocation_pin"]["path"]), bundle["spec"])
        bundle["release_pin"] = _pin(Path(bundle["release_pin"]["path"]), {
            "schema": "panel-rank-release-v1", "decision": "RELEASE",
            "invocation_sha256": bundle["invocation_pin"]["sha256"],
            "ownership_dir": bundle["spec"]["ownership_dir"],
            "packet_sha256": bundle["spec"]["packet_sha256"],
            "index": bundle["spec"]["index"],
        })

    factory_calls = _install_allowed_boundaries(monkeypatch, bundle)
    monkeypatch.setattr(sys, "path", list(sys.path))
    panel_reads = []
    real_stable_read = selected_panel_reader.guards._stable_read

    def track_panel(path, limit):
        if Path(path) == bundle["panel_path"]:
            panel_reads.append(Path(path))
        return real_stable_read(path, limit)

    monkeypatch.setattr(selected_panel_reader.guards, "_stable_read", track_panel)
    output = Path(bundle["spec"]["output_dir"])
    ownership = Path(bundle["spec"]["ownership_dir"])
    args = (bundle["invocation_pin"]["path"],
            bundle["invocation_pin"]["sha256"],
            bundle["release_pin"]["path"],
            bundle["release_pin"]["sha256"],
            bundle["bootstrap_sha"], bundle["helper_sha"])

    if scenario != "success":
        expected = ("terminal seal SHA mismatch" if scenario == "corrupt-seal"
                    else "historical reservation binding mismatch")
        with pytest.raises(ValueError, match=expected):
            worker.run(*args)
        assert panel_reads == []
        assert factory_calls == []
        assert not output.exists()
        assert not ownership.exists()
        return

    receipt = worker.run(*args)
    result_path = output / "result.json"
    result = json.loads(result_path.read_bytes())
    assert panel_reads == [bundle["panel_path"]]
    assert bundle["predict_calls"] == [64]
    assert factory_calls == [bundle["records"][6]["job"]["seed"]]
    assert set(result["projections"]) == {"control", "treatment"}
    assert receipt["result_sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert json.loads((output / "receipt.json").read_bytes()) == receipt
    assert receipt["release"] == bundle["release_pin"]
    assert receipt["previous_receipt"] == bundle["spec"]["receipt"]
    assert bundle["release_pin"]["path"] != bundle["packet"]["release"]


@pytest.mark.parametrize("changed_input", ["release", "model", "panel"])
def test_authenticated_prediction_drift_refuses_publication(
        tmp_path, monkeypatch, changed_input):
    """Real post-prediction stamp checks must reject a mid-call mutation."""
    bundle = _complete_authenticated_bundle(tmp_path, monkeypatch)
    factory_calls = _install_allowed_boundaries(monkeypatch, bundle)
    monkeypatch.setattr(sys, "path", list(sys.path))
    target = {
        "release": Path(bundle["release_pin"]["path"]),
        "model": Path(bundle["packet"]["recipe"]["model"]),
        "panel": bundle["panel_path"],
    }[changed_input]
    predict = bundle["bot"].predict

    def mutate_during_prediction(batch):
        result = predict(batch)
        # Change size as well as metadata, avoiding timestamp-resolution
        # assumptions. Only test-owned bytes are touched.
        target.write_bytes(target.read_bytes() + b"\nchanged during prediction\n")
        return result

    monkeypatch.setattr(bundle["bot"], "predict", mutate_during_prediction)
    args = (bundle["invocation_pin"]["path"],
            bundle["invocation_pin"]["sha256"],
            bundle["release_pin"]["path"],
            bundle["release_pin"]["sha256"],
            bundle["bootstrap_sha"], bundle["helper_sha"])
    expected = ("authenticated control changed" if changed_input == "release"
                else "panel rank authenticated input changed")
    with pytest.raises(ValueError, match=expected):
        worker.run(*args)

    output = Path(bundle["spec"]["output_dir"])
    ownership = Path(bundle["spec"]["ownership_dir"])
    assert bundle["predict_calls"] == [64]
    assert len(factory_calls) == 1
    assert not (output / "result.json").exists()
    assert not (output / "receipt.json").exists()
    refusal = json.loads((output / "refusal.json").read_bytes())
    assert refusal["stage"] == "rank-projection"
    assert refusal["error_type"] == "ValueError"
    claim = (ownership / "claim.json").read_bytes()
    assert json.loads((output / "claim.json").read_bytes())["status"] == "spent_no_retry"
    # A second invocation cannot turn a rejected attempt into fresh work.
    with pytest.raises(ValueError, match="fresh output required"):
        worker.run(*args)
    assert (ownership / "claim.json").read_bytes() == claim
    assert bundle["predict_calls"] == [64]
    assert len(factory_calls) == 1


def test_authenticated_real_numpy_factory_to_publication(tmp_path, monkeypatch):
    """Use real model loading/encoding/inference; runtime remains synthetic."""
    from test_cwv_puct_package_prior import _write_joint_package
    from shengji.eval import m9_panel_plan
    import test_m9_panel_plan
    import test_m9_panel_readout
    import test_panel_rank_worker_reader_integration as reader_fixture

    model_path = tmp_path / "tiny.npz"
    model_sha = _write_joint_package(model_path, 3)
    # Rebind only test-owned population identity; production source is unchanged.
    for module in (m9_panel_plan, test_m9_panel_plan,
                   test_m9_panel_readout, reader_fixture):
        monkeypatch.setattr(module, "CHECKPOINT_SHA256", model_sha)
    real_factory = tactical.bot_from_environ
    env = tactical.observation_comparison_environs(str(model_path), model_sha)[
        m9_panel_recipe.POLICY]
    _, fixture_bot = real_factory(env, seed=0)
    bundle = _complete_authenticated_bundle(
        tmp_path, monkeypatch, supplied_bot=fixture_bot,
        model_bytes=model_path.read_bytes())
    _install_allowed_boundaries(monkeypatch, bundle)
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = []
    predictions = []

    def tracked_factory(environment, *, seed):
        name, bot = real_factory(environment, seed=seed)
        calls.append(bot)
        real_predict = bot.predict

        def tracked_predict(batch):
            predictions.append(len(batch))
            return real_predict(batch)

        bot.predict = tracked_predict
        return name, bot

    monkeypatch.setattr(tactical, "bot_from_environ", tracked_factory)
    receipt = worker.run(
        bundle["invocation_pin"]["path"], bundle["invocation_pin"]["sha256"],
        bundle["release_pin"]["path"], bundle["release_pin"]["sha256"],
        bundle["bootstrap_sha"], bundle["helper_sha"])
    assert len(calls) == 1
    assert predictions == [64]
    assert calls[0].checkpoint_sha256 == model_sha
    output = Path(bundle["spec"]["output_dir"])
    result_bytes = (output / "result.json").read_bytes()
    result = json.loads(result_bytes)
    assert set(result["projections"]) == {"control", "treatment"}
    assert receipt["model_sha256"] == model_sha
    assert receipt["result_sha256"] == hashlib.sha256(result_bytes).hexdigest()
    assert json.loads((output / "receipt.json").read_bytes()) == receipt
    assert not (output / "refusal.json").exists()
