"""Research factories: fixed release-27 control and bury, independent play model.

This is not a production registry entry. The caller must supply a supervised
deadline and publish the complete recipe before launching gameplay.
"""
from ..ai.cwv_policy import shared_evaluator
from .cwv_bury_policy import CWVBuryBot
from .cwv_bounded_puct import CWVBoundedPuctBot, PuctConfig
from .cwv_prior_admission import CWVPriorBuryBot, CWVPriorAdmissionConfig
from .cwv_shortlist import CWVShortlistConfig
from .cwv_truncated_search import CWVPriorTruncatedSearchBot


M1_SHA = "12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f"
PRIOR_SHA = "b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c"


class PuctFixedBuryBot(CWVBuryBot, CWVBoundedPuctBot):
    """PUCT play with the unchanged hybrid-bury implementation."""


class TruncatedFixedBuryBot(CWVBuryBot, CWVPriorTruncatedSearchBot):
    """Truncated play with the unchanged hybrid-bury implementation."""


def make_release27_side(*, side, seed, baseline_checkpoint, prior_checkpoint,
                        arm_checkpoint, arm_sha256, mode, sweeps=8, depth=8,
                        continuation_tricks=1, root_warmup_top=0):
    if side not in ("arm", "baseline") or mode not in ("puct", "truncated"):
        raise ValueError("invalid release27 comparison side/mode")
    if root_warmup_top and mode != 'puct':
        raise ValueError('common-root warmup requires PUCT')
    fixed = shared_evaluator(baseline_checkpoint, threads=1, max_batch=128,
                             encoding="mlp-static")
    if fixed.checkpoint_sha256 != M1_SHA:
        raise ValueError("release27 requires the frozen M1 NumPy asset")
    prior = CWVPriorAdmissionConfig(checkpoint=str(prior_checkpoint),
                                   checkpoint_sha256=PRIOR_SHA,
                                   threshold=1000, top=256)
    kwargs = dict(seed=seed, config=CWVShortlistConfig(
        worlds=32, selection_worlds=30, alternatives=4, batch_size=128,
        uniform=False), prior=prior, arm="hybrid", serving_budget_seconds=2.0)
    if side == "baseline":
        bot = CWVPriorBuryBot(fixed, reuse_successors=True, **kwargs)
    else:
        evaluator = shared_evaluator(arm_checkpoint, threads=1, max_batch=128,
                                     encoding="mlp-static", value_head="outcome")
        if evaluator.checkpoint_sha256 != arm_sha256:
            raise ValueError("arm checkpoint changed")
        kwargs["bury_evaluator"] = fixed
        if mode == "puct":
            bot = PuctFixedBuryBot(evaluator, reuse_successors=False,
                puct_config=PuctConfig(sweeps=sweeps, depth=depth, batch_size=32),
                root_warmup_top=root_warmup_top,
                **kwargs)
        else:
            bot = TruncatedFixedBuryBot(evaluator, reuse_successors=True,
                continuation_tricks=continuation_tricks, **kwargs)
    bot.REPORT_FOLD_WORLDS = 300
    return bot
