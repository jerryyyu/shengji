"""Train a TINY complete-world value checkpoint for development only.

The real checkpoint is produced by the training build (claude/cwv-train) and
loads through the same #214 API.  Until it exists, this script fits a small
``ValueNetwork`` on a handful of reduced-work self-play rounds so the
evaluator, the one-ply bot, the calibration and the duel driver can be
exercised end to end.  Its metadata carries everything the play-time side
binds to: the afterstate encoder identity, ``sees_hidden_hands`` and the
train-only stratified prior the no-learning control reads.

    python scripts/cwv_dev_checkpoint.py --out /tmp/cwv-dev.pt --rounds 6

Nothing here is a strength claim; the checkpoint is not for a duel result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEV_SCHEMA = "shengji-cwv-dev-checkpoint-v1"


def dev_examples(seed0: int, rounds: int, *, select_worlds: int = 2,
                 report_worlds: int = 30):
    """Value examples from ``rounds`` reduced-work trajectory rounds."""
    from shengji.harvest import trajectory
    from shengji.rl.value_afterstate import example_from_trajectory_record

    config = trajectory.build_config(
        seed0=seed0, explore_rate=0.0, explore_k=0,
        select_worlds=select_worlds, report_worlds=report_worlds)
    examples = []
    for cluster in range(rounds):
        rows, _stats = trajectory.play_trajectory_round(
            config, cluster, seed0 + cluster, 0)
        examples.extend(example_from_trajectory_record(row) for row in rows)
    return examples


def build_dev_checkpoint(out: str, *, seed0: int = 4_200_000, rounds: int = 6,
                         architecture: str = "gru", width: int = 16,
                         max_epochs: int = 12, patience: int = 4,
                         seed: int = 0, examples=None, quiet: bool = False) -> dict:
    """Fit, save through ``value_checkpoint`` and return a small receipt."""
    import torch

    from shengji.ai.cwv_policy import afterstate_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_metrics import fit_stratified_prior
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    from shengji.rl.value_training import fit

    started = time.perf_counter()
    if examples is None:
        examples = dev_examples(seed0, rounds)
    deals = sorted({row.deal_key for row in examples})
    if len(deals) < 2:
        raise SystemExit("need at least two deals for a train/validation split")
    holdout = set(deals[-max(1, len(deals) // 4):])
    train = [row for row in examples if row.deal_key not in holdout]
    validation = [row for row in examples if row.deal_key in holdout]
    torch.manual_seed(seed)
    config = ValueModelConfig(
        architecture=architecture, width=width, history_layers=1,
        attention_heads=2, feedforward_width=2 * width, max_history=100)
    model = ValueNetwork(config)
    receipt = fit(model, train, validation, max_epochs=max_epochs,
                  patience=patience, batch_size=32, learning_rate=3e-3,
                  weight_decay=1e-4, seed=seed)
    prior = fit_stratified_prior(train)
    metadata = {
        "schema": DEV_SCHEMA,
        "arch": architecture,
        "encoder": afterstate_encoder_identity(),
        "sees_hidden_hands": True,
        "purpose": "development only; not a strength artifact",
        "train_rows": len(train),
        "validation_rows": len(validation),
        "deals": len(deals),
        "best_epoch": receipt.best_epoch,
        "epochs": [{"epoch": row.epoch, "train_loss": row.train_loss,
                    "validation_loss": row.validation_loss}
                   for row in receipt.epochs],
        "stratified_prior": {
            "global_probability": list(prior.global_probability),
            "strata_probability": [[key, list(probability)]
                                   for key, probability in prior.strata_probability],
            "training_examples": prior.training_examples,
        },
    }
    sha = save_checkpoint(out, model, metadata=metadata)
    summary = {"checkpoint": os.path.abspath(out), "sha256": sha,
               "ckpt8": sha[:8], "train_rows": len(train),
               "validation_rows": len(validation), "deals": len(deals),
               "best_epoch": receipt.best_epoch,
               "best_validation_loss": min(
                   row.validation_loss for row in receipt.epochs),
               "wall_secs": round(time.perf_counter() - started, 1)}
    if not quiet:
        print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--seed0", type=int, default=4_200_000)
    ap.add_argument("--arch", default="gru", choices=("gru", "transformer"))
    ap.add_argument("--width", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    build_dev_checkpoint(args.out, seed0=args.seed0, rounds=args.rounds,
                         architecture=args.arch, width=args.width,
                         max_epochs=args.epochs, seed=args.seed)


if __name__ == "__main__":
    main()
