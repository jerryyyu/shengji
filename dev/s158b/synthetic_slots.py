"""Synthetic seed records for Stage B reader validation."""
from shengji.engine.cards import RANKS


def clean_slot(index):
    row = dict(seat=(1 if index % 2 == 0 else 2), attacker=index % 2 == 0, admitted=[["SA"], ["SK"]], served=0, arm=1,
               full=1, full_censored=False, worlds=64, abandoned=None, stage_seconds=2.,
               completed_worlds=12, skipped_worlds=1, pi_attacker_points=([0, 5] if index % 2 == 0 else [5, 0]), play_index=0)
    return dict(schema="s158b-seed-v1", status="complete", seed=100 + index, release=55,
               arm_name="fixture", rank=RANKS[index % 12], banker=0, decisions=60, world_counts={"64": 60},
               belief_fallbacks=0, bury_fallback=None, declares=[dict(seat=1, evaluated=True,
               fallback_reason=None, arm="shared", worlds=64, completed=64)],
               attacker_points=100, kitty_bonus=0, level_change=0, winner_team=1, eligible=[row])
