"""Opt-in capture of actual search prior requests; never a gameplay metric.

Capture is an outcome-blind request prefix, conditioned on the generating
search. Priors express action preference, not terminal win probabilities.
No comparator work or additional model calls occur inside search.
"""
from dataclasses import dataclass

import numpy as np

from ..ai.cwv_puct import leaf_copy


@dataclass
class PriorRequest:
    state: object
    seat: int
    ballot: tuple
    observation: np.ndarray
    candidates: np.ndarray
    probabilities: np.ndarray | None = None


class PriorRecorder:
    """Wrap the encode/batch_from_encoded interface used by PUCT.

    Retain at most ``limit`` states. Request identity, not equal feature bytes,
    associates probabilities with the exact state/ballot that generated them.
    Unserved captured requests remain explicitly incomplete. This wrapper is
    diagnostic-only: copying states adds overhead, so its timing is not a
    performance comparison against an unwrapped search.
    """
    def __init__(self, prior, limit=16):
        if type(limit) is not int or limit < 1:
            raise ValueError("positive integer capture limit required")
        self.prior, self.limit = prior, limit
        self.rows = []
        self._pending = {}

    def __getattr__(self, name):
        return getattr(self.prior, name)

    def encode(self, state, seat, ballot):
        encoded = self.prior.encode(state, seat, ballot)
        if len(self.rows) < self.limit:
            row = PriorRequest(leaf_copy(state), seat,
                               tuple(tuple(play) for play in ballot),
                               np.array(encoded[0], copy=True),
                               np.array(encoded[1], copy=True))
            self.rows.append(row)
            # Retaining the encoded object prevents id reuse before dispatch.
            self._pending[id(encoded)] = (encoded, row)
        return encoded

    def batch_from_encoded(self, encoded_rows):
        output = self.prior.batch_from_encoded(encoded_rows)
        if len(output) != len(encoded_rows):
            raise ValueError("one prior vector per request required")
        for encoded, probabilities in zip(encoded_rows, output, strict=True):
            pending = self._pending.get(id(encoded))
            if pending is None:
                continue
            original, row = pending
            if original is not encoded:
                raise RuntimeError("prior request identity mismatch")
            p = np.asarray(probabilities)
            if (p.shape != (len(row.ballot),) or not np.isfinite(p).all()
                    or np.any(p < 0) or not np.isclose(p.sum(), 1.0, atol=1e-5, rtol=0)):
                raise ValueError("finite normalized ballot probability vector required")
            row.probabilities = p.copy()
            del self._pending[id(encoded)]
        return output

    def batch_probabilities(self, requests):
        return self.batch_from_encoded([self.encode(*request) for request in requests])

    def probabilities(self, state, seat, ballot):
        return self.batch_probabilities([(state, seat, ballot)])[0]


def compare_prior(probabilities, world_values, *, top_k=5):
    """Compare ballot preference to common-world final-level means.

    Stable input order breaks prior ties. Comparator ties are an explicit best
    set; no softmax of levels or fictitious win-probability target is created.
    World rows are correlated diagnostic evidence, not independent games.
    """
    p, values = np.asarray(probabilities, float), np.asarray(world_values, float)
    if (p.ndim != 1 or not len(p) or not np.isfinite(p).all() or np.any(p < 0)
            or not np.isclose(p.sum(), 1., atol=1e-5, rtol=0)):
        raise ValueError("normalized finite ballot probabilities required")
    if (values.ndim != 2 or values.shape[0] < 1 or values.shape[1] != len(p)
            or not np.isfinite(values).all()):
        raise ValueError("finite nonempty world-by-ballot matrix required")
    if type(top_k) is not int or top_k < 1:
        raise ValueError("positive integer top_k required")
    means = values.mean(axis=0)
    order = np.argsort(-p, kind="stable")
    best = means == means.max()
    pairs = correct = 0
    for a in range(len(p)):
        for b in range(a):
            if means[a] != means[b]:
                pairs += 1
                correct += int(np.sign(p[a] - p[b]) == np.sign(means[a] - means[b]))
    selected = int(order[0])
    return dict(worlds=len(values), actions=len(p), selected_index=selected,
                comparator_means=means.tolist(), prior_probabilities=p.tolist(),
                comparator_best_indices=np.flatnonzero(best).tolist(),
                comparator_regret=float(means.max() - means[selected]),
                best_set_prior_mass=float(p[best].sum()),
                top_k=min(top_k, len(p)),
                top_k_hits_best=bool(best[order[:top_k]].any()),
                strict_pairs=pairs, pairwise_accuracy=correct / pairs if pairs else None)


def compare_request(row, *, sampler, worlds=4, batch_size=128, top_k=5):
    """Post-search, fresh common legal worlds for every captured candidate.

    Caller supplies a NEW sampler/RNG, never the live search sampler. Its
    public constraints must be reconstructed for the captured actor/state.
    No true other hands from the captured determinization are used directly.
    This is conditional on the captured ballot, which need not be exhaustive.
    """
    from ..ai.cwv_policy import afterstate, sample_worlds
    from ..ai.memory import Memory
    from .cwv_truncated_value import continuation_values
    if row.probabilities is None:
        raise ValueError("prior request has not been served")
    if type(worlds) is not int or worlds < 1:
        raise ValueError("positive world count required")
    sampled, attempts = sample_worlds(sampler, row.state, row.seat, worlds,
                                     mem=Memory(row.state, row.seat, own_kitty=False))
    if len(sampled) != worlds:
        raise ValueError("diagnostic world pool underfilled")
    leaves = [afterstate(row.state, row.seat, hands, buried, list(action))
              for hands, buried in sampled for action in row.ballot]
    result = continuation_values(leaves, [row.seat] * len(leaves),
        [len(row.state.history)] * len(leaves), evaluator=None, tricks=None,
        batch_size=batch_size)
    matrix = result.values.reshape(worlds, len(row.ballot))
    return dict(schema="cwv-prior-request-comparison-v1",
        selection="prefix-of-actual-search-requests-conditional-ballot",
        comparator="full-heuristic-not-optimal-policy-truth",
        own_kitty=False,
        units="captured-acting-team-final-signed-levels", seat=row.seat,
        ballot=[list(a) for a in row.ballot], attempts=attempts,
        sampled_worlds=[dict(hands=h, buried=b) for h, b in sampled],
        world_values=matrix.tolist(), heuristic_plies=result.heuristic_plies,
        metrics=compare_prior(row.probabilities, matrix, top_k=top_k))
