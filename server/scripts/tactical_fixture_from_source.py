"""Build one tactical fixture (tests/tactical/fixtures.jsonl line) from a source.

The source carries the full deal; the fixture keeps only what the acting seat
could see (eval.tactical.public_fixture strips the rest and proves the public
view rebuilds the same trick state).

    # a room log play event (logs/<ROOM>.jsonl, 1-based line of the play event)
    uv run python scripts/tactical_fixture_from_source.py room-log \
        --log ../logs/CDCE.jsonl --line 33 --id cdce-r1-s1-t1-throw \
        --category doomed-throw --predicate not_a_doomed_throw --why "..."

    # a self-play decision record (shard .jsonl + the source_ref suffix
    # ":<shard>:<round>:<seat>:<ply>")
    uv run python scripts/tactical_fixture_from_source.py shard \
        --shard /path/cluster-000212.jsonl --key :212:0:0:19 --id ... \
        --category point-donation --predicate no_point_donation_when_zero_point_alternative_exists

Prints the fixture as one JSON line on stdout.  Nothing is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.engine.round import actual_play_after  # noqa: E402
from shengji.eval.tactical import public_fixture, refusal_args  # noqa: E402
from shengji.harvest.rebuild import state_for_record  # noqa: E402
from shengji.rl.replay_log import rebuild_round  # noqa: E402


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--predicate", required=True)
    parser.add_argument("--args", default="{}", help="predicate kwargs as JSON")
    parser.add_argument("--why", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--current-bot", default=None, choices=[None, "pass", "fail"])


def _replay_play(rnd, play, where):
    seat, committed = play["seat"], play["cards"]
    previous = rnd.last_trick
    rnd.play(seat, play.get("attempted", committed))
    if sorted(actual_play_after(rnd, seat, previous)) != sorted(committed):
        raise SystemExit(f"{where}: replay does not match the committed cards")


def _round_key(record):
    source, ref = record["source"], record["source_ref"]
    if source == "human":
        _, sep, ref = ref.rpartition(" -> ")
        if not sep:
            raise SystemExit("human source_ref lacks a room-log pointer")
        source = "room-log"
    if source == "room-log":
        prefix, sep, _ = ref.rpartition(":event-")
        if not sep:
            raise SystemExit("room-log source_ref lacks an event index")
        return source, prefix
    if source in ("luna-rpc", "luna-quality"):
        prefix, sep, _ = ref.rpartition("#event-")
        if not sep:
            raise SystemExit("Luna source_ref lacks an event index")
        return source, prefix
    if source == "trajectory":
        return source, ref.rsplit(":", 2)[0]
    # Other sources contain individual positions, without sibling refusals.
    return source, ref


def from_room_log(args: argparse.Namespace) -> dict:
    lines = Path(args.log).read_text().splitlines()
    target = json.loads(lines[args.line - 1])
    if target.get("e") != "play":
        raise SystemExit(f"line {args.line} is a {target.get('e')!r} event, not a play")
    round_no = target["round"]
    events = [json.loads(l) for l in lines[:args.line - 1]]
    events = [e for e in events if e.get("round") == round_no]
    rnd = rebuild_round(events + [target])
    if rnd is None:
        raise SystemExit("round lacks round_start/trump/bury")
    declarations = [{"seat": e["seat"], "cards": list(e["cards"])}
                    for e in events if e.get("e") == "declare"]
    plays = []
    for event_index, e in enumerate(events):
        if e.get("e") != "play":
            continue
        play = {"seat": int(e["seat"]), "cards": list(e["cards"])}
        if e.get("attempted_cards"):
            play["attempted"] = list(e["attempted_cards"])
        plays.append(play)
        _replay_play(rnd, play, f"round {round_no} event {event_index}")
    seat = int(target["seat"])
    decision = target.get("decision") or {}
    attempted = target.get("attempted_cards")
    if attempted:
        _replay_play(deepcopy(rnd), {"seat": seat, "cards": target["cards"],
                                    "attempted": attempted}, f"line {args.line}")
    observed = {
        "action": list(attempted or target["cards"]),
        "engine_play": list(target["cards"]) if attempted else None,
        "admitted": decision.get("admitted"),
        "value_means": decision.get("value_means"),
        "selected_index": decision.get("selected_index"),
        "policy": decision.get("policy"),
    }
    if "admitted_indices" in decision:
        observed["admitted_indices"] = decision["admitted_indices"]
    source = {"kind": "room-log", "path": str(Path(args.log).name), "line": args.line,
              "round": round_no}
    return build(rnd, seat, plays, declarations, source, observed, args)


def from_shard(args: argparse.Namespace) -> dict:
    records = [json.loads(l) for l in Path(args.shard).read_text().splitlines() if l.strip()]
    hits = [r for r in records if r.get("source_ref", "").endswith(args.key)]
    if len(hits) != 1:
        raise SystemExit(f"{len(hits)} records match {args.key!r}")
    rec = hits[0]
    if rec["decision_kind"] != "play":
        raise SystemExit("only play records become fixtures")
    rnd = state_for_record({**rec, "plays_prefix": []})
    seat = int(rec["seat"])
    round_key = _round_key(rec)
    forced = {}
    for row in records:
        if row.get("decision_kind") != "play" or not row.get("engine_play"):
            continue
        ply = int(row["ply"])
        if ply >= len(rec["plays_prefix"]) or _round_key(row) != round_key:
            continue
        evidence = int(row["seat"]), list(row["action"]), sorted(row["engine_play"])
        if ply in forced and forced[ply] != evidence:
            raise SystemExit(f"conflicting refused throws at ply {ply}")
        forced[ply] = evidence
    plays = []
    for ply, prefix_play in enumerate(rec["plays_prefix"]):
        play = {"seat": int(prefix_play["seat"]), "cards": list(prefix_play["cards"])}
        if ply in forced:
            actor, attempted, committed = forced[ply]
            if actor != play["seat"] or committed != sorted(play["cards"]):
                raise SystemExit(f"plays_prefix[{ply}] is not the engine play of the refused throw")
            play["attempted"] = attempted
        _replay_play(rnd, play, f"plays_prefix[{ply}]")
        plays.append(play)
    if rec.get("engine_play"):
        _replay_play(deepcopy(rnd), {"seat": seat, "cards": rec["engine_play"],
                                    "attempted": rec["action"]}, rec["source_ref"])
    setup = rec["setup"]
    declarations = [{"seat": int(d["seat"]), "cards": list(d["cards"])}
                    for d in setup.get("declarations") or []]
    av = rec.get("action_values") or {}
    observed = {
        "action": list(rec["action"]),
        "engine_play": list(rec["engine_play"]) if rec.get("engine_play") else None,
        "admitted": rec.get("production_ballot") or rec.get("ballot"),
        "ballot": rec.get("ballot"),
        "value_means": av.get("means"),
        "exploration": rec.get("exploration"),
        "policy": rec.get("policy"),
    }
    allocation = rec.get("allocation") or {}
    for key in ("admitted_indices", "selected_index"):
        if key in allocation:
            observed[key] = allocation[key]
    source = {"kind": "shard", "path": str(Path(args.shard)), "source_ref": rec["source_ref"],
              "run": Path(args.shard).resolve().parents[1].name}
    return build(rnd, seat, plays, declarations, source, observed, args)


def build(rnd, seat, plays, declarations, source, observed, args) -> dict:
    kwargs = json.loads(args.args)
    if args.predicate == "not_a_throw_refuted_by_public_refusal" and not kwargs:
        kwargs = refusal_args(plays, seat, rnd.ordering)     # derived from the public history
    fx = public_fixture(rnd, seat, plays, declarations, id=args.id, category=args.category,
                        source=source, observed=observed, predicate=args.predicate,
                        args=kwargs, why=args.why, notes=args.notes)
    fx.current_bot = args.current_bot
    return fx.to_json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="kind", required=True)
    p = sub.add_parser("room-log")
    p.add_argument("--log", required=True)
    p.add_argument("--line", type=int, required=True)
    _common(p)
    p = sub.add_parser("shard")
    p.add_argument("--shard", required=True)
    p.add_argument("--key", required=True)
    _common(p)
    args = parser.parse_args()
    row = from_room_log(args) if args.kind == "room-log" else from_shard(args)
    print(json.dumps(row, separators=(",", ":")))


if __name__ == "__main__":
    main()
