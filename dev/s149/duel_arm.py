"""Construct the RT3-FT control or the epoch-three whole-action challenger for a duel worker."""

from shengji.eval.served_config import process_env, served_env
from shengji.train.pv_search_policy import pv_env_recipe
from shengji.train.unified_reply_action import install_reply_action, load_reply_action
from shengji.train.unified_serving import unified_registry_entries


UNIFIED = "0ab200ee2cec39d401967110a53e034f7a2d83c408c7d6945507cab86b939c27"
BELIEF = "af11dea78a9dcdacdfce51c274c8a98d02b10156830a05340ba9e86c77439215"
ACTION = "33821ab7fae93709734ca06071c5300e46c396635f84cebd8ea2e86ee95e5186"
CONTROL = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-"
           "la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r58c2aaeb-"
           "bury-hybrid-bwv-bbw-dcaaa606cc2d-sc8-ushare0ab200ee-uvalue0ab200ee-ureply0ab200ee-ufast")


def arm_factory(*, mappings, unified_path, belief_path, action_path=None):
    """Build once per worker. Only the challenger receives an action package."""
    env = served_env(mappings=mappings)
    env.update(SHENGJI_PV_UNIFIED_CKPT=str(unified_path), SHENGJI_PV_UNIFIED_SHA256=UNIFIED,
               SHENGJI_PV_BELIEF_CKPT=str(belief_path), SHENGJI_PV_BELIEF_SHA256=BELIEF,
               SHENGJI_BOT=CONTROL)
    with process_env(env):
        entries = unified_registry_entries(environ=env, **pv_env_recipe(env))
    factory = entries[CONTROL]
    scorer = load_reply_action(action_path, sha256=ACTION) if action_path is not None else None
    name = CONTROL if scorer is None else f"{CONTROL}-uaction{ACTION[:8]}"

    def make(seed):
        with process_env(env):
            bot = factory(seed=seed)
        if (bot.policy_name != CONTROL or bot.unified_sha256 != UNIFIED or not bot.unified_fast
                or (bot.serving_budget_seconds, bot.bury_serving_budget_seconds) != (3.0, 3.0)):
            raise ValueError("constructed bot differs from the RT3-FT duel control")
        return bot if scorer is None else install_reply_action(bot, scorer)

    return name, make
