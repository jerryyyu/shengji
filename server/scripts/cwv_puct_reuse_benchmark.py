#!/usr/bin/env python3
"""Local fixed-state ABBA diagnostic for opt-in root enumeration reuse.

Not a gameplay screen. Supply the same saved snapshot fixture as the boundary
runner; run in an isolated window. Each search retains world-specific priors
and transitions. Prints one JSON receipt per pass and refuses any result drift.
"""
import argparse
import json

from cwv_puct_boundary import _outcome_evaluator, _world_digest
from shengji.ai.cwv_policy import file_sha256, sample_worlds
from shengji.luna.game import _round_from_snapshot
from shengji.train.cwv_bounded_puct import (
    CWVBoundedPuctBot, PuctConfig, root_clone, search_worlds,
)
from shengji.train.cwv_prior_admission import CWVPriorAdmissionConfig
from shengji.train.cwv_shortlist import CWVShortlistConfig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--states', required=True)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--prior-checkpoint', required=True)
    p.add_argument('--state', type=int, default=0)
    p.add_argument('--seed', type=int, default=616092026)
    p.add_argument('--worlds', type=int, default=32)
    p.add_argument('--sweeps', type=int, default=8)
    p.add_argument('--depth', type=int, default=8)
    a = p.parse_args()
    evaluator = _outcome_evaluator(a.checkpoint)
    prior_sha = file_sha256(a.prior_checkpoint)
    checkpoint_sha = file_sha256(a.checkpoint)
    bot = CWVBoundedPuctBot(evaluator, seed=a.seed,
        config=CWVShortlistConfig(worlds=a.worlds),
        prior=CWVPriorAdmissionConfig(a.prior_checkpoint, prior_sha))
    with open(a.states) as stream:
        rnd = _round_from_snapshot(json.load(stream)[a.state])
    worlds, _ = sample_worlds(bot, rnd, rnd.turn, a.worlds)
    if len(worlds) != a.worlds:
        raise RuntimeError('sample pool underfilled')
    roots = [root_clone(rnd, hands, buried) for hands, buried in worlds]
    reference = None
    for reuse in (False, True, True, False):
        result = search_worlds(roots, rnd.turn, prior_logits=bot._tree_prior,
            evaluator=evaluator, config=PuctConfig(sweeps=a.sweeps, depth=a.depth),
            profile=True, reuse_root_actions=reuse)
        timing = result.pop('timings')
        cache = result.pop('root_enumeration_reuse', None)
        if reference is None:
            reference = result
        if result != reference:
            raise AssertionError('root enumeration reuse changed the search result')
        print(json.dumps(dict(reuse=reuse, exact_equal=True, timings=timing,
            cache=cache, world_sha256=_world_digest(worlds),
            checkpoint_sha256=checkpoint_sha, prior_sha256=prior_sha,
            root_actions=result['diagnostics']['root_legal_counts'][0])), flush=True)


if __name__ == '__main__':
    main()
