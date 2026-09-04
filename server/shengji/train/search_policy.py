"""DEV-only learned root search, followed by production's independent report.

This is a root bandit, NOT recursive MCTS. The prior scores the complete legal
set; paired PUCT-style allocation chooses what to investigate. A value leaf
finishes the current trick and predicts signed level utility from the next
actor's observation. Selection values and report values never mix: the report
still uses MCBot's full heuristic rollouts, point units and original LCB rule.

The selection budget is N times the *production ballot's* size, not the larger
legal set. This matches candidate-evaluation counts, NOT CPU cost. New searches
on formerly locked/one-candidate decisions and all neural/enumeration work are
reported explicitly. A strength comparison must measure total work separately.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
import time

from ..ai.mcbot import _child_seed
from ..ai.registry import REGISTRY
from ..engine.combos import decompose
from ..engine.game import Game
from ..harvest.legal import enumerate_legal
from ..oracle.screen import OracleValueMixin


class SearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchConfig:
    arm: str = "both"             # prior / value / both / uniform
    leaf_tricks: int = 1          # 0 = immediate afterstate, 1 = current trick
    prior_uniform_mass: float = 0.05
    puct_scale: float = 40.0
    legal_limit: int = 200_000    # refuse overflow; NEVER use a capped prefix
    self_play: bool = False
    root_noise_fraction: float = 0.25
    root_noise_concentration: float = 10.0
    temperature: float = 1.0

    def __post_init__(self):
        if self.arm not in {"prior", "value", "both", "uniform"}:
            raise ValueError("unknown learned-search arm")
        if type(self.leaf_tricks) is not int or self.leaf_tricks not in (0, 1):
            raise ValueError("leaf_tricks must be 0 or 1")
        if type(self.legal_limit) is not int or self.legal_limit < 2:
            raise ValueError("legal_limit must be an integer >= 2")
        for name in ("prior_uniform_mass", "root_noise_fraction"):
            x = getattr(self, name)
            if not math.isfinite(x) or not 0 <= x <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.prior_uniform_mass == 0:
            raise ValueError("positive uniform support is required")
        for name in ("puct_scale", "root_noise_concentration", "temperature"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")


def terminal_utility(rnd, team: int) -> float:
    """Use the engine's terminal payoff, including zero-level takeover => 1."""
    if rnd.phase != "round_end":
        raise SearchError("terminal utility requires a completed round")
    game = Game(random.Random(0))
    game.round = rnd
    result = game.finish_round()
    level = max(1, int(result.level_change))
    return float(level if result.winner_team == team else -level)


class LearnedSearchBot(REGISTRY["mc-s0-report-lcb"]):
    """No registry entry: an experiment cannot silently become production."""
    ADAPTIVE_ALLOCATION = True
    TRACTOR_LOCK = False

    def __init__(self, heads, *, seed: int = 0, config: SearchConfig | None = None):
        super().__init__(seed)
        self.heads = heads
        self.search_config = config or SearchConfig()
        self.policy_name = f"mc-s0-report-lcb+learned-{self.search_config.arm}"
        self.learned_counts = {k: 0 for k in (
            "decisions", "legal_actions", "production_actions", "new_searches",
            "value_evaluations", "terminal_leaves", "leaf_plies",
            "full_rollout_calls", "off_ballot_selections", "off_ballot_plays",
            "self_play_samples")}
        self.enumeration_secs = 0.0
        self.learned_inference_secs = 0.0
        self._root = None
        # Collection exploration is a different mode, never used in a duel.
        if self.search_config.self_play:
            self.REPORT_FOLD_WORLDS = 0
            self.REPORT_RULE = "none"

    def _candidates(self, rnd, seat):
        cfg = self.search_config
        started = time.perf_counter()
        production = super()._candidates(rnd, seat)
        locked = False
        if not rnd.trick.plays:
            dec = decompose(self.canonical_lead(rnd, seat), rnd.ordering)
            locked = len(dec.components) == 1 and dec.components[0].pair_len >= 2
        keys = {tuple(sorted(a)) for a in production}
        # The value-only ablation changes the evaluator, not action coverage.
        if cfg.arm == "value":
            actions = [list(a) for a in production]
        else:
            legal = enumerate_legal(rnd, seat, cap=cfg.legal_limit + 1,
                                    must_include=production)
            if not legal.complete or len(legal.actions) > cfg.legal_limit:
                raise SearchError(f"exhaustive legal set exceeds supported limit: "
                                  f"count={legal.count}, limit={cfg.legal_limit}")
            incumbent = tuple(sorted(production[0]))
            actions = [list(incumbent)] + [a for a in legal.actions
                                          if tuple(sorted(a)) != incumbent]
        elapsed = time.perf_counter() - started
        self.enumeration_secs += elapsed
        if cfg.arm in {"prior", "both"}:
            before = time.perf_counter()
            prior = list(self.heads.priors(rnd, seat, actions))
            self.learned_inference_secs += time.perf_counter() - before
        else:
            prior = [1.0 / len(actions)] * len(actions)
        if (len(prior) != len(actions) or any(not math.isfinite(p) or p < 0 for p in prior)
                or not math.isclose(sum(prior), 1.0, rel_tol=1e-6, abs_tol=1e-8)):
            raise SearchError("prior must normalize over the exact legal population")
        mix = cfg.prior_uniform_mass
        prior = [(1 - mix) * p + mix / len(prior) for p in prior]
        if cfg.self_play and cfg.root_noise_fraction:
            rng = random.Random(_child_seed(self.rng.getstate(), "learned-root-noise"))
            noise = [rng.gammavariate(cfg.root_noise_concentration / len(prior), 1)
                     for _ in prior]
            total = sum(noise)
            if total <= 0:
                raise SearchError("root exploration produced no probability mass")
            e = cfg.root_noise_fraction
            prior = [(1 - e) * p + e * z / total for p, z in zip(prior, noise)]
        self._root = {
            "production_keys": keys, "production_size": len(production),
            "production_would_search": not locked and len(production) > 1,
            "priors": prior, "visits": [0] * len(actions),
            "enumeration_secs": elapsed,
        }
        return actions

    def _rollout(self, *args, **kwargs):
        self.learned_counts["full_rollout_calls"] += 1
        return super()._rollout(*args, **kwargs)

    def _selection_values(self, rnd, seat, hands, buried, actions, exact_session):
        if self.search_config.arm not in {"value", "both"}:
            vals = [self._score(self._rollout(rnd, seat, hands, buried, a,
                                             exact_session=exact_session)) for a in actions]
            return vals if rnd.is_attacker(seat) else [-v for v in vals]
        values = [0.0] * len(actions)
        unfinished, indices = [], []
        target_tricks = len(rnd.history) + self.search_config.leaf_tricks
        for i, action in enumerate(actions):
            # This constructor replaces EVERY hidden hand and the hidden burial
            # with the sampled world. It cannot retain the true hidden deal.
            clone = OracleValueMixin._oracle_world_clone(self, rnd, seat, hands, buried)
            clone.play(seat, list(action))
            self.learned_counts["leaf_plies"] += 1
            while clone.phase == "play" and len(clone.history) < target_tricks:
                who = clone.turn
                clone.play(who, self.rollout_policy.decide_play(clone, who))
                self.learned_counts["leaf_plies"] += 1
            self.learned_counts["value_evaluations"] += 1
            if clone.phase == "round_end":
                values[i] = terminal_utility(clone, seat % 2)
                self.learned_counts["terminal_leaves"] += 1
            else:
                unfinished.append(clone)
                indices.append(i)
        if unfinished:
            before = time.perf_counter()
            pred = self.heads.values(unfinished)
            self.learned_inference_secs += time.perf_counter() - before
            if len(pred) != len(unfinished) or any(not math.isfinite(v) for v in pred):
                raise SearchError("leaf values must be finite and cover every state")
            for i, state, v in zip(indices, unfinished, pred):
                values[i] = v if state.turn % 2 == seat % 2 else -v
        # Selection's point-shy epsilon=2 now means .05 levels. Never pass
        # predicted levels into the production points-to-score conversion.
        return [40.0 * v for v in values]

    def _decide_adaptive(self, rnd, seat, candidates, mem, i_attack, *, allocation_rng):
        root = self._root
        k = len(candidates)
        budget = self.N_DETERMINIZATIONS * max(2, root["production_size"])
        totals, d_sum, d_sq = [0.0] * k, [0.0] * k, [0.0] * k
        n_by, visits = [0] * k, root["visits"]
        attempts = worlds = spent = 0
        cap = budget * self.SAMPLE_ATTEMPT_FACTOR
        while spent + 2 <= budget and attempts < cap:
            attempts += 1
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            scale = math.sqrt(sum(visits) + 1)
            # Pairing evaluates the incumbent regardless of the allocation.
            # At least one alternative must be investigated before asking the
            # unchanged report stage to judge a challenger.
            pool = range(1, k) if worlds == 0 else range(k)
            index = max(pool, key=lambda i: (
                (totals[i] / n_by[i] if n_by[i] else 0.0)
                + self.search_config.puct_scale * root["priors"][i]
                * scale / (1 + visits[i]), -i))
            session = self._new_exact_world_session(rnd, buried)
            # The incumbent is already the paired reference. If PUCT chooses
            # it, evaluate it ONCE (one budget unit and one allocation visit),
            # rather than spending two units on an identical [base, base] pair.
            chosen = [0, index] if index else [0]
            values = self._selection_values(
                rnd, seat, hands, buried, [candidates[i] for i in chosen], session)
            for i, v in zip(chosen, values):
                totals[i] += v
                n_by[i] += 1
            if index:
                delta = values[1] - values[0]
                d_sum[index] += delta
                d_sq[index] += delta * delta
            visits[index] += 1
            self.learned_counts["off_ballot_selections"] += int(
                tuple(sorted(candidates[index])) not in root["production_keys"])
            worlds += 1
            spent += len(chosen)
        dummy = 0
        # An odd final unit is real work, but not a policy visit or estimate.
        if spent + 1 == budget:
            while attempts < cap:
                attempts += 1
                sampled = self._sample_hands(rnd, seat, mem)
                if sampled is not None:
                    hands, buried = sampled
                    self._selection_values(rnd, seat, hands, buried, [candidates[0]],
                                           self._new_exact_world_session(rnd, buried))
                    spent += 1
                    dummy = 1
                    break
        survivors = [i for i, n in enumerate(n_by) if n]
        self.last_alloc = {
            "mode": "learned_root_paired_puct", "attempts": attempts,
            "attempt_cap": cap, "attempt_cap_hit": attempts >= cap and spent < budget,
            "worlds": worlds, "rollouts": spent, "decision_rollouts": spent - dummy,
            "dummy_rollouts": dummy, "budget": budget, "short": spent != budget,
            "survivors": len(survivors), "survivor_indices": survivors,
            "n_by_candidate": n_by,
        }
        return totals, d_sum, d_sq, n_by, worlds, spent

    def decide_play(self, rnd, seat):
        before_counts = dict(self.learned_counts)
        before_inference = self.learned_inference_secs
        before = time.perf_counter()
        self._root = None
        action = super().decide_play(rnd, seat)
        root = self._root
        if root is None:
            raise SearchError("learned search did not construct a root")
        self.learned_counts["decisions"] += 1
        self.learned_counts["legal_actions"] += len(root["priors"])
        self.learned_counts["production_actions"] += root["production_size"]
        searched = self.last_decision_record is not None
        self.learned_counts["new_searches"] += int(searched and not root["production_would_search"])
        rec = self.last_decision_record
        if searched and self.search_config.self_play and sum(root["visits"]):
            log_weights = [(math.log(n) / self.search_config.temperature if n else -math.inf)
                           for n in root["visits"]]
            high = max(log_weights)
            weights = [math.exp(w - high) for w in log_weights]
            rng = random.Random(_child_seed(self.rng.getstate(), "learned-root-action"))
            chosen = rng.choices(range(len(weights)), weights=weights, k=1)[0]
            action = list(rec["candidates"][chosen])
            self._finalise_record(rec["candidates"], chosen, "self_play_root_visits")
            self.learned_counts["self_play_samples"] += 1
        self.learned_counts["off_ballot_plays"] += int(tuple(sorted(action)) not in root["production_keys"])
        if rec is not None:
            rec["learned_search"] = {
                "schema": "learned-root-search-v1", "config": asdict(self.search_config),
                "production_size": root["production_size"],
                "production_would_search": root["production_would_search"],
                "legal_size": len(root["priors"]), "priors": root["priors"],
                "allocation_visits": root["visits"],
                "visits_meaning": "selected root investigations, NOT paired reference counts or full-tree MCTS",
                "selection_units": ("acting-team signed levels x40" if
                                    self.search_config.arm in {"value", "both"} else "acting-team points"),
                "report_evaluator": "production full heuristic rollout, point units",
                "enumeration_secs": root["enumeration_secs"],
                "inference_secs": self.learned_inference_secs - before_inference,
                "decision_wall_secs": time.perf_counter() - before,
                "counts": {k: self.learned_counts[k] - before_counts[k] for k in before_counts},
            }
        return action
