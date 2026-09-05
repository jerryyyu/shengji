"""Small opened-DEV token experiment; never a collection or strength certificate.

Reuse the zero-tool provider transport and TurnDriver. Private call artifacts
are written once, before any engine action. Snapshot reruns reuse completed
calls; an unknown-cost failure stops admission rather than pretending it was
free. Full-round mode does not replay failed calls or resume partial games.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

from shengji.luna import game as engine
from shengji.luna.atomic_io import publish_exclusive_bytes
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.transport import CodexExecPlannerTransport
from shengji.luna.turn import DecisionPacket, PhaseContext, TurnDriver, Usage


ARMS = {"baseline": 1, "compact1": 1, "batch2": 2, "batch4": 4}
FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens",
          "reasoning_output_tokens", "total_tokens", "wall_ms")


def publish(path, value):
    publish_exclusive_bytes(Path(path), canonical_json_bytes(value), mode=0o600)


def load(path):
    return json.loads(Path(path).read_bytes())


def retained_packets(private_root):
    """Select four independent deals and fixed decision indices, not outcomes."""
    selected = []
    seen = set()
    folders = sorted((Path(private_root) / "attempts").iterdir(),
                     key=lambda p: hashlib.sha256(p.name.encode()).hexdigest())
    for folder in folders:
        packets = {}
        for path in sorted((folder / "journal").glob("*-response.json")):
            evidence = load(path)["response"]["provider_private_evidence"]
            prompt = base64.b64decode(evidence["prompt_base64"]).decode()
            value = json.loads(prompt.split("DECISION_PACKET_JSON\n", 1)[1])
            packet = DecisionPacket.from_mapping(value)
            if packet.decision_index in (0, 12, 24, 36):
                packets[packet.decision_index] = packet
        if not packets:
            continue
        coordinate = next(iter(packets.values())).coordinate
        if any(p.coordinate != coordinate for p in packets.values()):
            raise ValueError("retained journal mixes independent deals")
        if coordinate in seen:
            continue
        # No outcome is loaded. Require this cheap repeated-position panel.
        if set(packets) != {0, 12, 24, 36}:
            continue
        seen.add(coordinate)
        selected.append(packets)
        if len(selected) == 4:
            break
    if len(selected) != 4:
        raise ValueError("four independent retained games not available")
    # At each stage consecutive slots always come from different games.
    return [group[index] for index in (0, 12, 24, 36) for group in selected]


def summarize(rows):
    arms = {}
    for name in ARMS:
        subset = [r for r in rows if r["arm"] == name]
        totals = {key: sum((r.get("usage") or {}).get(key, 0)
                           for r in subset) for key in FIELDS}
        accepted = sum(len(r["decisions"]) for r in subset if r["accepted"])
        tokens = totals["total_tokens"]
        unknown = sum(r.get("usage") is None for r in subset)
        arms[name] = {"calls": len(subset), "accepted_decisions": accepted,
                      "failed_calls": sum(not r["accepted"] for r in subset),
                      "unknown_usage_calls": unknown, "usage": totals,
                      "accepted_decisions_per_million_reported_tokens":
                          accepted * 1e6 / tokens if tokens and not unknown else None,
                      "reported_tokens_per_accepted_decision":
                          tokens / accepted if accepted and not unknown else None,
                      "serial_decisions_per_minute":
                          accepted * 60000 / totals["wall_ms"]
                          if totals["wall_ms"] else None}
    return arms


class Pilot:
    def __init__(self, args):
        from shengji.luna.token_batch import CompactBatchTransport
        self.args = args
        self.root = args.out.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_mode & 0o077:
            raise ValueError("pilot directory must be private (mode 700)")
        self.rows = []
        self.charged = 0
        self.created = time.time()
        self.deadline_ns = time.monotonic_ns() + args.wall_seconds * 1_000_000_000
        self.base = CodexExecPlannerTransport(
            codex_binary=args.codex_binary, policy_mode="play-only",
            timeout_seconds=args.call_seconds,
            deadline_provider=lambda: self.deadline_ns)
        self.compact = CompactBatchTransport(
            codex_binary=args.codex_binary, policy_mode="play-only",
            timeout_seconds=args.call_seconds,
            deadline_provider=lambda: self.deadline_ns,
            runtime_attestor=lambda _: self.base.runtime)
        self.source = {str(p.relative_to(Path(__file__).resolve().parents[1])):
                       hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (Path(__file__).resolve(),
                                 Path(sys.modules["shengji.luna.token_batch"].__file__),
                                 Path(sys.modules["shengji.luna.transport"].__file__),
                                 Path(engine.__file__))}

    def configure(self, inputs):
        config = {"mode": self.args.mode, "arms": self.args.arms,
                  "tokens": self.args.tokens, "wall_seconds": self.args.wall_seconds,
                  "call_seconds": self.args.call_seconds, "runtime": self.base.runtime,
                  "source": self.source, "inputs": inputs,
                  "model": self.base.model, "effort": self.base.reasoning_effort,
                  "provider_concurrency": 1, "claim": "opened-DEV diagnostic",
                  "created_unix": self.created}
        path = self.root / "config.json"
        if path.exists():
            old = load(path)
            self.created = old["created_unix"]
            self.deadline_ns = time.monotonic_ns() + max(0, int(
                (self.args.wall_seconds - (time.time() - self.created)) * 1e9))
            config["created_unix"] = self.created
            if config != old:
                raise ValueError("pilot inputs or implementation changed")
        else:
            publish(path, config)

    def call(self, arm, index, packets):
        path = self.root / f"{arm}-{index:04d}.json"
        pending = self.root / "pending" / path.name
        if path.exists():
            row = load(path)
            if row["packet_hashes"] != [p.sha256 for p in packets]:
                raise ValueError("saved call inputs differ")
            self.rows.append(row)
            self.charged += row["charged_tokens"]
            return row, None
        if pending.exists():
            row = load(pending)
            if row["packet_hashes"] != [p.sha256 for p in packets]:
                raise ValueError("unsettled reservation inputs differ")
            row.update(accepted=False, decisions=[], usage=None,
                       error="unsettled provider reservation; cost unknown; no redispatch")
            self.rows.append(row)
            self.charged += row["charged_tokens"]
            return row, None
        # Admission reserve, not a promise about unreported provider billing.
        reserve = 18000 + 12000 * len(packets)
        remaining = (self.deadline_ns - time.monotonic_ns()) / 1e9
        if self.charged + reserve > self.args.tokens or remaining < self.args.call_seconds:
            raise RuntimeError("pilot admission budget exhausted; completed calls retained")
        print(json.dumps({"event": "call-start", "arm": arm, "batch": index,
                          "decisions": len(packets), "reported_or_reserved_tokens": self.charged}),
              flush=True)
        row = {"arm": arm, "index": index, "packet_hashes": [p.sha256 for p in packets],
               "packets": [p.payload() for p in packets], "accepted": False,
               "decisions": [], "usage": None, "error": None, "private_evidence": None}
        pending.parent.mkdir(mode=0o700, exist_ok=True)
        publish(pending, {**row, "charged_tokens": reserve, "started_unix": time.time()})
        started = time.monotonic()
        responses = None
        try:
            if arm == "baseline":
                responses = (self.base.call(packets[0]),)
                evidence = self.base.take_private_evidence(packets[0], responses[0])
                row["usage"] = responses[0].usage.payload()
            else:
                responses = self.compact.call_many(tuple(packets))
                evidence = self.compact.last_evidence
                # Responses explicitly allocate (not multiply) each batch's usage.
                summed = {key: sum(r.usage.payload()[key] for r in responses)
                          for key in FIELDS}
                row["usage"] = summed
            row["private_evidence"] = evidence
            row["decisions"] = [{"packet_sha256": p.sha256,
                                 "candidate_index": r.intent.candidate_index,
                                 "confidence": r.intent.confidence,
                                 "planning_note": r.intent.planning_note}
                                for p, r in zip(packets, responses, strict=True)]
            row["accepted"] = True
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            evidence = (self.base.take_private_refusal_evidence(packets[0])
                        if arm == "baseline" else self.compact.last_evidence)
            row["private_evidence"] = evidence
            if evidence and evidence.get("usage") is not None:
                usage = dict(evidence["usage"])
                usage.setdefault("total_tokens", usage["input_tokens"] + usage["output_tokens"])
                row["usage"] = usage
        row["elapsed_seconds"] = time.monotonic() - started
        row["charged_tokens"] = (row["usage"]["total_tokens"]
                                  if row["usage"] is not None else reserve)
        publish(path, row)
        self.rows.append(row)
        self.charged += row["charged_tokens"]
        print(json.dumps({"event": "call-finished", "arm": arm, "batch": index,
                          "accepted": row["accepted"], "error": row["error"],
                          "elapsed_seconds": row["elapsed_seconds"],
                          "reported_or_reserved_tokens": self.charged,
                          "summary": summarize(self.rows)[arm]}), flush=True)
        return row, responses

    def finish(self, extra):
        result = {"schema": "luna-token-pilot-v1", "source": self.source,
                  "arms": summarize(self.rows), "charged_tokens": self.charged,
                  "wall_seconds": time.time() - self.created,
                  "interpretation": "Exploratory; four independent games, not 16 independent games. "
                    "Reported raw tokens are not subscription quota or billing estimates. "
                    "The play-only collector is not the historical rollout-enabled teacher.",
                  **extra}
        path = self.root / "result.json"
        if path.exists():
            return load(path)
        publish(path, result)
        print(json.dumps(result, sort_keys=True), flush=True)
        return result


def snapshots(pilot):
    packets = retained_packets(pilot.args.private_root)
    pilot.configure([p.sha256 for p in packets])
    for stage in range(4):
        # Rotate arm order at each stage to distribute time/cache effects.
        order = pilot.args.arms[stage % len(pilot.args.arms):] + pilot.args.arms[:stage % len(pilot.args.arms)]
        for arm in order:
            size = ARMS[arm]
            for offset in range(0, 4, size):
                row, _ = pilot.call(arm, stage * 4 + offset,
                                    packets[stage * 4 + offset:stage * 4 + offset + size])
                if not row["accepted"]:
                    return pilot.finish({"status": "stopped-on-refusal", "completed_rounds": 0})
    return pilot.finish({"status": "snapshot-panel-complete", "completed_rounds": 0,
                         "snapshots": len(packets), "independent_games": 4})


class ReadyResponse:
    response = None

    def call(self, packet):
        if self.response is None or self.response.packet_sha256 != packet.sha256:
            raise ValueError("preplanned response belongs to another game/decision")
        response, self.response = self.response, None
        return response


def driver_packet(driver):
    team = driver.game.acting_team
    return DecisionPacket.from_observation(
        driver.game.session(team).observe(), coordinate=driver.game.coordinate,
        mirror=driver.game.mirror, team=team, decision_index=driver.decision_index,
        memory=driver.memories[team], phase=PhaseContext())


def rounds(pilot):
    if len(pilot.args.arms) != 1:
        raise ValueError("full-round invocation has exactly one arm")
    secret = hashlib.sha256(b"teacher-token-full-round-pilot-2026-09-05-v1").digest()
    coords = [("2", 0, 0), ("5", 1, 0), ("9", 0, 0), ("K", 1, 0)]
    games = [engine.LunaSelfPlayGame(engine.build_root(secret, c), coordinate=c,
                                    seed_secret=secret) for c in coords]
    pilot.configure([g.root_sha256 for g in games])
    if list(pilot.root.glob("*-0*.json")):
        raise ValueError("round pilot already started; retain output, do not replay calls")
    slots = [ReadyResponse() for _ in games]
    drivers = [TurnDriver(g, slots[i]) for i, g in enumerate(games)]
    completed = set()
    arm = pilot.args.arms[0]
    index = 0
    while len(completed) < len(games):
        live = [i for i, g in enumerate(games) if not g.complete]
        for start in range(0, len(live), ARMS[arm]):
            ids = live[start:start + ARMS[arm]]
            packets = [driver_packet(drivers[i]) for i in ids]
            row, responses = pilot.call(arm, index, packets)
            index += 1
            if not row["accepted"]:
                return pilot.finish({"status": "stopped-on-refusal", "completed_rounds": len(completed)})
            for i, response in zip(ids, responses, strict=True):
                slots[i].response = response
                drivers[i].step()  # Full existing validation + engine transition + team memory.
                if games[i].complete:
                    completed.add(i)
                    publish(pilot.root / f"game-{i}-terminal.json", games[i].terminal_receipt().payload())
                    publish(pilot.root / f"game-{i}-trajectory.json", games[i].sealed_trajectory().body)
            publish(pilot.root / f"state-{index:04d}.json",
                    [{"coordinate": list(g.coordinate), "state": engine._state_snapshot(g.rnd),
                      "memories": {str(t): m.payload() for t, m in d.memories.items()},
                      "decision_index": d.decision_index} for g, d in zip(games, drivers, strict=True)])
    tokens = sum((r.get("usage") or {}).get("total_tokens", 0) for r in pilot.rows)
    return pilot.finish({"status": "four-rounds-complete", "completed_rounds": 4,
                         "completed_rounds_per_million_reported_tokens": 4e6 / tokens})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshots", "rounds"))
    parser.add_argument("--private-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--tokens", type=int, default=1_000_000)
    parser.add_argument("--wall-seconds", type=int, default=1200)
    parser.add_argument("--call-seconds", type=int, default=90)
    args = parser.parse_args()
    if not 1 <= args.tokens <= 6_000_000 or not 1 <= args.wall_seconds <= 5400:
        parser.error("small pilot only: at most 6M reported/reserved tokens and 90m")
    if len(set(args.arms)) != len(args.arms):
        parser.error("duplicate arms")
    pilot = Pilot(args)
    try:
        (snapshots if args.mode == "snapshots" else rounds)(pilot)
    except Exception as exc:
        pilot.finish({"status": "stopped", "error": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
