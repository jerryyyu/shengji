"""Exercise the timing reader with synthetic captures in the producer's wire format."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import read_timing as reader


@pytest.fixture
def capture():
    names = {side: identity[0] for side, identity in reader.SIDES.items()}
    events = [{"kind": "preflight", "baseline": [0, 0, 0]}, {"kind": "names", **names}]
    worker = {"VmHWM": 81 * 1024}
    server = {"VmHWM": 148 * 1024}
    for side, (name, unified, belief) in reader.SIDES.items():
        events.append({"kind": "identity", "side": side, "env_bot": name, "policy": name,
                       "unified_sha256": unified, "belief_sha256": belief, "tree": str(reader.APP),
                       "fast": True, "have_native": True, "compiled_decompose": True})
    decisions = []
    for seed in reader.SEEDS:
        events.append({"kind": "round_start", "seed": seed})
        for phase in ["bury"] + ["play"] * 51:
            index = len(decisions)
            decisions.append({"index": index, "seed": seed, "phase": phase,
                              "first": "A" if index % 2 == 0 else "B", **{
                                  side: {"policy": name, "copy_s": .01, "decide_s": .99, "total_s": 1,
                                         "schema": reader.PLAY_SCHEMA if phase == "play" else None,
                                         "fallback": False, "belief_fallback_any": 0 if phase == "play" else None,
                                         "unified": {"shared": 1}, "status": dict(worker)}
                                  for side, name in names.items()
                              }})
        events.append({"kind": "round_end", "seed": seed, "phase": "round_end", "decisions": len(decisions)})
    events.append({"kind": "terminal", "status": "DONE", "elapsed": 500, "decisions": len(decisions),
                   "healthz_end": {"ok": True, "rooms": 0, "bot": names["A"],
                                   "activity": {"rooms_created": 0, "games_started": 0}},
                   "worker_final": {side: {"status": dict(worker)} for side in names}})
    samples = [{"tag": tag, "server": server, "mem_available_kb": 1024 * 1024}
               for tag in ("before", "watch", "after")]
    return {"events": events, "decisions": decisions, "samples": samples}


def write(directory, capture):
    manifest = []
    for name, rows in sorted(capture.items()):
        filename = f"{name}.jsonl"
        payload = "".join(json.dumps(row) + "\n" for row in rows).encode()
        (directory / filename).write_bytes(payload)
        manifest.append(f"{hashlib.sha256(payload).hexdigest()}  {filename}\n")
    seal = "".join(manifest).encode()
    (directory / "SHA256SUMS").write_bytes(seal)
    return hashlib.sha256(seal).hexdigest()


def test_cli_consumes_complete_capture(tmp_path, capture):
    seal = write(tmp_path, capture)
    cli = Path(reader.__file__)
    result = subprocess.run([sys.executable, str(cli), str(tmp_path), "--seal-sha256", seal], text=True, capture_output=True, check=True)
    parsed = json.loads(result.stdout)
    assert parsed["verdict"] == "PASS"
    assert parsed["paired_plays"] == 306
    assert parsed["wall_ratio_B_over_A"] == 1.0
    assert parsed["memory"]["projected_server_mib"] == 229


@pytest.mark.parametrize(("where", "mutate", "reason"), [
    ("events", lambda rows: rows.pop(), "terminal"),
    ("events", lambda rows: rows.insert(-1, {"kind": "abort"}), "abort"),
    ("events", lambda rows: rows[-1].update(status="ABORT"), "did not complete"),
    ("events", lambda rows: rows[2].update(belief_sha256="other"), "wrong serving identity"),
    ("events", lambda rows: rows[5].update(seed=53006), "round 53000"),
    ("decisions", lambda rows: rows[4].update(first="B"), "out-of-order"),
    ("decisions", lambda rows: rows[9].pop("B"), "'B'"),
    ("decisions", lambda rows: rows[1]["B"].update(unified={"shared": 0}), "shared unified"),
    ("decisions", lambda rows: rows[1]["B"].pop("belief_fallback_any"), "belief_fallback_any"),
    ("decisions", lambda rows: rows[1]["B"].update(belief_fallback_any=None), "belief fallback tally"),
    ("decisions", lambda rows: rows[2]["A"].update(belief_fallback_any=False), "belief fallback tally"),
    ("decisions", lambda rows: rows[1]["B"].update(fallback=True), "play schema and fallback flag"),
    ("decisions", lambda rows: rows[1]["A"].update(schema="other"), "play schema and fallback flag"),
    ("decisions", lambda rows: rows[-1]["B"].update(total_s=float("nan")), "invalid measurement"),
    ("samples", lambda rows: rows[1].update(mem_available_kb=1000), "watchdog floor"),
])
def test_incomplete_or_invalid_capture_cannot_pass(tmp_path, capture, capsys, where, mutate, reason):
    mutate(capture[where])
    seal = write(tmp_path, capture)
    assert reader.main([str(tmp_path), "--seal-sha256", seal]) == 2
    decoded = json.loads(capsys.readouterr().out)
    assert decoded["verdict"] == "INSUFFICIENT"
    assert reason in decoded["reason"]


def test_latency_gate_uses_unrounded_ratio(tmp_path, capture):
    for row in capture["decisions"]:
        row["B"].update(decide_s=1.09004, total_s=1.10004)
    seal = write(tmp_path, capture)
    decision = reader.decide(tmp_path, seal)
    assert decision["verdict"] == "FAIL"
    assert not decision["gates"]["latency"]
    assert round(decision["wall_ratio_B_over_A"], 4) == 1.10


def test_fallback_and_peak_memory_gates_include_worker_terminal(tmp_path, capture):
    capture["decisions"][1]["B"].update(belief_fallback_any=1)
    final = capture["events"][-1]["worker_final"]
    final["A"]["status"]["VmHWM"] = 1200 * 1024
    final["B"]["status"]["VmHWM"] = 1500 * 1024
    seal = write(tmp_path, capture)
    decision = reader.decide(tmp_path, seal)
    assert decision["verdict"] == "FAIL"
    assert decision["memory"]["projected_server_mib"] == 1648
    assert decision["gates"] == {"latency": True, "play_fallbacks": True,
                                 "belief_fallbacks": False, "memory": False}



def test_rejects_seal_and_capture_drift_before_parsing(tmp_path, capture):
    seal = write(tmp_path, capture)
    with pytest.raises(ValueError, match="seal SHA-256 mismatch"):
        reader.decide(tmp_path, "0" * 64)
    path = tmp_path / "decisions.jsonl"
    path.write_text("broken JSON", encoding="utf-8")
    with pytest.raises(ValueError, match="capture bytes differ"):
        reader.decide(tmp_path, seal)



def test_actual_control_play_fallback_can_omit_belief_tally(tmp_path, capture):
    capture["decisions"][1]["A"].update(
        schema=reader.PLAY_FALLBACK_SCHEMA, fallback=True, belief_fallback_any=None, unified=None,
    )
    seal = write(tmp_path, capture)
    decision = reader.decide(tmp_path, seal)
    assert decision["verdict"] == "PASS"
    assert decision["fallbacks"]["A"] == {"play": 1, "belief": 0}
