"""Frozen Fly card-play reference, observed 2026-09-20 via fly config show.

NOT the full served package: the duel supplies shared heuristic declare/bury.
The export, prior, doses and ranking settings match production card play; engine
and hardware must be reported by the caller, never implied to be Fly latency.
No environment configuration or live production alias is read by this module.
"""
from dataclasses import dataclass
from pathlib import Path

from .cwv_shortlist import make_shortlist_bot


SHA256 = '0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747'
PLAY_NAME = 'mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03'
SERVED_NAME = PLAY_NAME + '-bury-hybrid-003c2abe49ff'


def recipe():
    # Specify every factory argument affecting the play recipe; do not inherit
    # mutable defaults or override the generated name to disguise recipe drift.
    return dict(worlds=32, alternatives=4, selection_worlds=30,
                report_worlds=300, batch_size=128, encoding='mlp-static',
                reuse_successors=True, threads=1, prior_sha256=SHA256,
                prior_threshold=1000, prior_top=256)


@dataclass(frozen=True)
class ProductionPlayControl:
    checkpoint: str

    def identity(self):
        return {'schema': 'fly-production-play-control-v1',
                'observed_utc_date': '2026-09-20',
                'checkpoint': str(Path(self.checkpoint).resolve()),
                'checkpoint_sha256': SHA256, 'prior_sha256': SHA256,
                'play_policy': PLAY_NAME, 'served_package_reference': SERVED_NAME,
                'declare_bury': 'shared HeuristicBot supplied by duel',
                'scope': 'card play only; not full production package or Fly latency',
                'recipe': recipe()}

    def make(self, seed):
        # The prior path is exactly the value path. The existing checked loader
        # verifies its FULL hash before loading, and validates prior support.
        bot = make_shortlist_bot(self.checkpoint, seed=seed,
                                 prior_checkpoint=self.checkpoint, **recipe())
        if (bot.cwv_checkpoint_sha256 != SHA256
                or bot.cwv_prior_sha256 != SHA256
                or bot.policy_name != PLAY_NAME):
            raise RuntimeError('production card-play identity drift')
        return bot
