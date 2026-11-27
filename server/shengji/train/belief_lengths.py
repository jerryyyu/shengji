"""Offline autoregressive suit lengths over the actor's unknown copies.

Copies with the same effective suit and receiver mask are interchangeable for
length prediction. Allocate their counts before the belief proposal chooses
individual card identities. Both training and generation use the same order
and support, including public voids and the residual capacity of the kitty.
"""
from typing import NamedTuple

import numpy as np

from .belief_seq import FEATURE_DIM, _SUB_OF, _SUBSETS


_RECEIVER_BITS = 1 << np.arange(4)
_UPPER_SUBSETS = tuple(
    tuple(np.flatnonzero(includes & ~_SUB_OF[:, remaining]) for remaining in range(16))
    for includes in _SUBSETS.T
)
_LOWER_SUBSETS = tuple(
    tuple(np.flatnonzero(~includes & _SUB_OF[:, remaining]) for remaining in range(16))
    for includes in _SUBSETS.T
)


class _Allocation(NamedTuple):
    suit: int
    mask_type: int
    receiver: int
    lengths: np.ndarray
    capacity: np.ndarray
    left: int
    choices: np.ndarray
    cards: np.ndarray


def _allocation_steps(card_feat, mask, copies, sizes):
    """Yield a length decision; receive the chosen count and update the prefix."""
    suit = card_feat[:, 1:6].argmax(1)
    types = np.asarray(mask, bool) @ _RECEIVER_BITS
    classes = suit * 16 + types
    counts = np.zeros((5, 16), dtype=np.int64)
    np.add.at(counts.ravel(), classes, copies)
    cap = np.asarray(sizes, dtype=np.int64).copy()
    future = counts.sum(0)
    if (cap < 0).any() or cap.sum() != future.sum() or future[0]:
        raise ValueError("infeasible residual copies or receiver sizes")
    # Hall's condition holds for every prefix of supported choices.
    slack = _SUBSETS @ cap - _SUB_OF @ future
    if (slack < 0).any():
        raise ValueError("no feasible suit length")
    lengths = np.zeros((5, 4), dtype=np.int64)
    for s, t in zip(*counts.nonzero()):
        left = counts[s, t]
        slack += left * _SUB_OF[:, t]
        cards = classes == s * 16 + t
        remaining_mask = int(t)
        for receiver in range(4):
            if not remaining_mask & (1 << receiver):
                continue
            remaining_mask ^= 1 << receiver
            if left and remaining_mask:
                # Subsets covering only the receiver bound k from above. Those
                # covering only the residual mask bound left-k from above.
                upper = min(left, slack[_UPPER_SUBSETS[receiver][remaining_mask]].min())
                lower = max(0, left - slack[_LOWER_SUBSETS[receiver][remaining_mask]].min())
                choices = np.arange(lower, upper + 1)
            else:
                choices = np.array([left], dtype=np.int64)
            k = yield _Allocation(s, t, receiver, lengths, cap, left, choices, cards)
            if k not in choices:
                raise ValueError("length outside public feasible support")
            lengths[s, receiver] += k
            cap[receiver] -= k
            left -= k
            if k:
                slack -= k * _SUBSETS[:, receiver]
    return lengths


def build_length_head(width=64):
    """CPU reference head for residualized belief_seq.make_batch batches."""
    import torch
    from torch import nn

    class LengthHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.context = nn.Linear(FEATURE_DIM + 4, width)
            self.suit = nn.Embedding(5, width)
            self.mask_type = nn.Embedding(16, width)
            self.receiver = nn.Embedding(4, width)
            self.prefix = nn.Linear(20 + 4 + 1, width)
            self.output = nn.Sequential(nn.ReLU(), nn.Linear(width, 26))

        def _walk(self, context, card_feat, mask, copies, sizes, *, labels=None, rng=None):
            steps = _allocation_steps(card_feat, mask, copies, sizes)
            losses = []
            try:
                step = next(steps)
                while True:
                    choices = step.choices
                    if labels is not None:
                        k = int(labels[step.cards, step.receiver].sum())
                    if len(choices) > 1:
                        prefix = np.r_[step.lengths.ravel(), step.capacity, step.left].astype(np.float32) / 25
                        state = (context + self.suit.weight[step.suit] + self.mask_type.weight[step.mask_type]
                                 + self.receiver.weight[step.receiver] + self.prefix(torch.from_numpy(prefix)))
                        logits = self.output(state)[choices]
                        if labels is None:
                            p = logits.double().softmax(0).numpy()
                            k = int(rng.choice(choices, p=p))
                        else:
                            if k not in choices:
                                raise ValueError("label outside public feasible support")
                            losses.append(-logits.log_softmax(0)[np.searchsorted(choices, k)])
                    elif labels is None:
                        k = int(choices[0])
                    step = steps.send(k)
            except StopIteration as done:
                return done.value, losses

        @torch.no_grad()
        def draw_lengths(self, inp, mask, batch, rng):
            context = self.context(torch.as_tensor(inp["X"], dtype=torch.float32))
            return np.stack([self._walk(context, inp["card_feat"], mask, inp["n_c"],
                                        inp["sizes"], rng=rng)[0] for _ in range(batch)])

        def loss(self, batch):
            """Mean negative log likelihood per decision, including forced lengths at zero cost."""
            context = self.context(torch.as_tensor(batch["X"], dtype=torch.float32))
            total = context.sum() * 0
            for row, round_index in enumerate(batch["rr"]):
                y = batch["Y"][row]
                if (y < 0).any() or (y != np.floor(y)).any() or (y[~batch["M"][row]] > 0).any():
                    raise ValueError("invalid residual card labels")
                y = y.astype(np.int64)
                sizes = np.rint(batch["X"][row, -4:] * 25).astype(np.int64)
                if not np.array_equal(y.sum(0), sizes):
                    raise ValueError("labels disagree with public receiver sizes")
                _, terms = self._walk(context[row], batch["card_feat"][round_index],
                                      batch["M"][row], y.sum(1), sizes, labels=y)
                if terms:
                    total = total + torch.stack(terms).sum()
            return total / len(context)

    return LengthHead()


def load_length_checkpoint(path):
    """Return the inference head and its training exposure for held-out evaluation."""
    import torch

    saved = torch.load(path, map_location="cpu", weights_only=True)
    if saved["schema"] != "shengji-suit-lengths-v1":
        raise ValueError("unknown suit-length checkpoint schema")
    head = build_length_head(saved["width"])
    head.load_state_dict(saved["model"], strict=True)
    if not all(torch.isfinite(p).all() for p in head.parameters()):
        raise ValueError("nonfinite suit-length checkpoint")
    return head.eval(), saved["training"]


def fit(args):
    """Fit at most one pass of the train split and publish only a completed fit."""
    import os
    import tempfile
    from pathlib import Path
    import torch
    from . import belief_seq as bs

    out = Path(args.out)
    if out.exists():
        raise FileExistsError(out)
    if min(args.steps, args.rounds_per_batch, args.width) < 1 or args.seed < 0:
        raise ValueError("positive steps, batch size and width, and a nonnegative seed required")
    entries = bs.extract_entries([args.extract], "train", exclude_seed_windows=args.exclude_seed_window)
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    head = build_length_head(args.width)
    optimizer = torch.optim.AdamW(head.parameters(), lr=args.lr)
    verified = bs._Verified()
    deals = set()
    steps = rows_used = 0
    for index in rng.permutation(len(entries)):
        part = bs.load_part(entries[index], bs.ROW_KEYS, verified)
        if not len(part["X"]):
            continue
        for rounds, rows in bs.round_batches(part, args.rounds_per_batch, rng):
            batch = bs.make_batch(part, rounds, rows)
            optimizer.zero_grad()
            loss = head.loss(batch)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite length loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
            steps += 1
            rows_used += len(rows)
            deals.update(map(int, part["deal"][rows]))
            if steps == args.steps:
                break
        if steps == args.steps:
            break
    if steps != args.steps:
        raise ValueError(f"train split supplied {steps} of {args.steps} requested steps")
    training = {"steps": steps, "rows": rows_used, "deals": sorted(deals),
                "seed": args.seed, "rounds_per_batch": args.rounds_per_batch,
                "lr": args.lr, "exclude_seed_window": args.exclude_seed_window}
    with tempfile.NamedTemporaryFile(dir=out.parent) as tmp:
        torch.save({"schema": "shengji-suit-lengths-v1", "width": args.width,
                    "model": head.state_dict(), "training": training}, tmp)
        tmp.flush()
        load_length_checkpoint(tmp.name)
        os.link(tmp.name, out)
    return training


def main(argv=None):
    import argparse
    from .belief_seq import seed_window

    parser = argparse.ArgumentParser(description="Fit an offline joint suit-length checkpoint")
    parser.add_argument("--extract", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--steps", type=int, required=True,
                        help="optimizer updates required within one train-split pass")
    parser.add_argument("--rounds-per-batch", type=int, default=1)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--exclude-seed-window", type=seed_window, action="append", default=[])
    args = parser.parse_args(argv)
    if not np.isfinite(args.lr) or args.lr <= 0:
        parser.error("--lr must be finite and positive")
    training = fit(args)
    print(f"completed {training['steps']} updates on {training['rows']} rows "
          f"from {len(training['deals'])} deals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
