"""Per-release model manifests: which package each served decision stage consults.

A manifest (``server/releases/r<N>.json``, schema `SCHEMA`) states, for one release:

* ``release`` (int) and ``bot_name``, the full served ``SHENGJI_BOT`` name;
* ``env``: the exact environment lines the server builds the bot from (``fly.toml``'s
  ``[env]`` without `NON_BOT_KEYS`), volume paths included;
* ``packages``: name -> ``sha256``, ``basename`` (of the volume path), ``env_path`` (the env
  keys naming that path) and ``env_sha256`` (the env keys pinning that hash); a package no
  stage consults carries a ``why``;
* ``stages``: for each of `STAGES`, ``value`` and ``prior`` (a package name or null) and
  ``worlds`` (`SAMPLERS`, or ``belief:<package>``), with a ``why`` whenever ``value`` or
  ``prior`` is null or the worlds are not a belief package's.

The manifest documents what the code does; it configures nothing.  `wiring` is the check
that it is true: it builds the served bot from the manifest's env as the server builds it,
takes a few seeded decisions of every stage, and reports which value and prior packages
each stage's forwards actually ran on and which world sampler each stage drew from.
`wiring_mismatches` compares that report with the manifest's stage table.

    python -m shengji.releases check server/releases/r49.json
        # schema validation only (no package needed)
    python -m shengji.releases wiring server/releases/r49.json --package-dir DIR
        # the wiring witness; DIR holds the packages by basename
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "shengji-release-manifest-v1"
RELEASES_DIR = Path(__file__).resolve().parents[1] / "releases"
STAGES = ("declare", "bury", "lead", "follow", "endgame")
#: the world samplers a stage can draw from, besides ``belief:<package>``
SAMPLERS = {
    # `value_declare.sample_declare_world`: a uniform deal given the seat's hand and the
    # current declaration
    "uniform-declare": "value_declare.sample_declare_world",
    # `MCBot._sample_hands`, the split sampler (directly, or as the history-legal draw's fill)
    "mcbot-split": "ai.mcbot.MCBot._sample_hands",
}
BELIEF_PREFIX = "belief:"
#: ``fly.toml`` ``[env]`` keys that enter no bot: credentials, where the server writes, and
#: the test-room switch
NON_BOT_KEYS = ("GOOGLE_CLIENT_ID", "SHENGJI_LOG_DIR", "SHENGJI_DATA_DIR",
                "SHENGJI_W32_TEST_ROOMS")
#: env keys the wiring build leaves to the process: the engine is chosen at import
PROCESS_KEYS = ("SHENGJI_FAST",)
VOLUME_PREFIX = "/data/models/"
#: the seeded round the witness plays (its declare chances, bury, first lead and follow
#: and an endgame lead and follow)
WIRING_SEED = 49
#: an endgame decision: the actor holds at most this many cards
ENDGAME_CARDS = 7
#: the play and bury budgets of a witnessed decision (`_lift_budgets`)
WITNESS_BUDGET_SECONDS = 12.0
#: decision records that say the stage degraded: no wiring evidence
FALLBACK_SCHEMAS = ("pv-search-fallback-v1", "cwv-bury-fallback-v1")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TOP_KEYS = {"schema", "release", "bot_name", "env", "packages", "stages"}
_PACKAGE_KEYS = {"sha256", "basename", "env_path", "env_sha256", "why"}
_STAGE_KEYS = {"value", "prior", "worlds", "why"}


class ManifestError(ValueError):
    pass


def manifest_path(release: int) -> Path:
    return RELEASES_DIR / f"r{int(release)}.json"


def load(path_or_release) -> dict:
    """The validated manifest at a path, or of a release number."""
    path = manifest_path(path_or_release) if isinstance(path_or_release, int) else Path(path_or_release)
    manifest = json.loads(Path(path).read_text())
    validate(manifest)
    return manifest


def _require(condition, message):
    if not condition:
        raise ManifestError(message)


def validate(manifest: Mapping[str, Any]) -> None:
    """Refuses a manifest that breaks the schema (module docstring)."""
    _require(isinstance(manifest, Mapping), "a manifest is a JSON object")
    _require(set(manifest) == _TOP_KEYS,
             f"manifest keys must be {sorted(_TOP_KEYS)}, not {sorted(manifest)}")
    _require(manifest["schema"] == SCHEMA, f"schema must be {SCHEMA!r}")
    _require(type(manifest["release"]) is int and manifest["release"] > 0,
             "release must be a positive int")
    env = manifest["env"]
    _require(isinstance(env, Mapping) and env, "env must be a non-empty object")
    for key, value in env.items():
        _require(isinstance(key, str) and isinstance(value, str),
                 f"env {key!r}: every key and value is a string")
        _require(key not in NON_BOT_KEYS, f"env {key!r} enters no bot; leave it out")
    _require(manifest["bot_name"] == env.get("SHENGJI_BOT"),
             "bot_name must equal env SHENGJI_BOT")
    packages = manifest["packages"]
    _require(isinstance(packages, Mapping) and packages, "packages must be a non-empty object")
    claimed_paths, claimed_shas = {}, {}
    for name, package in packages.items():
        _require(isinstance(package, Mapping), f"package {name!r} must be an object")
        _require(set(package) - {"why"} == _PACKAGE_KEYS - {"why"} and set(package) <= _PACKAGE_KEYS,
                 f"package {name!r} keys must be {sorted(_PACKAGE_KEYS - {'why'})} (+ why)")
        _require(isinstance(package["sha256"], str) and _HEX64.fullmatch(package["sha256"]),
                 f"package {name!r}: sha256 must be 64 lowercase hex")
        _require(isinstance(package["basename"], str) and package["basename"].endswith(".npz")
                 and "/" not in package["basename"], f"package {name!r}: basename must be a .npz file name")
        _require(isinstance(package["env_path"], list) and package["env_path"],
                 f"package {name!r}: env_path must name at least one env key")
        _require(isinstance(package["env_sha256"], list),
                 f"package {name!r}: env_sha256 must be a list of env keys")
        for key in package["env_path"]:
            _require(key in env, f"package {name!r}: env_path key {key!r} is not in env")
            _require(env[key] == VOLUME_PREFIX + package["basename"],
                     f"package {name!r}: env {key} is {env[key]!r}, not "
                     f"{VOLUME_PREFIX + package['basename']!r}")
            _require(key not in claimed_paths, f"env {key} is claimed by two packages")
            claimed_paths[key] = name
        for key in package["env_sha256"]:
            _require(key in env, f"package {name!r}: env_sha256 key {key!r} is not in env")
            _require(env[key] == package["sha256"],
                     f"package {name!r}: env {key} pins {env[key][:12]}, not the manifest's "
                     f"{package['sha256'][:12]} (sha mismatch)")
            _require(key not in claimed_shas, f"env {key} is claimed by two packages")
            claimed_shas[key] = name
    for key, value in env.items():
        if value.startswith(VOLUME_PREFIX):
            _require(key in claimed_paths, f"env {key} names a package no manifest entry lists "
                     f"({value}): unknown package")
        if key.endswith("_SHA256"):
            _require(key in claimed_shas, f"env {key} pins a hash no manifest entry lists: "
                     "unknown package")
    stages = manifest["stages"]
    _require(isinstance(stages, Mapping) and tuple(stages) == STAGES,
             f"stages must be exactly {list(STAGES)}, in that order")
    used = set()
    for stage, row in stages.items():
        _require(isinstance(row, Mapping) and {"value", "prior", "worlds"} <= set(row) <= _STAGE_KEYS,
                 f"stage {stage!r} keys must be value, prior, worlds (+ why)")
        for role in ("value", "prior"):
            ref = row[role]
            _require(ref is None or ref in packages,
                     f"stage {stage!r} {role} names unknown package {ref!r}")
            used.add(ref)
        worlds = row["worlds"]
        _require(isinstance(worlds, str), f"stage {stage!r}: worlds must be a string")
        belief = worlds.startswith(BELIEF_PREFIX)
        if belief:
            ref = worlds[len(BELIEF_PREFIX):]
            _require(ref in packages, f"stage {stage!r} worlds names unknown package {ref!r}")
            used.add(ref)
        else:
            _require(worlds in SAMPLERS, f"stage {stage!r} worlds {worlds!r} is not "
                     f"{BELIEF_PREFIX}<package> or one of {sorted(SAMPLERS)}")
        if row["value"] is None or row["prior"] is None or not belief:
            why = row.get("why")
            _require(isinstance(why, str) and why.strip(),
                     f"stage {stage!r} needs a why: its value or prior is null or its worlds "
                     "are not a belief package's")
    for name, package in packages.items():
        if name not in used:
            why = package.get("why")
            _require(isinstance(why, str) and why.strip(),
                     f"package {name!r} reaches no stage and needs a why")


def fly_env(fly_toml=None) -> dict[str, str]:
    """``fly.toml``'s ``[env]`` without `NON_BOT_KEYS`: what a manifest's ``env`` must equal."""
    from .eval.served_config import fly_env as served_fly_env
    return {k: v for k, v in served_fly_env(fly_toml).items() if k not in NON_BOT_KEYS}


def local_env(manifest: Mapping[str, Any], paths: Mapping[str, str | os.PathLike]) -> dict[str, str]:
    """The manifest's env with each package's volume path replaced by its local copy in
    ``paths`` (package name -> file).  A package absent from ``paths`` keeps its volume
    path; a present one must hash to the manifest's sha256."""
    from .ai.cwv_policy import file_sha256
    env = dict(manifest["env"])
    for name, path in paths.items():
        package = manifest["packages"].get(name)
        if package is None:
            raise ManifestError(f"no package {name!r} in release {manifest['release']}")
        actual = file_sha256(str(path))
        if actual != package["sha256"]:
            raise ManifestError(f"local {name} is {actual[:12]}, not the manifest's "
                                f"{package['sha256'][:12]} (sha mismatch)")
        for key in package["env_path"]:
            env[key] = str(path)
    return env


def package_paths(manifest: Mapping[str, Any], directory: str | os.PathLike) -> dict[str, str]:
    """name -> file for every manifest package present in ``directory`` by basename."""
    out = {}
    for name, package in manifest["packages"].items():
        path = Path(directory) / package["basename"]
        if path.is_file():
            out[name] = str(path)
    return out


def expected_wiring(manifest: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    """The manifest's stage table in `wiring`'s report shape."""
    out = {}
    for stage, row in manifest["stages"].items():
        out[stage] = {"value": [] if row["value"] is None else [row["value"]],
                      "prior": [] if row["prior"] is None else [row["prior"]],
                      "worlds": [row["worlds"]]}
    return out


def expected_model_ids(manifest: Mapping[str, Any], chars: int = 8) -> dict[str, dict]:
    """The decision records' ``model_ids`` (`PVSearchBot.model_ids`) each stage should carry."""
    def short(name):
        return None if name is None else manifest["packages"][name]["sha256"][:chars]
    out = {}
    for stage, row in manifest["stages"].items():
        worlds = row["worlds"]
        belief = worlds[len(BELIEF_PREFIX):] if worlds.startswith(BELIEF_PREFIX) else None
        out[stage] = {"value": short(row["value"]), "prior": short(row["prior"]),
                      "belief": short(belief)}
    return out


def wiring_mismatches(manifest: Mapping[str, Any], report: Mapping[str, Any]) -> list[str]:
    """Every way the witnessed ``report`` differs from the manifest's stage table: a package
    or sampler a stage used that the manifest does not list, or one it lists that the stage
    never used; a witnessed decision without a stamped ``model_ids`` record; and a decision
    record whose ``model_ids`` differ from the table's."""
    problems = []
    want = expected_wiring(manifest)
    ids = expected_model_ids(manifest)
    for stage in STAGES:
        seen = report["stages"].get(stage)
        if not seen or not seen["decisions"]:
            problems.append(f"{stage}: no decision witnessed")
            continue
        for role in ("value", "prior", "worlds"):
            if seen[role] != want[stage][role]:
                problems.append(f"{stage} {role}: witnessed {seen[role]}, manifest {want[stage][role]}")
        for schema in seen.get("schemas", ()):
            if schema in FALLBACK_SCHEMAS:
                problems.append(f"{stage}: a witnessed decision fell back ({schema})")
        for reason in seen.get("fallback_reasons", ()):
            problems.append(f"{stage}: a witnessed decision fell back ({reason})")
        stamped = seen["model_ids"]
        if len(stamped) != seen["decisions"]:
            problems.append(f"{stage}: {seen['decisions']} decisions witnessed, "
                            f"{len(stamped)} model_ids stamps")
        for got in stamped:
            if not isinstance(got, dict):
                problems.append(f"{stage}: a witnessed decision carries no model_ids stamp "
                                f"(record absent, not a dict, or without model_ids)")
            elif got != ids[stage]:
                problems.append(f"{stage} record model_ids {got}, manifest {ids[stage]}")
    return problems


class _Witness:
    """Counts, per decision stage, the rows each value and prior package forwards and the
    draws of each world sampler, by patching the forward and sampler entry points for
    the duration.  Counting only: every patched call returns what the original returns."""

    def __init__(self, names_by_sha: Mapping[str, str]):
        self.names_by_sha = dict(names_by_sha)
        self.stage = None
        self.counts = defaultdict(Counter)

    def _name(self, sha):
        return self.names_by_sha.get(sha, f"unlisted:{str(sha)[:12]}")

    def _tag(self, role, sha, n=1):
        if self.stage is not None:
            self.counts[self.stage][(role, self._name(sha) if role != "worlds" else sha)] += n

    @contextlib.contextmanager
    def active(self):
        from .ai import belief_numpy, cwv_numpy, cwv_prior_numpy, mcbot
        from .train import value_declare
        witness = self
        saved = []

        def patch(owner, attr, make):
            original = getattr(owner, attr)
            saved.append((owner, attr, original))
            setattr(owner, attr, make(original))

        def value_forward(original):
            def probabilities(self, public, *args, **kwargs):
                witness._tag("value", getattr(self, "package_sha256", None), len(public))
                return original(self, public, *args, **kwargs)
            return probabilities

        def prior_forward(original):
            def forward(self, X, *args, **kwargs):
                witness._tag("prior", getattr(self, "package_sha256", None), len(X))
                return original(self, X, *args, **kwargs)
            return forward

        def belief_proposal(original):
            def __init__(self, model, *args, **kwargs):
                sha = getattr(model, "package_sha256", None)
                witness._tag("worlds", BELIEF_PREFIX + witness._name(sha))
                return original(self, model, *args, **kwargs)
            return __init__

        def sampler(name):
            def make(original):
                def sample(*args, **kwargs):
                    witness._tag("worlds", name)
                    return original(*args, **kwargs)
                return sample
            return make

        patch(cwv_numpy.CWVNumpyMLP, "probabilities", value_forward)
        patch(cwv_numpy.CWVNumpyMLP, "policy_log_odds", prior_forward)
        patch(cwv_prior_numpy.CWVNumpyPrior, "log_odds", prior_forward)
        patch(belief_numpy.BeliefProposal, "__init__", belief_proposal)
        patch(mcbot.MCBot, "_sample_hands", sampler("mcbot-split"))
        patch(value_declare, "sample_declare_world", sampler("uniform-declare"))
        try:
            yield self
        finally:
            for owner, attr, original in reversed(saved):
                setattr(owner, attr, original)

    def stage_report(self, stage):
        rows = self.counts.get(stage, Counter())
        out = {role: sorted({key for r, key in rows if r == role})
               for role in ("value", "prior", "worlds")}
        # value and prior: rows forwarded; worlds: sampler calls
        out["counts"] = {f"{role} {key}": n for (role, key), n in sorted(rows.items())}
        return out


def _build(env: Mapping[str, str], full: bool, seed: int):
    """``(registration, bot)``: the served bot built from ``env`` as the server builds it.
    ``full``: every registration the server makes at boot (`served_config.build_served_bot`,
    which needs every package of the env locally); else only the pv-search registration
    (`registry._register_pv_search_from_env`, the only one that builds this bot), on a
    scratch copy of the registry."""
    from .ai import registry
    from .eval import served_config
    if full:
        saved = dict(registry.REGISTRY)
        try:
            name, bot = served_config.build_served_bot(env, seed=seed,
                                                       expected_name=env["SHENGJI_BOT"])
        finally:
            registry.REGISTRY.clear()
            registry.REGISTRY.update(saved)
        return "server", bot
    saved = registry.REGISTRY
    registry.REGISTRY = {k: v for k, v in saved.items() if not k.startswith("pv-search-")}
    try:
        registry._register_pv_search_from_env()
        bot = registry.make_bot(env["SHENGJI_BOT"], seed=seed)
    finally:
        registry.REGISTRY = saved
    return "pv-search", bot


def _lift_budgets(bot):
    """A slow host does not turn the witness into a fallback test (an expiry is its own,
    separately tested path): `WITNESS_BUDGET_SECONDS` for the play and bury budgets, no
    greedy-finish deadline.  The play budget stays finite because the exact endgame
    stages' soft stops are fractions of it."""
    bot.serving_budget_seconds = WITNESS_BUDGET_SECONDS
    bot.leaf_greedy_deadline_ms = 0
    if hasattr(bot, "bury_serving_budget_seconds"):
        bot.bury_serving_budget_seconds = WITNESS_BUDGET_SECONDS


def _play_round(bot, witness, seed):
    """The seeded round: the bot makes every declare decision, the bury and the first lead
    and follow; the heuristic plays on until the actor holds `ENDGAME_CARDS` or fewer,
    where the bot makes one lead and one follow.  The bot observes every play, as a
    room's bot does.  Returns stage -> the decisions' records."""
    from .ai.heuristic import HeuristicBot
    from .engine.game import Game

    records = defaultdict(list)
    rnd = Game(random.Random(seed)).start_round()
    witness.stage = "declare"

    def declare(seat, final):
        cards = bot.decide_declare(copy.deepcopy(rnd), seat, final=final)
        record = getattr(bot, "last_declare_record", None)
        if record is not None:
            records["declare"].append(copy.deepcopy(record))
        if cards:
            rnd.declare(seat, cards)

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        declare(seat, False)
    for seat in range(4):
        declare(seat, True)
    rnd.finalize_declare()
    witness.stage = "bury"
    banker = rnd.banker
    cards = bot.decide_bury(copy.deepcopy(rnd), banker)
    records["bury"].append(copy.deepcopy(bot.last_bury_record))
    rnd.bury(banker, cards)
    heuristic = HeuristicBot()
    wanted = {("lead", True), ("follow", False), ("endgame", True), ("endgame", False)}
    observe = getattr(bot, "observe_public", None)
    while rnd.phase == "play" and wanted:
        seat = rnd.turn
        lead = rnd.trick is None or not rnd.trick.plays
        stage = ("endgame" if len(rnd.hands[seat]) <= ENDGAME_CARDS
                 else "lead" if lead else "follow")
        if (stage, lead) in wanted:
            wanted.discard((stage, lead))
            witness.stage = stage
            cards = bot.decide_play(copy.deepcopy(rnd), seat)
            records[stage].append(copy.deepcopy(bot.last_decision_record))
            witness.stage = None
        else:
            cards = heuristic.decide_play(rnd, seat)
        rnd.play(seat, cards)
        if observe is not None:
            observe(rnd)
    if wanted:
        raise ManifestError(f"the seeded round ended before the witness saw {sorted(wanted)}")
    return records


def wiring(manifest: Mapping[str, Any], paths: Mapping[str, str | os.PathLike], *,
           seed: int = WIRING_SEED, lift_budgets: bool = True) -> dict:
    """Builds the served bot from the manifest's env (volume paths mapped to ``paths``,
    package name -> local file) as the server builds it, plays the seeded round
    (`_play_round`) and reports per stage which value and prior packages ran forwards,
    which world samplers drew, and the decision records' ``model_ids``.

    Every package a stage names must be in ``paths``; with every package present the build
    makes all the server's boot registrations, else only the pv-search one (``registration``
    in the report says which).  ``lift_budgets`` (default) removes the wall clocks
    (`_lift_budgets`) so a slow host cannot turn the witness into a fallback test; a
    decision that fell back anyway is reported (`wiring_mismatches`), never counted as
    wiring."""
    validate(manifest)
    referenced = {ref for row in manifest["stages"].values()
                  for ref in (row["value"], row["prior"],
                              row["worlds"][len(BELIEF_PREFIX):] if row["worlds"].startswith(BELIEF_PREFIX)
                              else None) if ref is not None}
    missing = sorted(referenced - set(paths))
    if missing:
        raise ManifestError(f"the wiring needs the packages its stages name; missing {missing}")
    env = local_env(manifest, paths)
    full = set(paths) == set(manifest["packages"])
    process = {k: v for k, v in env.items() if k not in PROCESS_KEYS}
    from .ai import belief_numpy
    from .eval import served_config
    names_by_sha = {p["sha256"]: name for name, p in manifest["packages"].items()}
    witness = _Witness(names_by_sha)
    prep = belief_numpy.PREP_SECONDS
    with served_config.process_env(process):
        registration, bot = _build(process, full, seed)
        if lift_budgets:
            _lift_budgets(bot)
            belief_numpy.PREP_SECONDS = 60.0
        try:
            with witness.active():
                records = _play_round(bot, witness, seed)
        finally:
            belief_numpy.PREP_SECONDS = prep
    stages = {}
    for stage in STAGES:
        row = witness.stage_report(stage)
        row["decisions"] = len(records.get(stage, ()))
        # one entry per decision: None where the record is absent or carries no model_ids
        row["model_ids"] = [r.get("model_ids") if isinstance(r, dict) else None
                            for r in records.get(stage, ())]
        row["schemas"] = sorted({str(r.get("schema")) for r in records.get(stage, ())
                                 if isinstance(r, dict)})
        row["fallback_reasons"] = sorted({str(r["fallback_reason"]) for r in records.get(stage, ())
                                          if isinstance(r, dict) and r.get("fallback_reason")})
        if stage == "endgame":
            row["exact"] = [{k: r.get(k) for k in ("exact_lead_status", "exact_follow_attempted",
                                                   "exact_follow_applied")}
                            for r in records.get(stage, ()) if isinstance(r, dict)]
        stages[stage] = row
    return {"release": manifest["release"], "bot_name": bot.policy_name,
            "registration": registration, "stages": stages}


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "wiring"))
    parser.add_argument("manifest")
    parser.add_argument("--package-dir")
    parser.add_argument("--seed", type=int, default=WIRING_SEED)
    args = parser.parse_args(argv)
    try:
        manifest = load(args.manifest)
        if args.command == "check":
            print(f"OK release {manifest['release']} {manifest['bot_name']}")
            return 0
        if not args.package_dir:
            raise ManifestError("wiring needs --package-dir")
        report = wiring(manifest, package_paths(manifest, args.package_dir), seed=args.seed)
    except (ManifestError, OSError, ValueError) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(report, indent=1, sort_keys=True))
    problems = wiring_mismatches(manifest, report)
    for problem in problems:
        print(f"MISMATCH {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
