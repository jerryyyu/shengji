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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    for e in events:
        if e.get("e") != "play":
            continue
        play = {"seat": int(e["seat"]), "cards": list(e["cards"])}
        if e.get("attempted_cards"):
            play["attempted"] = list(e["attempted_cards"])
        plays.append(play)
        rnd.play(play["seat"], play["cards"])     # the full deal: engine-validated replay
    seat = int(target["seat"])
    decision = target.get("decision") or {}
    attempted = target.get("attempted_cards")
    observed = {
        "action": list(attempted or target["cards"]),
        "engine_play": list(target["cards"]) if attempted else None,
        "admitted": decision.get("admitted"),
        "value_means": decision.get("value_means"),
        "selected_index": decision.get("selected_index"),
        "policy": decision.get("policy"),
    }
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
    rnd = state_for_record(rec)
    seat = int(rec["seat"])
    round_prefix = rec["source_ref"].rsplit(":", 2)[0]
    # refused throws in the prefix: the round's own records carry engine_play
    forced = {}
    for r in records:
        if r.get("decision_kind") == "play" and r["source_ref"].rsplit(":", 2)[0] == round_prefix \
                and r.get("engine_play"):
            forced[int(r["ply"])] = (list(r["action"]), list(r["engine_play"]))
    plays = []
    for ply, p in enumerate(rec["plays_prefix"]):
        play = {"seat": int(p["seat"]), "cards": list(p["cards"])}
        if ply in forced:
            attempted, engine = forced[ply]
            if sorted(engine) != sorted(play["cards"]):
                raise SystemExit(f"plays_prefix[{ply}] is not the engine play of the refused throw")
            play["attempted"] = attempted
        plays.append(play)
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
