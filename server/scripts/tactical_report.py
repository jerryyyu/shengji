"""Run the tactical regression fixtures against a bot and print a pass/fail table.

Diagnostic, not a gate (tests/tactical/README.md).  The bot is built from a
fly.toml-shaped environment exactly as the server registers it, so a screen of
an admission or tie-break change points this at its candidate and reads which
fixtures moved against the recorded production verdicts.

    # the production recipe on a local copy of the served package
    uv run python scripts/tactical_report.py \
        --ckpt /path/smv3out-491ee4bf.npz --sha256 491ee4bf...

    # any recipe: the env itself (SHENGJI_PV_* in the process environment)
    SHENGJI_PV_CKPT=... SHENGJI_PV_SHA256=... SHENGJI_PV_CANDIDATES=16 \
        uv run python scripts/tactical_report.py --from-env

    # a registry bot by name (anything make_bot accepts, e.g. smart, mc-...)
    uv run python scripts/tactical_report.py --bot smart

``--stamp`` rewrites ``current_bot`` in the fixtures file from this run (only
meaningful for the production bot; it is what the pytest xfail marks read).
``--json PATH`` writes the per-fixture results.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.eval import tactical as T  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ckpt", help="pv-search package (.npz); production knobs unless --env-override")
    src.add_argument("--from-env", action="store_true", help="read SHENGJI_PV_* from the environment")
    src.add_argument("--bot", help="a registry policy name (ai.registry.make_bot)")
    ap.add_argument("--sha256", help="full sha256 of --ckpt")
    ap.add_argument("--env-override", action="append", default=[],
                    help="KEY=VALUE applied over the production knobs (with --ckpt)")
    ap.add_argument("--fixtures", default=str(T.FIXTURES_PATH))
    ap.add_argument("--only", action="append", default=[], help="fixture id or category filter")
    ap.add_argument("--seed", type=int, default=0, help="bot seed (fresh bot per fixture)")
    ap.add_argument("--fill-seed", type=int, default=0, help="placeholder hidden-hand fill")
    ap.add_argument("--json", help="write per-fixture results here")
    ap.add_argument("--stamp", action="store_true",
                    help="rewrite current_bot in the fixtures file from this run")
    ap.add_argument("--compare-observations", action="store_true",
                    help="paired r36-SMV3 vs div+rc+tb+la observation screen")
    ap.add_argument("--compare-seeds", default="0,1,2",
                    help="comparison bot seeds (recorded in JSON; default: 0,1,2)")
    ap.add_argument("--compare-fill-seed", type=int, default=0,
                    help="comparison public hidden-fill seed (recorded in JSON)")
    args = ap.parse_args()

    fixtures = T.load_fixtures(args.fixtures)
    if args.only:
        fixtures = [fx for fx in fixtures if fx.id in args.only or fx.category in args.only]
    if not fixtures:
        raise SystemExit("no fixtures selected")

    if args.compare_observations:
        if not args.ckpt or not args.sha256:
            raise SystemExit("--compare-observations requires --ckpt and full --sha256")
        if args.sha256 != T.OBSERVATION_COMPARISON_SHA256:
            raise SystemExit("comparison requires the pinned r36 SMV3 package SHA256")
        if not args.json:
            raise SystemExit("--compare-observations requires --json for comparison metadata")
        if args.stamp or args.bot or args.from_env or args.only or args.env_override:
            raise SystemExit("comparison refuses stamp, bot, env, filters, and overrides")
        if len(fixtures) != 4 or any(fx.category != T.OBSERVATION_CATEGORY or
                                     fx.current_bot is not None for fx in fixtures):
            raise SystemExit("comparison requires exactly four unstamped observation fixtures")
        try:
            seeds = tuple(int(value) for value in args.compare_seeds.split(",") if value != "")
        except ValueError as exc:
            raise SystemExit("--compare-seeds must be comma-separated integers") from exc
        if not seeds:
            raise SystemExit("--compare-seeds must not be empty")
        if len(set(seeds)) != len(seeds):
            raise SystemExit("--compare-seeds must not contain duplicates")
        output_path = Path(args.json)
        try:
            fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            raise SystemExit(f"comparison output already exists: {args.json}")
        environs = T.observation_comparison_environs(args.ckpt, args.sha256)
        names = {}
        for label, environ in environs.items():
            names[label], _ = T.bot_from_environ(environ, seed=seeds[0])

        def factory(label):
            return lambda seed: T.bot_from_environ(environs[label], seed=seed)[1]

        paired = T.run_observation_comparison(
            factory("r36-smv3"), factory("div+rc+tb+la"), fixtures,
            seeds=seeds, fill_seed=args.compare_fill_seed)
        print(f"paired observations: {len(paired)} roots; "
              f"control={names['r36-smv3']} treatment={names['div+rc+tb+la']}")
        if args.json:
            def row(result):
                return {"status": result.status, "action": result.action,
                        "detail": result.detail, "error": result.error,
                        "observation": result.extra.get("observation"),
                        "ballot_opportunity": result.extra["ballot_opportunity"],
                        "decision": T.observation_decision_metadata(result)}
            payload = {
                "comparison": "r36-smv3-vs-div+rc+tb+la",
                "checkpoint": args.ckpt, "checkpoint_sha256": args.sha256,
                "seeds": list(seeds), "fill_seed": args.compare_fill_seed,
                "changed_flags": list(T.OBSERVATION_COMPARISON_FLAGS),
                "bots": names,
                "results": [{"id": item["fixture"], "seed": item["seed"],
                             "fill_seed": item["fill_seed"],
                             "control": row(item["control"]),
                             "treatment": row(item["treatment"])}
                            for item in paired],
            }
            output_path.write_text(json.dumps(payload, indent=1))
            print(f"wrote {args.json}", file=sys.stderr)
        return

    if args.bot:
        from shengji.ai.registry import make_bot
        name = args.bot

        def make():
            return make_bot(name, seed=args.seed)
    else:
        if args.ckpt:
            if not args.sha256 or len(args.sha256) != 64:
                raise SystemExit("--ckpt needs the package's full --sha256")
            overrides = dict(kv.split("=", 1) for kv in args.env_override)
            environ = T.production_environ(args.ckpt, args.sha256, **overrides)
        else:
            environ = dict(os.environ)
        name, _probe = T.bot_from_environ(environ, seed=args.seed)

        def make():
            return T.bot_from_environ(environ, seed=args.seed)[1]

    def progress(res):
        print(f"  {res.fixture.id:<28} {res.status:<5} {res.seconds:5.2f}s  {res.detail}",
              file=sys.stderr, flush=True)

    print(f"running {len(fixtures)} fixtures against {name}", file=sys.stderr)
    results = T.run_set(make, fixtures, fill_seed=args.fill_seed, progress=progress)
    print(T.format_table(results, name))

    if args.json:
        rows = [{"id": r.fixture.id, "category": r.fixture.category, "status": r.status,
                 "action": r.action, "detail": r.detail, "seconds": r.seconds, "error": r.error,
                 "current_bot": r.fixture.current_bot, "record": r.record, **r.extra}
                for r in results]
        Path(args.json).write_text(json.dumps({"bot": name, "seed": args.seed,
                                               "fill_seed": args.fill_seed, "results": rows},
                                              indent=1))
        print(f"wrote {args.json}", file=sys.stderr)

    if args.stamp:
        verdict = {r.fixture.id: ("pass" if r.status == "pass" else "fail")
                   for r in results if r.status in ("pass", "FAIL")}
        path = Path(args.fixtures)
        out = []
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                row = json.loads(line)
                if row["id"] in verdict:
                    row["current_bot"] = verdict[row["id"]]
                line = json.dumps(row, separators=(",", ":"))
            out.append(line)
        path.write_text("\n".join(out) + "\n")
        print(f"stamped current_bot for {len(verdict)} fixtures in {path} (bot {name})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
