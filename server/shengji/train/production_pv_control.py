"""Frozen release-29 card-play control; never resolves a mutable registry alias.

Observed from live /healthz on 2026-09-22. The research harness supplies shared
heuristic declare/bury, so this is NOT a full served-bot or Fly-latency comparison.
Keep production_play_control's historical release-28 recipe unchanged.
"""
from dataclasses import dataclass
from pathlib import Path

from .pv_search_policy import PVSearchConfig, make_pv_search_bot, pv_policy_name


SHA256 = 'ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75'
PLAY_NAME = 'pv-search-ccade130-w64-k8-r8bc573be'
SERVED_NAME = PLAY_NAME + '-bury-hybrid-4f003f41e23e'


def recipe():
    return dict(worlds=64, candidates=8, cap=4000, batch_size=128,
                serving_budget_seconds=3.0)


@dataclass(frozen=True)
class ProductionPVControl:
    checkpoint: str

    def identity(self):
        return dict(schema='release29-production-play-control-v1',
                    observed_utc_date='2026-09-22',
                    checkpoint=str(Path(self.checkpoint).resolve()),
                    checkpoint_sha256=SHA256, play_policy=PLAY_NAME,
                    served_package_reference=SERVED_NAME, recipe=recipe(),
                    value_head='outcome', threads=1,
                    declare_bury='shared HeuristicBot supplied by harness',
                    scope='card play only; not full served package or Fly latency',
                    fallback='heuristic-anchor-on-error-or-3s-budget')

    def make(self, seed):
        config = PVSearchConfig(checkpoint_sha256=SHA256, **recipe())
        if pv_policy_name(SHA256[:8], config) != PLAY_NAME:
            raise RuntimeError('release29 play recipe identity drift')
        # The factory validates the complete artifact digest and NumPy heads.
        # Pass every effective play knob; neither env nor registry is consulted.
        return make_pv_search_bot(self.checkpoint, sha256=SHA256, seed=seed,
                                  threads=1, name=PLAY_NAME, **recipe())
