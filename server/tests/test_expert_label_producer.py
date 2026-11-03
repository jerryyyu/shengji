"""The expert-label producer (``scripts/expert_labels``) on both served bases: release 48 and release 49 "Y".

``served_base`` holds the derivation the producer and its duel harness share: the served-name grammar
(``<play>-bury-<arm>-<digest>`` plus at most one registered wrapper token, anything else refused), the
base check (a ``SHENGJI_BOT`` its own environment does not register is refused), the variant registration
(a variant keeps the singleton-challenger wrapper exactly when its own environment turns it on) and the
expert's overrides (``EXPERT_ENV`` plus the explicit removal of the base's lead confirmation and singleton
challenger), so on either base the expert is the M28 expert under the M28 name.

The end-to-end tests run the producer as a subprocess at small widths on a scratch repo whose ``fly.toml``
is production's (Y) or its documented release-48 rollback, then replay every capsule through a fresh served
bot: on Y the served arm is Y's class with both lead rules in force (its confirmation draws are the shared
draw's next worlds and travel in the capsule); on release 48 the served arm is the plain search and no
release-49 field appears.  The package tests fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1``.
"""
import gzip
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA  # noqa: F401
from test_release46_fly_config import RELEASE49_ADDED_KEYS, fly_env
from test_release48_fly_config import (BELIEF_VOLUME_PATH, RELEASE48, local_env, release48_env,
                                       pinned_release48_belief_package)  # noqa: F401
from test_release49_fly_config import RELEASE49

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
PRODUCER_DIR = SERVER / "scripts" / "expert_labels"
sys.path.insert(0, str(PRODUCER_DIR))
import served_base  # noqa: E402

#: the expert the M28 labels were produced with (on release 48), and the name a release-49 base must derive
M28_EXPERT = ("pv-search-491ee4bf-w256-k32-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-ed8-els9000-edn200000000-"
              "xf8-xfcompactlevel-rf46b9754-bury-hybrid-bwv-63b7cb149669")
#: the M28 producer's expert overrides on release 48, as its shard bindings record them
M28_EXPERT_ENV = (("SHENGJI_PV_CANDIDATES", "32"), ("SHENGJI_PV_EXACT_DEEP_CARDS", "8"),
                  ("SHENGJI_PV_EXACT_DEEP_MAX_NODES", "200000000"), ("SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS", "8"),
                  ("SHENGJI_PV_EXACT_FOLLOW_MAX_NODES", "200000000"), ("SHENGJI_PV_EXACT_LEAD_MAX_SECONDS", "9.0"),
                  ("SHENGJI_PV_LEAF_GREEDY_DEADLINE", ""), ("SHENGJI_PV_WORLDS", "256"))
BURY = ("hybrid", "bwv")
SMALL_SERVED = (("SHENGJI_PV_CANDIDATES", "4"), ("SHENGJI_PV_WORLDS", "8"))


def y_env():
    return fly_env()


def r48_env():
    return release48_env(fly_env())


def test_served_name_grammar():
    assert served_base.parse_served_name(RELEASE49) == (BURY, "d12d7acfc860", "sc8")
    assert served_base.parse_served_name(RELEASE48) == (BURY, "cd6dd3d2b02a", None)
    assert served_base.parse_served_name(M28_EXPERT) == (BURY, "63b7cb149669", None)
    for bad in (RELEASE49[:-len("-sc8")] + "-sc9",        # an unregistered wrapper
                RELEASE49 + "-sc8",                       # two wrappers
                RELEASE48 + "-extra",                     # a token after the digest
                RELEASE48[:-len("-cd6dd3d2b02a")],        # no digest
                RELEASE48.replace("-bury-hybrid-bwv-", "-bury-hybrid-bwv-cd6dd3d2b02a-"),   # two digests
                RELEASE48.split("-bury-")[0],             # no bury arm
                "-bury-hybrid-bwv-cd6dd3d2b02a"):         # no play part
        with pytest.raises(served_base.ServedNameError):
            served_base.parse_served_name(bad)


def test_match_variant_takes_the_base_arm_with_the_variants_own_wrapper():
    plain = "pv-search-x-w8-k4-r0-bury-hybrid-bwv-0123456789ab"
    other = "pv-search-x-w8-k4-r0-bury-hybrid-0123456789ab"
    entries = {plain: None, other: None, plain + "-sc8": None, "pv-search-x-w8-k4-r0": None}
    on, off = {"SHENGJI_PV_SINGLETON_CHALLENGER": "1"}, {}
    assert served_base.match_variant(RELEASE49, off, entries) == plain
    assert served_base.match_variant(RELEASE49, on, entries) == plain + "-sc8"
    assert served_base.match_variant(RELEASE48, off, entries) == plain
    with pytest.raises(served_base.ServedNameError):     # nothing with the base's bury arm
        served_base.match_variant(RELEASE48, off, {other: None})
    with pytest.raises(served_base.ServedNameError):     # the wrapper the variant's env registers is absent
        served_base.match_variant(RELEASE48, on, {plain: None})
    with pytest.raises(served_base.ServedNameError):
        served_base.match_variant(RELEASE48, {"SHENGJI_PV_SINGLETON_CHALLENGER": "2"}, entries)


def test_expert_env_removes_the_y_rules_explicitly():
    assert served_base.EXPERT_ENV == M28_EXPERT_ENV
    assert served_base.expert_env(r48_env()) == M28_EXPERT_ENV      # the M28 binding, unchanged
    y = served_base.expert_env(y_env())
    assert set(RELEASE49_ADDED_KEYS) == set(served_base.EXPERT_DROPS)
    assert y == tuple(sorted(M28_EXPERT_ENV + tuple((k, "") for k in served_base.EXPERT_DROPS)))
    assert served_base.expert_env({**r48_env(), "SHENGJI_PV_LEAD_CONFIRM": "0"}) == M28_EXPERT_ENV


@pytest.fixture(scope="module")
def envs(pinned_production_package, pinned_release48_belief_package):
    def local(env):
        return {k: str(v) for k, v in local_env(pinned_production_package, pinned_release48_belief_package, env).items()}
    return {"y": (RELEASE49, local(y_env())), "r48": (RELEASE48, local(r48_env()))}


@pytest.mark.parametrize("base", ["y", "r48"])
def test_the_expert_is_m28s_on_both_bases(envs, base):
    name, env = envs[base]
    expert, factory = served_base.derive_variant(name, env, served_base.expert_env(env))
    assert expert == M28_EXPERT
    assert served_base.served_class(expert).__name__ == "PVSearchBuryBot"


def test_y_without_the_drops_is_refused(envs):
    from shengji.train.pv_search_policy import PVSearchPolicyError
    name, env = envs["y"]
    with pytest.raises(PVSearchPolicyError, match="lead_confirm must exceed candidates"):
        served_base.derive_variant(name, env, M28_EXPERT_ENV)


def test_a_base_its_environment_does_not_build_is_refused(envs):
    (y, yenv), (r48, renv) = envs["y"], envs["r48"]
    served_base.check_base(y, yenv)
    served_base.check_base(r48, renv)
    for name, env in ((y, renv), (r48, yenv),
                      (y[:-len("-sc8")], yenv),                                   # Y's search without its wrapper
                      (re.sub(r"d12d7acfc860", "d12d7acfc861", y), yenv),          # another bury digest
                      (y.replace("-w64-", "-w32-"), yenv)):                        # another play recipe
        with pytest.raises(served_base.ServedNameError):
            served_base.check_base(name, env)
        with pytest.raises(served_base.ServedNameError):
            served_base.derive_variant(name, env, SMALL_SERVED)


@pytest.mark.parametrize("base", ["y", "r48"])
def test_a_served_variant_keeps_the_bases_wrapper(envs, base):
    name, env = envs[base]
    variant, factory = served_base.derive_variant(name, env, SMALL_SERVED)
    assert served_base.parse_served_name(variant)[::2] == served_base.parse_served_name(name)[::2]
    bot = factory(seed=0)
    assert type(bot) is served_base.served_class(variant) is served_base.served_class(name)
    assert (bot.worlds, bot.candidates) == (8, 4)
    assert bool(bot.lead_confirm) == (base == "y")


def scratch_repo(tmp_path, base):
    """A repo whose ``fly.toml`` is production's (Y) or its release-48 rollback, around this tree's server/."""
    text = (REPO / "fly.toml").read_text()
    if base == "r48":
        text = "".join(line for line in text.splitlines(keepends=True)
                       if not any(line.startswith(f"  {k} = ") for k in RELEASE49_ADDED_KEYS))
        text, n = re.subn(r"(?m)^  SHENGJI_BOT = '[^']*'$", f"  SHENGJI_BOT = '{RELEASE48}'", text)
        assert n == 1
    repo = tmp_path / f"repo-{base}"
    repo.mkdir()
    (repo / "fly.toml").write_text(text)
    (repo / "server").symlink_to(SERVER)
    env = tomllib.loads(text)["env"]
    assert env == (y_env() if base == "y" else r48_env())
    return repo


REPLAY = r"""
import gzip, json, sys
sys.path.insert(0, sys.argv[2])
import expert_label_probe as p
out = sys.argv[1]
hdr = json.loads(open(out + "/shard-00/probe.jsonl").readline())
name, make = p.duel.variant_factory(tuple(tuple(x) for x in hdr["served_env"]))
cls = type(make(0))
fixed = p.fixed_worlds_class(cls)
caps = [json.loads(l) for l in gzip.open(out + "/shard-00/capsule.jsonl.gz")]
results = [p.replay_capsule(c, make) for c in caps]
print(json.dumps(dict(
    name=name, cls=cls.__name__, fixed=fixed.__name__,
    fixed_is_plain=fixed is p.FixedWorldsBot, admit=fixed._admit.__qualname__, worlds=fixed._worlds.__qualname__,
    confirm_draw=fixed._lead_confirm_draw.__qualname__,
    n=len(caps), ok=sum(r["ok"] for r in results), confirm=sorted({len(c.get("confirm_worlds", [])) for c in caps}),
    torch="torch" in sys.modules)))
"""


def run_producer(tmp_path, base, package, belief):
    repo = scratch_repo(tmp_path, base)
    out = tmp_path / f"out-{base}"
    env = {**os.environ, "FIND_GAPS_SERVER": str(repo / "server"), "FIND_GAPS_PKG": str(package),
           "FIND_GAPS_PATH_MAP": f"{BELIEF_VOLUME_PATH}={belief}", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    env.pop("SHENGJI_BOT", None)
    for k in list(env):
        if k.startswith("SHENGJI_PV_"):
            env.pop(k)
    small = [a for k, v in SMALL_SERVED for a in ("--served-env", f"{k}={v}")]
    cmd = [sys.executable, "-B", str(PRODUCER_DIR / "expert_label_probe.py"), "--out", str(out), "--seed0", "311039600",
           "--deals", "2", "--record-capsule", *small,
           "--expert-env", "SHENGJI_PV_WORLDS=32", "--expert-env", "SHENGJI_PV_CANDIDATES=8"]
    done = subprocess.run(cmd, cwd=SERVER, env=env, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-4000:]
    assert done.stdout.startswith("DONE deals 2 "), done.stdout
    rows = [json.loads(line) for line in open(out / "shard-00" / "probe.jsonl")]
    replay = subprocess.run([sys.executable, "-B", "-c", REPLAY, str(out), str(PRODUCER_DIR)], cwd=SERVER, env=env,
                            capture_output=True, text=True, timeout=900)
    assert replay.returncode == 0, replay.stderr[-4000:]
    caps = [json.loads(line) for line in gzip.open(out / "shard-00" / "capsule.jsonl.gz")]
    return rows, json.loads(replay.stdout.strip().splitlines()[-1]), caps


@pytest.fixture(scope="module")
def produced(pinned_production_package, pinned_release48_belief_package, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("expert-labels")
    return {base: run_producer(tmp, base, pinned_production_package, pinned_release48_belief_package)
            for base in ("y", "r48")}


def test_the_producer_on_y_keeps_ys_served_rules(produced):
    rows, replay, caps = produced["y"]
    header = rows[0]
    assert header["served_name"].endswith("-sc8") and "-lcc32-" in header["served_name"]
    assert dict(map(tuple, header["expert_env"])) == {**dict(M28_EXPERT_ENV), "SHENGJI_PV_LEAD_CONFIRM": "",
                                                      "SHENGJI_PV_SINGLETON_CHALLENGER": "",
                                                      "SHENGJI_PV_WORLDS": "32", "SHENGJI_PV_CANDIDATES": "8"}
    assert replay["cls"] == "SingletonChallengerBuryBot" and replay["fixed"] == "FixedWorldsSingletonChallengerBuryBot"
    assert replay["admit"] == "_SingletonChallenger._admit"
    assert replay["worlds"] == "FixedWorldsBot._worlds"
    assert replay["confirm_draw"] == "FixedWorldsBot._lead_confirm_draw"
    assert replay["n"] > 0 and replay["ok"] == replay["n"]
    assert replay["confirm"] == [2 * 8]
    decisions = [r for r in rows if r["row"] == "decision"]
    served = [r["served"] for r in decisions]
    assert all("singleton_challenger_applied" in s for s in served)
    leads = [s for r, s in zip(decisions, served) if r["lead"]]
    assert leads and all("lead_confirm_status" in s for s in leads)
    # the rules ran in the served arm: a confirmation got past its gates on some lead
    assert any(s["lead_confirm_status"] in ("applied", "rejected", "no_challenger") for s in leads)
    assert any(s.get("lead_confirm_worlds") == 2 * 8 for s in leads)
    assert all("lead_confirm_status" not in r["expert"] and "singleton_challenger_applied" not in r["expert"]
               for r in decisions)
    for r in decisions:   # the served arm priced the shared draw's first worlds
        assert r["worlds_digest"]["served"] == r["worlds_digest"]["expert_prefix"]
    assert len(caps) == replay["n"] and all(len(c["confirm_worlds"]) == 16 for c in caps)
    assert replay["torch"] is False


def test_the_producer_on_r48_is_the_plain_search(produced):
    rows, replay, caps = produced["r48"]
    header = rows[0]
    assert served_base.parse_served_name(header["served_name"])[2] is None and "-lcc" not in header["served_name"]
    assert replay["cls"] == "PVSearchBuryBot" and replay["fixed_is_plain"] and replay["fixed"] == "FixedWorldsBot"
    assert replay["n"] > 0 and replay["ok"] == replay["n"]
    assert replay["confirm"] == [0] and all("confirm_worlds" not in c for c in caps)
    decisions = [r for r in rows if r["row"] == "decision"]
    for r in decisions:
        for arm in ("served", "expert", "live"):
            assert not any(k.startswith(("lead_confirm", "singleton")) for k in r[arm]), (arm, sorted(r[arm]))


def test_the_expert_is_the_same_bot_on_both_bases(produced):
    (y, _, _), (r48, _, _) = produced["y"], produced["r48"]
    assert y[0]["expert_name"] == r48[0]["expert_name"]
    assert served_base.parse_served_name(y[0]["expert_name"])[2] is None
