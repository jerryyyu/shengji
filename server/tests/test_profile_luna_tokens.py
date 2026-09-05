"""Focused offline tests for the PT-Luna private token profiler."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from scripts.profile_luna_tokens import (
    PROMPT_MARKER,
    _canonical,
    _field_bytes,
    profile_roots,
)


def _prompt(packet: dict, prefix: bytes = b"STATIC\n") -> str:
    return base64.b64encode(prefix + PROMPT_MARKER + _canonical(packet)).decode()


def _usage(*, input=10, cached=2, output=8, reasoning=3):
    return {
        "schema": "pt-luna-usage-v1", "input_tokens": input,
        "cached_input_tokens": cached, "cache_write_input_tokens": 0,
        "output_tokens": output, "reasoning_output_tokens": reasoning,
        "total_tokens": input + output, "wall_ms": 1,
    }


def _accepted(tmp_path: Path, number: int, *, provider_hash: str,
              usage=None, packet=None, prompt_prefix=b"STATIC\n"):
    packet = packet or {"schema": "packet", "state": {"turn": number},
                        "decision_sha256": "a" * 64}
    private = {
        "prompt_base64": _prompt(packet, prompt_prefix),
        "response": {"usage": usage} if usage is not None else {},
    }
    body = {
        "kind": "model-response-sealed", "call_index": number,
        "packet_sha256": "p" * 64,
        "attempt": {"attempt_sha256": "attempt", "logical_packet_sha256": "logical"},
        "response": {"provider_response_sha256": provider_hash,
                     "provider_private_evidence": private},
    }
    path = tmp_path / "attempts" / "A" / "journal" / f"{number:06d}-response.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def _refusal(tmp_path: Path, number: int, *, private=None):
    body = {
        "kind": "model-call-refused", "call_index": number,
        "packet_sha256": "p" * 64,
        "attempt": {"attempt_sha256": "attempt", "logical_packet_sha256": "logical"},
        "provider_private_evidence": private,
    }
    path = tmp_path / "attempts" / "A" / "journal" / f"{number:06d}-refusal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_unique_accepted_hash_is_counted_once(tmp_path):
    _accepted(tmp_path, 0, provider_hash="h" * 64, usage=_usage())
    _accepted(tmp_path, 1, provider_hash="h" * 64,
              usage=_usage(input=100, output=100, reasoning=0))
    result = profile_roots([tmp_path])
    assert result["records"]["accepted_unique"] == 1
    assert result["diagnostics"]["duplicate_accepted_count"] == 1
    assert result["usage"]["aggregate"]["total_tokens"] == 18


def test_cached_and_reasoning_are_subsets_not_extra_usage(tmp_path):
    _accepted(tmp_path, 0, provider_hash="h" * 64,
              usage=_usage(input=100, cached=25, output=40, reasoning=17))
    usage = profile_roots([tmp_path])["usage"]["aggregate"]
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 25
    assert usage["uncached_input_tokens"] == 75
    assert usage["output_tokens"] == 40
    assert usage["reasoning_output_tokens"] == 17
    assert usage["non_reasoning_output_tokens"] == 23
    assert usage["total_tokens"] == 140


def test_accepted_and_refusal_for_one_call_are_not_double_counted(tmp_path):
    _accepted(tmp_path, 0, provider_hash="h" * 64, usage=_usage())
    _refusal(tmp_path, 0, private={"usage": _usage(input=99, output=99)})
    result = profile_roots([tmp_path])
    assert result["records"]["accepted_unique"] == 1
    assert result["records"]["refusal_unique"] == 0
    assert result["diagnostics"]["accepted_refusal_conflicts"] == 1
    assert result["usage"]["aggregate"]["total_tokens"] == 18


def test_missing_and_malformed_telemetry_are_unknown_not_zero(tmp_path):
    _accepted(tmp_path, 0, provider_hash="a" * 64, usage=None)
    _accepted(tmp_path, 1, provider_hash="b" * 64,
              usage={"input_tokens": 1, "output_tokens": 1})
    _refusal(tmp_path, 2)
    malformed = tmp_path / "attempts" / "A" / "journal" / "000003-response.json"
    malformed.write_text("{not-json", encoding="utf-8")
    result = profile_roots([tmp_path])
    assert result["diagnostics"]["malformed_json"] == 1
    assert result["diagnostics"]["unknown_telemetry_count"] == 4
    assert result["usage"]["aggregate"]["record_count"] == 0
    assert result["usage"]["aggregate"]["total_tokens"] == 0


def test_prompt_field_aggregate_is_utf8_bytes(tmp_path):
    packet = {
        "schema": "packet", "decision_sha256": "a" * 64,
        "state": {"turn": 1, "note": "é"}, "team": 0,
    }
    _accepted(tmp_path, 0, provider_hash="a" * 64, usage=_usage(), packet=packet)
    result = profile_roots([tmp_path])["prompt_bytes"]
    expected_top = {key: _field_bytes(key, value) for key, value in packet.items()}
    expected_state = {key: _field_bytes(key, value)
                      for key, value in packet["state"].items()}
    assert result["basis"].startswith("UTF-8 bytes")
    assert result["top_level_fields"] == expected_top
    assert result["state_fields"] == expected_state
    assert result["packet_bytes"] == len(_canonical(packet))
    assert result["metadata_hash_occurrences"] == 2
    assert result["metadata_hash_overhead_bytes"] == (
        _field_bytes("schema", packet["schema"])
        + _field_bytes("decision_sha256", packet["decision_sha256"]))
