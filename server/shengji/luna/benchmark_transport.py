"""Benchmark JSON adapter over the existing contained Codex invocation path."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import time

from .canonical import canonical_json_bytes
from .game import CONTINUATIONS
from .transport import (CodexExecPlannerTransport, CodexTurnTransportError,
                        CODE_MODE_DISABLED_DIAGNOSTIC, CodexProviderResourceError,
                        MAX_TRACE_BYTES, _events_and_usage, _strict_json)


CAPACITY_RETRY_DELAYS = (15, 30, 60)
_CAPACITY_MESSAGE = "Selected model is at capacity. Please try a different model."
_RECOVERED_WEBSOCKET = re.compile(
    r"Reconnecting\.\.\. ([1-5])/5 \(stream disconnected before completion: "
    r"WebSocket protocol error: Connection reset without closing handshake\)")


def _benchmark_events_and_usage(raw):
    """Permit the observed recoverable CLI notice, never failed turns/tools.

    This does not retry an invocation. The caller retains the original trace
    and still requires rc=0, final-file agreement and a valid completed turn.
    Legacy planner transports retain their stricter parser unchanged.
    Unknown error events refuse in this pre-pass; this can change the receipt
    error text when another forbidden event also exists, never acceptance.
    """
    if type(raw) is not bytes or not raw or len(raw) > MAX_TRACE_BYTES:
        raise CodexTurnTransportError("Codex JSONL size drift")
    filtered, reconnects = [], []
    started = completed = False
    last_attempt = 0
    message_after_notice = True
    for line in raw.splitlines():
        if not line:
            continue
        event = _strict_json(line, "Codex JSONL event")
        if type(event) is dict and event.get("type") == "error":
            message = event.get("message")
            match = (_RECOVERED_WEBSOCKET.fullmatch(message)
                     if type(message) is str else None)
            if (set(event) != {"type", "message"} or not match
                    or not started or completed
                    or int(match[1]) <= last_attempt):
                raise CodexTurnTransportError("benchmark reconnect telemetry drift")
            last_attempt = int(match[1])
            reconnects.append(event)
            message_after_notice = False
            continue
        if type(event) is dict:
            started = started or event.get("type") == "turn.started"
            completed = completed or event.get("type") == "turn.completed"
            item = event.get("item")
            if (event.get("type") == "item.completed" and type(item) is dict
                    and item.get("type") == "agent_message"):
                message_after_notice = True
        filtered.append(line)
    if not message_after_notice:
        raise CodexTurnTransportError("no agent message after reconnect notice")
    _, usage, message = _events_and_usage(
        b"\n".join(filtered), use_final_message=True)
    return reconnects, usage, message


def output_schema():
    cards = {"type": "array", "items": {"type": "string"}}
    evaluation = {"type": "object", "additionalProperties": False,
                  "required": ["cards", "continuation"], "properties": {
                      "cards": cards,
                      "continuation": {"type": "string", "enum": list(CONTINUATIONS)}}}
    return {"type": "object", "additionalProperties": False,
            "required": ["cards", "evaluations", "memory"], "properties": {
                "cards": {"anyOf": [cards, {"type": "null"}]},
                "evaluations": {"anyOf": [{"type": "array", "items": evaluation,
                                            "minItems": 1, "maxItems": 16},
                                            {"type": "null"}]},
                "memory": {"type": "string"}}}


class BenchmarkTransport(CodexExecPlannerTransport):
    ALLOWED_MODELS = ("gpt-5.6-sol", "gpt-5.6-luna")

    def __init__(self, *, evidence_root, capacity_retry_delays=(), **kwargs):
        if type(capacity_retry_delays) is not tuple \
                or any(type(delay) is not int or isinstance(delay, bool)
                       for delay in capacity_retry_delays) \
                or capacity_retry_delays not in ((), CAPACITY_RETRY_DELAYS):
            raise CodexTurnTransportError("benchmark capacity retry drift")
        super().__init__(**kwargs)
        self.capacity_retry_delays = capacity_retry_delays
        self.evidence_root = Path(evidence_root)
        self.evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.calls = []

    @staticmethod
    def _capacity_failure(result, final_path):
        """Recognize only the provider's terminal, no-response capacity trace."""
        if (type(result.returncode) is not int or result.returncode <= 0
                or final_path.exists() or final_path.is_symlink()):
            return False
        raw = result.stdout
        if type(raw) is not bytes or not raw:
            return False
        rows = []
        try:
            for line in raw.splitlines():
                if not line:
                    return False
                rows.append(_strict_json(line, "capacity JSONL event"))
        except CodexTurnTransportError:
            return False
        if not all(type(row) is dict for row in rows):
            return False
        if len(rows) not in (4, 5):
            return False
        cursor = 0
        thread = rows[cursor]
        if (set(thread) != {"type", "thread_id"}
                or thread.get("type") != "thread.started"
                or type(thread.get("thread_id")) is not str):
            return False
        cursor += 1
        if cursor < len(rows) and rows[cursor].get("type") == "item.completed":
            warning = rows[cursor]
            item = warning.get("item")
            if (set(warning) != {"type", "item"} or type(item) is not dict
                    or set(item) != {"id", "type", "message"}
                    or type(item.get("id")) is not str
                    or item.get("type") != "error"
                    or item.get("message") != CODE_MODE_DISABLED_DIAGNOSTIC):
                return False
            cursor += 1
        if cursor + 3 != len(rows):
            return False
        if rows[cursor] != {"type": "turn.started"}:
            return False
        error = rows[cursor + 1]
        if (set(error) != {"type", "message"}
                or error.get("type") != "error"
                or error.get("message") != _CAPACITY_MESSAGE):
            return False
        failed = rows[cursor + 2]
        return (set(failed) == {"type", "error"}
                and failed.get("type") == "turn.failed"
                and type(failed.get("error")) is dict
                and set(failed["error"]) == {"message"}
                and failed["error"].get("message") == _CAPACITY_MESSAGE)

    @staticmethod
    def _deadline_remaining(logical_deadline, row_deadline):
        deadline = logical_deadline
        if row_deadline is not None:
            deadline = min(deadline, row_deadline)
        return deadline - time.monotonic_ns(), deadline

    def __call__(self, packet):
        prompt = ("Play Shengji for the observing seat's partnership. Card codes use S/H/C/D "
                  "and ranks 2..A; BJ/LJ are jokers. Use only the provided information. "
                  "Your memory belongs to this seat, not your partner. Return cards to play "
                  "from suggested_actions, or propose another legal action. Suggestions are "
                  "a bounded public-information ballot, not exhaustive or guaranteed winning "
                  "throws. All cards of trump_rank are trumps regardless of printed suit; "
                  "jokers and cards of trump_suit are trumps too. Follow the effective suit "
                  "and play_requirement.required_card_count when following. Only the first "
                  "play defines the lead: two different seats each playing one CK are two "
                  "single-card plays, not a pair lead. The current observation overrides "
                  "stale memory. When leading, required_card_count is null. Follow suit "
                  "and pair/tractor requirements; a failed throw may be "
                  "reduced by the engine. Respect rollout_calls_remaining. "
                  "Return nonempty cards and evaluations=null, OR cards=null and 1 to 16 "
                  "{cards,continuation} "
                  "rollout requests. At most two rollout batches per decision. "
                  "Rollouts use the true world in perfect mode and shared constraint-sampled "
                  "worlds in actor-only mode; results are estimates under the named policy, "
                  "not guaranteed outcomes. Positive signed levels favor your partnership. "
                  "Keep a concise updated memory. No prose outside JSON.\n" +
                  canonical_json_bytes(packet).decode("ascii")).encode("utf-8")
        schema_bytes = canonical_json_bytes(output_schema())
        retry_delays = self.capacity_retry_delays
        logical_deadline = (time.monotonic_ns() + self.timeout_seconds * 1_000_000_000
                            if retry_delays else None)
        earliest_deadline = logical_deadline
        for attempt_ordinal in range(1, len(retry_delays) + 2):
            workspace = Path(tempfile.mkdtemp(prefix="call-", dir=self.evidence_root))
            schema_path, final_path = workspace / "schema.json", workspace / "final.json"
            schema_path.write_bytes(schema_bytes)
            (workspace / "prompt.txt").write_bytes(prompt)
            receipt = {
                "model": self.model, "effort": self.reasoning_effort,
                "accepted": False, "runtime": self.runtime,
                "attempt": attempt_ordinal,
                "attempt_ordinal": attempt_ordinal,
                "retry_enabled": bool(retry_delays),
                "backoff_seconds": 0,
                "backoff_planned": False,
            }
            retry_after = None
            try:
                if retry_delays:
                    timeout, row_deadline = self._dispatch_deadline()
                    if row_deadline is not None:
                        earliest_deadline = min(earliest_deadline, row_deadline)
                    remaining, effective_deadline = self._deadline_remaining(
                        logical_deadline, earliest_deadline)
                    if remaining <= 0:
                        raise CodexProviderResourceError(
                            "Codex turn deadline exceeded before dispatch")
                    timeout = min(timeout, remaining // 1_000_000_000)
                    deadline = effective_deadline
                else:
                    timeout, deadline = self._dispatch_deadline()
                command = self._command(workspace=workspace, schema_path=schema_path,
                                        final_path=final_path)
                result = self.run_command(command, prompt, workspace, timeout)
                (workspace / "stdout.jsonl").write_bytes(result.stdout)
                (workspace / "stderr.txt").write_bytes(result.stderr)
                receipt.update(wall_ms=result.wall_ms, returncode=result.returncode)
                if retry_delays:
                    remaining, _ = self._deadline_remaining(
                        logical_deadline, earliest_deadline)
                    if remaining <= 0:
                        raise CodexProviderResourceError(
                            "Codex game deadline exceeded after dispatch")
                else:
                    self._check_dispatch_deadline(deadline)
                if retry_delays and self._capacity_failure(result, final_path):
                    receipt.update(error_type="provider_capacity",
                                   error="provider_capacity",
                                   capacity_message=_CAPACITY_MESSAGE)
                    if attempt_ordinal < len(retry_delays) + 1:
                        delay = retry_delays[attempt_ordinal - 1]
                        remaining, _ = self._deadline_remaining(
                            logical_deadline, earliest_deadline)
                        if remaining <= delay * 1_000_000_000:
                            raise CodexProviderResourceError(
                                "Codex turn deadline exceeded before capacity retry")
                        receipt.update(backoff_seconds=delay,
                                       backoff_planned=True)
                        retry_after = delay
                    else:
                        raise CodexProviderResourceError(
                            "Codex provider capacity exhausted")
                else:
                    if result.returncode or not final_path.is_file() \
                            or final_path.is_symlink():
                        raise CodexTurnTransportError(
                            "benchmark provider failed or final absent")
                    # JSONL contains intermediate agent messages too. The CLI's
                    # --output-last-message file defines the final answer; bind it to
                    # the last message before the sole completed turn. Never select
                    # an earlier answer by legality or score. Legacy callers stay strict.
                    reconnects, usage, message = _benchmark_events_and_usage(result.stdout)
                    receipt["recovered_reconnects"] = reconnects
                    receipt["usage"] = usage
                    final = _strict_json(final_path.read_bytes(), "benchmark final")
                    if final != _strict_json(message.encode(), "benchmark message"):
                        raise CodexTurnTransportError("benchmark final/message mismatch")
                    if (type(final) is not dict
                            or set(final) != {"cards", "evaluations", "memory"}
                            or type(final["memory"]) is not str
                            or (final["cards"] is None) == (final["evaluations"] is None)):
                        raise CodexTurnTransportError("benchmark action shape refused")
                    key = "evaluations" if final["cards"] is None else "cards"
                    receipt["accepted"] = True  # protocol shape only; engine validation follows
                    answer = {key: final[key], "memory": final["memory"]}
            except BaseException as exc:
                if "error_type" not in receipt:
                    receipt["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                (workspace / "receipt.json").write_bytes(canonical_json_bytes(receipt))
                self.calls.append(dict(receipt, evidence_path=str(workspace)))
            if retry_after is None:
                return answer
            time.sleep(retry_after)
