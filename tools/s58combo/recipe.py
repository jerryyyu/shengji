"""Build the S58 full-combo screen arms without changing serving defaults."""
from dataclasses import asdict
import os
from unittest.mock import patch

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
    # A screen registers only its explicit PV arm; serving-only registrations
    # may reference other packages that are not part of this screen's inputs.
    pv_base = {key: value for key, value in base.items() if key.startswith('SHENGJI_PV_')}
    comparator = {**pv_base, "SHENGJI_REQUIRE_VOIDS": "1", "SHENGJI_PV_CKPT": str(play_package),
                  "SHENGJI_PV_BELIEF_CKPT": str(old_belief)}
    candidate = {**comparator, **FLAGS, "SHENGJI_PV_BELIEF_CKPT": str(new_belief),
                 "SHENGJI_PV_BELIEF_SHA256": S58_SHA}
    return candidate, comparator


def half_budget_envs(envs):
    """Proposed perf profile; outer budgets halve, inner exact caps stay fixed."""
    out = []
    for env in envs:
        if (env.get('SHENGJI_PV_SERVING_BUDGET_SECONDS') != '3'
                or env.get('SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS') != '2'
                or env.get('SHENGJI_PV_LEAF_GREEDY_DEADLINE', '0') != '0'):
            raise ValueError('half-budget profile requires the unmodified served budgets')
        out.append({**env, 'SHENGJI_PV_SERVING_BUDGET_SECONDS': '1.5',
                    'SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS': '1'})
    if len(out) != 2:
        raise ValueError('exactly two arms required')
    out[0].update(SHENGJI_PV_LEAF_GREEDY_DEADLINE='1',
                  SHENGJI_PV_ENCODE_PREFIX_CACHE='1', SHENGJI_PV_LEAF_GREEDY_STREAM='1')
    return tuple(out)


def build_pair(envs, seed=17, *, profile='served'):
    """Single-threaded admission: bind factory-only flags separately for each arm."""
    if profile not in ('served', 'half-budget-lgfd1000'):
        raise ValueError('unknown screen profile')
    half = profile == 'half-budget-lgfd1000'
    if len(envs) != 2:
        raise ValueError('exactly two arms required')
    built = []
    for env in envs:
        entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
        (name, factory), = entries.items()
        # These switches are read by the factory, not captured in its recipe.
        switches = pv.latency_switches(env)
        factory_env = {key: "1" if switches[attr] else "0"
                       for attr, key in pv.LATENCY_SWITCH_ENV.items()}
        factory_env["SHENGJI_PV_BELIEF_LOG"] = env.get("SHENGJI_PV_BELIEF_LOG", "1")
        with patch.dict(os.environ, factory_env):
            bot = factory(seed=seed)
        if any(getattr(bot, attr) != on for attr, on in switches.items()):
            raise ValueError("factory did not bind the arm-local cost switches")
        built.append((name, bot))
    control_env = dict(envs[1])
    if half:
        control_env.update(SHENGJI_PV_SERVING_BUDGET_SECONDS='3',
                           SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS='2')
    control_name, = pv.pv_registry_entries(**pv.pv_env_recipe(control_env))
    if control_name != CONTROL_NAME:
        raise ValueError("comparator is not release 46 as served")
    candidate, comparator = [asdict(bot.config) for _, bot in built]
    delta = {key for key in candidate if candidate[key] != comparator[key]}
    if delta != DIFFERENCES | ({'leaf_greedy_deadline_ms'} if half else set()):
        raise ValueError(f"unexpected arm config delta: {sorted(delta)}")
    for _, bot in built:
        if (bot.worlds, bot.candidates, bot.serving_budget_seconds,
                bot.bury_serving_budget_seconds) != (64, 8, 1.5 if half else 3.0, 1.0 if half else 2.0):
            raise ValueError('screen budget/profile drift')
    expected_switches = {'encode_prefix_cache', 'leaf_greedy_stream'}
    for index, (_, bot) in enumerate(built):
        actual = {attr for attr in pv.LATENCY_SWITCH_ENV if getattr(bot, attr)}
        allowed = [set(), expected_switches] if index == 0 and not half else [
            expected_switches if index == 0 else set()]
        if actual not in allowed:
            raise ValueError('screen runtime switches drift')
    if half:
        if (candidate['leaf_greedy_deadline_ms'], comparator['leaf_greedy_deadline_ms']) != (1000, 0):
            raise ValueError('half-budget finish deadline drift')
    model = built[0][1].belief_model
    if model.package_sha256 != S58_SHA or abs(model.temperature - 1.0129481491372179) > 1e-12:
        raise ValueError("S58 package or stored temperature drift")
    return built
