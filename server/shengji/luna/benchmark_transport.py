"""Benchmark JSON adapter over the existing contained Codex invocation path."""
from __future__ import annotations

from pathlib import Path
import tempfile

from .canonical import canonical_json_bytes
from .game import CONTINUATIONS
from .transport import (CodexExecPlannerTransport, CodexTurnTransportError,
                        _events_and_usage, _strict_json)


def output_schema():
    cards = {"type": "array", "items": {"type": "string"}}
    evaluation = {"type": "object", "additionalProperties": False,
                  "required": ["cards", "continuation"], "properties": {
                      "cards": cards,
                      "continuation": {"type": "string", "enum": list(CONTINUATIONS)}}}
    return {"type": "object", "additionalProperties": False,
            "required": ["cards", "evaluations", "memory"], "properties": {
                "cards": {"anyOf": [cards, {"type": "null"}]},
                "evaluations": {"anyOf": [{"type": "array", "items": evaluation},
                                            {"type": "null"}]},
                "memory": {"type": "string"}}}


class BenchmarkTransport(CodexExecPlannerTransport):
    ALLOWED_MODELS = ("gpt-5.6-sol", "gpt-5.6-luna")

    def __init__(self, *, evidence_root, **kwargs):
        super().__init__(**kwargs)
        self.evidence_root = Path(evidence_root)
        self.evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.calls = []

    def __call__(self, packet):
        workspace = Path(tempfile.mkdtemp(prefix="call-", dir=self.evidence_root))
        schema_path, final_path = workspace / "schema.json", workspace / "final.json"
        prompt = ("Play Shengji for the observing seat's partnership. Card codes use S/H/C/D "
                  "and ranks 2..A; BJ/LJ are jokers. Use only the provided information. "
                  "Your memory belongs to this seat, not your partner. Return cards to play "
                  "from suggested_actions, or propose another legal action. Suggestions are "
                  "a bounded public-information ballot, not exhaustive or guaranteed winning "
                  "throws. Follow suit and pair/tractor requirements; a failed throw may be "
                  "reduced by the engine. Respect rollout_calls_remaining. "
                  "and evaluations=null, OR cards=null and up to 16 {cards,continuation} "
                  "rollout requests. At most two rollout batches per decision. "
                  "Rollouts use the true world in perfect mode and shared constraint-sampled "
                  "worlds in actor-only mode; results are estimates under the named policy, "
                  "not guaranteed outcomes. Positive signed levels favor your partnership. "
                  "Keep a concise updated memory. No prose outside JSON.\n" +
                  canonical_json_bytes(packet).decode("ascii")).encode("utf-8")
        schema_path.write_bytes(canonical_json_bytes(output_schema()))
        (workspace / "prompt.txt").write_bytes(prompt)
        receipt = {"model": self.model, "effort": self.reasoning_effort,
                   "accepted": False, "runtime": self.runtime}
        try:
            timeout, deadline = self._dispatch_deadline()
            command = self._command(workspace=workspace, schema_path=schema_path,
                                    final_path=final_path)
            result = self.run_command(command, prompt, workspace, timeout)
            (workspace / "stdout.jsonl").write_bytes(result.stdout)
            (workspace / "stderr.txt").write_bytes(result.stderr)
            receipt.update(wall_ms=result.wall_ms, returncode=result.returncode)
            self._check_dispatch_deadline(deadline)
            if result.returncode or not final_path.is_file() or final_path.is_symlink():
                raise CodexTurnTransportError("benchmark provider failed or final absent")
            _, usage, message = _events_and_usage(result.stdout)
            receipt["usage"] = usage
            final = _strict_json(final_path.read_bytes(), "benchmark final")
            if final != _strict_json(message.encode(), "benchmark message"):
                raise CodexTurnTransportError("benchmark final/message mismatch")
            if (type(final) is not dict or set(final) != {"cards", "evaluations", "memory"}
                    or type(final["memory"]) is not str
                    or (final["cards"] is None) == (final["evaluations"] is None)):
                raise CodexTurnTransportError("benchmark action shape refused")
            key = "evaluations" if final["cards"] is None else "cards"
            receipt["accepted"] = True  # protocol shape only; engine validation follows
            return {key: final[key], "memory": final["memory"]}
        except BaseException as exc:
            receipt["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            (workspace / "receipt.json").write_bytes(canonical_json_bytes(receipt))
            self.calls.append(dict(receipt, evidence_path=str(workspace)))
