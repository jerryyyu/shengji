"""Offline autoregressive suit lengths over the actor's unknown copies.

Copies with the same effective suit and receiver mask are interchangeable for
length prediction. Allocate their counts before the belief proposal chooses
individual card identities. Both training and generation use the same order
and support, including public voids and the residual capacity of the kitty.
"""
from typing import NamedTuple

import numpy as np

from .belief_seq import FEATURE_DIM, _SUB_OF, _SUBSETS


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
    types = np.asarray(mask, bool) @ (1 << np.arange(4))
    classes = suit * 16 + types
    counts = np.zeros((5, 16), dtype=np.int64)
    np.add.at(counts.ravel(), classes, copies)
    cap = np.asarray(sizes, dtype=np.int64).copy()
    future = counts.sum(0)
    if (cap < 0).any() or cap.sum() != future.sum() or future[0]:
        raise ValueError("infeasible residual copies or receiver sizes")
    lengths = np.zeros((5, 4), dtype=np.int64)
    for s, t in zip(*counts.nonzero()):
        left = counts[s, t]
        future[t] -= left
        # For each subset of receivers, these future copies have nowhere else to go.
        need = _SUB_OF @ future
        remaining_mask = int(t)
        for receiver in range(4):
            if not remaining_mask & (1 << receiver):
                continue
            remaining_mask ^= 1 << receiver
            choices = np.arange(min(left, cap[receiver]) + 1)
            # After assigning k copies here, the remaining left-k must fit
            # among the remaining receivers of this class. Hall's condition
            # on all 16 subsets is necessary and sufficient for completion.
            capacity = (_SUBSETS @ cap) - choices[:, None] * _SUBSETS[:, receiver]
            required = need + (left - choices[:, None]) * _SUB_OF[:, remaining_mask]
            choices = choices[(capacity >= required).all(1)]
            if not len(choices):
                raise ValueError("no feasible suit length")
            k = yield _Allocation(s, t, receiver, lengths, cap, left, choices, classes == s * 16 + t)
            if k not in choices:
                raise ValueError("length outside public feasible support")
            lengths[s, receiver] += k
            cap[receiver] -= k
            left -= k
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
