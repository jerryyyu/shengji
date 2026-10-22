"""Build the S58 full-combo screen arms without changing serving defaults."""
from dataclasses import asdict

from shengji.train import pv_search_policy as pv

PLAY_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
S58_SHA = "424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e"
OLD_SHA = "763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343"
CONTROL_NAME = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-"
                "xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0")
FLAGS = {
    "SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD": "1",
    "SHENGJI_PV_LEAF_GREEDY_FINISH": "1",
    "SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP": "1",
}
DIFFERENCES = {
    "belief_sha256", "doomed_throw_reselect_exact_guard",
    "leaf_greedy_finish", "leaf_greedy_finish_exact_skip",
}


def arm_envs(base, play_package, old_belief, new_belief):
    """Keep release budgets and exact depth; replace only the treatment keys."""
    expected = {
        "SHENGJI_PV_SHA256": PLAY_SHA,
        "SHENGJI_PV_BELIEF_SHA256": OLD_SHA,
        "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
        "SHENGJI_PV_EXACT_DEEP_CARDS": "7",
        "SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS": "7",
    }
    if any(base.get(key) != value for key, value in expected.items()):
        raise ValueError("base is not the expected release-46 recipe")
    if any(base.get(key, "0") not in ("0", "") for key in FLAGS):
        raise ValueError("comparator already carries a treatment flag")
    comparator = {**base, "SHENGJI_PV_CKPT": str(play_package),
                  "SHENGJI_PV_BELIEF_CKPT": str(old_belief)}
    candidate = {**comparator, **FLAGS, "SHENGJI_PV_BELIEF_CKPT": str(new_belief),
                 "SHENGJI_PV_BELIEF_SHA256": S58_SHA}
    return candidate, comparator


def build_pair(envs, seed=17):
    """Construct through the actual registry and refuse unintended config drift."""
    built = []
    for env in envs:
        entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
        (name, factory), = entries.items()
        bot = factory(seed=seed)
        built.append((name, bot))
    if built[1][0] != CONTROL_NAME:
        raise ValueError("comparator is not release 46 as served")
    candidate, comparator = [asdict(bot.config) for _, bot in built]
    delta = {key for key in candidate if candidate[key] != comparator[key]}
    if delta != DIFFERENCES:
        raise ValueError(f"unexpected arm config delta: {sorted(delta)}")
    for _, bot in built:
        if (bot.worlds, bot.candidates, bot.serving_budget_seconds) != (64, 8, 3.0):
            raise ValueError("screen must retain W64/K8 and the served 3s budget")
    model = built[0][1].belief_model
    if model.package_sha256 != S58_SHA or abs(model.temperature - 1.0129481491372179) > 1e-12:
        raise ValueError("S58 package or stored temperature drift")
    return built
