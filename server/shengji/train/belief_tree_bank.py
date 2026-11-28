"""Score one reserved deck and publish its complete four-turn result."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from ..ai.registry import make_bot
from .belief_labels import SPLIT_SALT
from .belief_tree_bank_analysis import checked_deck
from .belief_tree_bank_settings import pilot_settings
from .belief_tree_bank_score import score_bank_root
from .belief_tree_replay import RootTarget, replay_tranche_roots


def _offline_bot(policy, seed):
    bot = make_bot(policy, seed=seed)
    bot.serving_budget_seconds = None
    bot.leaf_greedy_deadline_ms = 0
    return bot


def score_reserved_deck(bank, *, bank_sha256, store, round_seed, settings, bot_factory=_offline_bot):
    raw = Path(bank).read_bytes()
    if hashlib.sha256(raw).hexdigest() != bank_sha256:
        raise ValueError("reserved bank digest mismatch")
    manifest = json.loads(raw)
    source = manifest["source"]
    split = manifest["split"]
    if split["salt"] != SPLIT_SALT:
        raise ValueError("bank and replay split salts differ")
    matches = [item for item in manifest["deals"] if item["seed"] == round_seed]
    if len(matches) != 1:
        raise ValueError("expected exactly one reserved entry for the seed")
    entry, = matches
    cluster = round_seed - source["seed0"]
    shard = f"shards/cluster-{cluster:06d}.jsonl"
    if cluster < 0 or entry["shard"] != shard:
        raise ValueError("reserved shard disagrees with the cluster seed")
    if sum(item["key"] == entry["key"] for item in manifest["deals"]) != 1:
        raise ValueError("duplicate reserved deck")
    targets = []
    for row in entry["targets"]:
        if type(row["completed_tricks"]) is not int or row["completed_tricks"] * 4 != row["ply"]:
            raise ValueError("reserved trick count disagrees with the lead")
        targets.append(RootTarget(row["decision_index"], row["mirror"], row["ply"], row["seat"]))
    if sorted(t.mirror for t in targets) != [0, 0, 1, 1]:
        raise ValueError("expected two reserved turns per mirror")
    roots = replay_tranche_roots(Path(store) / shard, shard_sha256=entry["sha256"],
                                 run_id=source["run_id"], cluster=cluster, round_seed=round_seed,
                                 policy=source["policy"], expected_deal_key=entry["key"],
                                 calib=split["calib"], test=split["test"], min_tricks=5, targets=targets)
    policy = source["policy"]
    def make_seeded_bot(seed):
        return bot_factory(policy, seed)

    rows = []
    for root in roots:
        try:
            row = score_bank_root(root, make_bot=make_seeded_bot, policy=policy, **settings)
        except ValueError as exc:
            exc.add_note(f"Reserved deck {round_seed}, mirror {root.target.mirror}, ply {root.target.ply}")
            raise
        rows.append(row)
    deck = {"schema": "belief-tree-paired-deck-v2", "bank_sha256": bank_sha256,
            "shard_sha256": entry["sha256"], "run_id": source["run_id"], "policy": policy,
            "round_seed": round_seed, "deal_key": entry["key"], "settings": dict(settings), "rows": rows}
    checked_deck(deck, entry, source=source, bank_sha256=bank_sha256, settings=settings)
    return deck


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("bank", "bank-sha256", "store", "output"):
        p.add_argument("--" + flag, required=True)
    p.add_argument("--round-seed", type=int, required=True)
    p.add_argument("--pilot-settings", action="store_true")
    for flag in ("seed", "depth-worlds", "reply-cap", "batch-size"):
        p.add_argument("--" + flag, type=int)
    p.add_argument("--reply-value-weight", type=float)
    p.add_argument("--cover-winning-follow", action="store_true")
    p.add_argument("--complete-small-multicard-follows", action="store_true",
                   help="score every multi-card follow from a hand of five or fewer cards")
    args = p.parse_args(argv)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    settings = {key: getattr(args, key) for key in pilot_settings() if getattr(args, key) is not None}
    overrides = {key: True for key in ("cover_winning_follow", "complete_small_multicard_follows")
                 if getattr(args, key)}
    if args.pilot_settings:
        if settings or overrides:
            p.error("--pilot-settings cannot be combined with explicit search settings")
        settings = pilot_settings()
    elif settings.keys() != pilot_settings().keys():
        p.error("supply --pilot-settings or all five search settings")
    settings.update(overrides)
    result = score_reserved_deck(args.bank, bank_sha256=args.bank_sha256, store=args.store,
                                 round_seed=args.round_seed, settings=settings)
    # A consumer sees either all four completed turns or no result at this path.
    with NamedTemporaryFile(dir=output.parent, mode="w") as tmp:
        json.dump(result, tmp, sort_keys=True, allow_nan=False)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        os.link(tmp.name, output)


if __name__ == "__main__":
    main()
