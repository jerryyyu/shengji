"""Per-copy marginal surprisal via independent draws from the joint proposal."""
import numpy as np

from ..ai.belief_numpy import draw_length_worlds


def first_hit_loss(truth, draw_world, rng, max_draws):
    """Return the sum of copy-weighted inverse-binomial scores and unseen copy count.

    For a randomly selected copy of a code, the first draw putting it at receiver
    r has a geometric waiting time T with parameter p. E[H_(T-1)] = -log(p),
    by the power series sum((1-p)**k/k). A censored observation has an unknown
    remaining contribution and cannot supply a completed log-loss estimate.
    """
    copies = truth.sum(1)
    card, receiver = np.nonzero(truth)
    weights = truth[card, receiver]
    waiting = np.ones(len(card), dtype=bool)
    score = 0.
    for trial in range(1, max_draws + 1):
        if not waiting.any():
            break
        world = draw_world()
        # The two copies of one code can be split. Sample one exchangeable copy.
        ticket = (rng.random(len(copies)) * copies).astype(int)
        holder = (world.cumsum(1) <= ticket[:, None]).sum(1)
        waiting &= holder[card] != receiver
        score += weights[waiting].sum() / trial
    return score, int(weights[waiting].sum())


class MarginalLoss:
    """Pair each independent replicate with the same analytic projected baseline."""
    def __init__(self, replicates, max_draws):
        if replicates < 2 or max_draws < 1:
            raise ValueError("log-loss requires two or more replicates and a positive draw limit")
        self.joint = np.zeros(replicates)
        self.unseen = np.zeros(replicates, dtype=np.int64)
        self.max_draws = max_draws
        self.baseline = 0.
        self.copies = 0

    def add(self, inp, q, truth, head, stream):
        hit = truth > 0
        if (q[hit] <= 0).any() or not np.isfinite(q[hit]).all():
            raise ValueError("invalid baseline mass at a true receiver")
        self.baseline -= (truth[hit] * np.log(q[hit])).sum()
        self.copies += int(truth.sum())
        for i, child in enumerate(stream.spawn(len(self.joint))):
            rng = np.random.default_rng(child)

            def draw():
                # One world per call gives each trial its own card ordering.
                return draw_length_worlds(inp, q, inp["M"], head.draw_lengths, 1, rng)[0]

            score, unseen = first_hit_loss(truth, draw, rng, self.max_draws)
            self.joint[i] += score
            self.unseen[i] += unseen

    def report(self):
        complete = self.copies > 0 and not self.unseen.any()
        delta = (self.joint - self.baseline) / max(1, self.copies)
        return {"hidden_copies": self.copies, "replicates": len(delta),
                "draw_limit_per_row_per_replicate": self.max_draws,
                "unresolved_copy_observations": int(self.unseen.sum()),
                "projected_baseline_nats_per_copy": self.baseline / self.copies if self.copies else None,
                "joint_minus_baseline_nats_per_copy": float(delta.mean()) if complete else None,
                "monte_carlo_standard_error": float(delta.std(ddof=1) / np.sqrt(len(delta)))
                if complete else None}
