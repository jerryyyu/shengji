"""JevBot: card play chosen by TypeSafe's Jev model (a System One "Choice").

Jerry 2026-09-21: "I just made a TypeSafe account for jev — build a harness to
play shengji for it. Actions need to be encoded."

Every play decision becomes ONE Choice question: the state is the encoded
public game state from this seat (own hand, trump, the trick on the table and
who is winning it, previous tricks, points), the criteria are the legal plays
(each encoded as an option with its cards, shape, suit, points and whether it
would win the trick as it stands), and the answer is the chosen option plus a
probability per option and a confidence.  Declare and bury stay heuristic
(as the pv-search serving mode does): a bury is one of ~10^7 subsets and does
not fit a 255-option Choice.

Spend control (the project rule: no LLM-token spend without a ceiling): the
live client refuses to start without a call ceiling, every bot draws from a
shared ``JevBudget``, and once the ceiling is reached the bot falls back to the
heuristic play and says so in its record.  Any API error, an unknown answer or
an illegal option also falls back to the heuristic -- a Jev bot never stalls a
game and never plays an illegal card.

Transport: the HTTP API directly (``POST /v1/systemone``, bearer key), through
the standard library, so the engine gains no dependency; the SDK is not used.
The ``ask`` callable is injectable, which is how the tests run without a key.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field

from ..engine.cards import BJ, LJ, TRUMP, Ordering, card_rank, card_suit, is_joker, points, total_points
from ..engine.combos import decompose
from ..engine.legal import beats, uniform_suit
from ..engine.round import Round
from ..harvest.legal import enumerate_legal
from .heuristic import HeuristicBot

RECORD_SCHEMA = "jev-decision-v1"
FALLBACK_SCHEMA = "jev-fallback-v1"
DEFAULT_MODEL = "jev-latest"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
MODEL_ENV = "TYPESAFE_DEFAULT_MODEL"
MAX_CALLS_ENV = "SHENGJI_JEV_MAX_CALLS"
MAX_OPTIONS = 255          # the Choice limit
DEFAULT_OPTIONS = 120      # legal plays offered per decision (heuristic incumbent always included)
SUIT_NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs", TRUMP: "trump"}

RULES = (
    "Sheng Ji (two decks, 108 cards, 4 players in two teams: seats 0+2 and 1+3). "
    "The banker's team defends; the other team attacks and wins the round by collecting "
    "80 or more points (5s are 5, 10s and Ks are 10; the last trick's winner, if an attacker, "
    "also takes the buried kitty's points times a multiplier). Trump = the trump suit, every "
    "card of the trump rank, and both jokers (BJ big joker highest, then LJ). A trick is won by "
    "the highest play in the led suit unless trump is played; followers must follow the led "
    "suit and shape (pair for pair, tractor for tractor) while they can. Playing more cards than "
    "the lead (a throw) is only legal when every part would win."
)


class JevError(RuntimeError):
    pass


@dataclass
class JevBudget:
    """One ceiling shared by every Jev bot in a game or harness run."""
    max_calls: int
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    fallbacks: Counter = field(default_factory=Counter)

    def take(self) -> bool:
        if self.calls >= self.max_calls:
            return False
        self.calls += 1
        return True

    def charge(self, usage: dict | None) -> None:
        if usage:
            self.input_tokens += int(usage.get("input_tokens", 0) or 0)
            self.output_tokens += int(usage.get("output_tokens", 0) or 0)

    def snapshot(self) -> dict:
        return {"max_calls": self.max_calls, "calls": self.calls,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "fallbacks": dict(self.fallbacks)}


class TypeSafeHTTP:
    """The documented HTTP contract: POST {base}/v1/systemone with a bearer key."""

    def __init__(self, api_key: str, *, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, timeout: float = 20.0, opener=None):
        if not api_key:
            raise JevError(f"{API_KEY_ENV} is not set")
        self.api_key, self.base_url, self.model, self.timeout = api_key, base_url.rstrip("/"), model, timeout
        self._open = opener or urllib.request.urlopen

    def __call__(self, state, questions: dict) -> dict:
        body = json.dumps({"state": state, "model": self.model, "questions": questions}).encode()
        req = urllib.request.Request(
            self.base_url + "/v1/systemone", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise JevError(f"HTTP {exc.code}: {exc.read()[:200]!r}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise JevError(f"transport: {exc}") from exc


# ------------------------------------------------------------------ encoding

def card_label(code: str) -> str:
    if code == BJ:
        return "BJ (big joker)"
    if code == LJ:
        return "LJ (little joker)"
    return f"{code} ({card_rank(code)} of {SUIT_NAMES[card_suit(code)]})"


def option_key(cards: list[str]) -> str:
    """Stable option name: the canonical (sorted) card codes joined by '+'."""
    return "+".join(sorted(cards))


def _shape_name(cards: list[str], o: Ordering) -> str:
    d = decompose(cards, o)
    runs, singles = d.shape()
    if len(cards) == 1:
        return "single"
    if runs == (1,) and singles == 0:
        return "pair"
    if len(runs) == 1 and singles == 0:
        return f"tractor of {runs[0]} consecutive pairs"
    return f"throw ({len(cards)} cards: {len(runs)} pair-run(s), {singles} single(s))"


def _incumbent(rnd: Round):
    """(winning seat, suit, top level) of the trick so far, as the engine resolves it."""
    o, plays = rnd.ordering, rnd.trick.plays
    if not plays:
        return None
    lead = plays[0].cards
    inc_suit = uniform_suit(lead, o)
    inc_top = decompose(lead, o).top_level()
    winner = plays[0].seat
    for tp in plays[1:]:
        won, top = beats(tp.cards, lead, inc_suit, inc_top, o)
        if won:
            winner, inc_top, inc_suit = tp.seat, top, o.eff_suit(tp.cards[0])
    return winner, inc_suit, inc_top


def describe_option(rnd: Round, seat: int, cards: list[str]) -> dict:
    o = rnd.ordering
    suit = uniform_suit(cards, o)
    out = {"cards": [card_label(c) for c in sorted(cards, key=o.sort_key, reverse=True)],
           "shape": _shape_name(cards, o),
           "suit": SUIT_NAMES.get(suit, "mixed suits") if suit else "mixed suits",
           "points_in_play": total_points(cards)}
    inc = _incumbent(rnd)
    if inc is not None:
        _, inc_suit, inc_top = inc
        won, _ = beats(list(cards), rnd.trick.plays[0].cards, inc_suit, inc_top, o)
        out["wins_trick_as_it_stands"] = bool(won)
    return out


def encode_state(rnd: Round, seat: int, *, history_tricks: int = 6) -> dict:
    """The public state from ``seat``: never another hand, never the kitty."""
    o = rnd.ordering
    assert o is not None and rnd.trick is not None and rnd.banker is not None
    hand = sorted(rnd.hands[seat], key=o.sort_key, reverse=True)
    by_suit: dict[str, list[str]] = {}
    for c in hand:
        by_suit.setdefault(SUIT_NAMES[o.eff_suit(c)], []).append(card_label(c))
    team = "attackers" if rnd.is_attacker(seat) else "defenders (banker's team)"
    seen = Counter(c for t in rnd.history for tp in t.plays for c in tp.cards)
    seen.update(c for tp in rnd.trick.plays for c in tp.cards)
    seen.update(rnd.hands[seat])
    unseen = Counter()
    for c in rnd.deck:
        if seen[c] > 0:
            seen[c] -= 1
        else:
            unseen[SUIT_NAMES[o.eff_suit(c)]] += 1
    inc = _incumbent(rnd)
    trick = {"leader": rnd.trick.leader,
             "plays": [{"seat": tp.seat,
                        "team": "attackers" if rnd.is_attacker(tp.seat) else "defenders",
                        "partner_of_me": tp.seat % 2 == seat % 2 and tp.seat != seat,
                        "cards": [card_label(c) for c in tp.cards]} for tp in rnd.trick.plays],
             "points_on_table": total_points(c for tp in rnd.trick.plays for c in tp.cards)}
    if inc is not None:
        trick["currently_winning"] = {"seat": inc[0],
                                      "team": "attackers" if rnd.is_attacker(inc[0]) else "defenders",
                                      "is_my_partner": inc[0] % 2 == seat % 2 and inc[0] != seat}
    else:
        trick["note"] = "you lead this trick"
    return {
        "rules": RULES,
        "trump": {"suit": SUIT_NAMES[rnd.trump_suit] if rnd.trump_suit else "no trump (jokers only)",
                  "rank": rnd.trump_rank},
        "me": {"seat": seat, "team": team, "partner_seat": (seat + 2) % 4},
        "banker_seat": rnd.banker,
        "attacker_points_so_far": rnd.attacker_points,
        "tricks_played": len(rnd.history), "tricks_left": 25 - len(rnd.history),
        "my_hand_by_suit_high_to_low": by_suit,
        "cards_not_yet_seen_by_suit": dict(unseen),
        "current_trick": trick,
        "previous_tricks_most_recent_first": [
            {"leader": t.leader, "winner": t.winner, "points": t.points,
             "plays": [[tp.seat, [card_label(c) for c in tp.cards]] for tp in t.plays]}
            for t in reversed(rnd.history[-history_tricks:])],
    }


def shortlist(actions: list[list[str]], incumbent: list[str], limit: int) -> list[list[str]]:
    """The options offered: smallest plays first (singles, pairs, tractors before throws),
    higher-point plays first within a size, the heuristic's incumbent always present."""
    ranked = sorted(actions, key=lambda a: (len(a), -total_points(a), option_key(a)))
    keys = {option_key(a) for a in ranked[:limit]}
    out = ranked[:limit]
    if option_key(incumbent) not in keys:
        out = out[:limit - 1] + [list(incumbent)]
    return out


def encode_options(rnd: Round, seat: int, actions: list[list[str]]) -> dict[str, dict]:
    return {option_key(a): describe_option(rnd, seat, a) for a in actions}


INSTRUCTIONS = (
    "You are seat {seat} on the {team}. Choose the play that most improves your team's chance "
    "to win this round. Win tricks that carry points, feed points to a partner who is winning, "
    "duck with worthless cards when an opponent is winning, keep high trumps for later tricks, "
    "and remember attackers need 80 points in total."
)


# ------------------------------------------------------------------- the bot

class JevBot(HeuristicBot):
    """Plays through Jev; declare and bury through the heuristic."""

    def __init__(self, seed: int = 0, *, ask=None, budget: JevBudget | None = None,
                 max_options: int = DEFAULT_OPTIONS, history_tricks: int = 6,
                 model: str | None = None):
        if not (1 <= int(max_options) <= MAX_OPTIONS):
            raise ValueError(f"max_options must be in 1..{MAX_OPTIONS}")
        self.seed = seed
        self.ask = ask
        self.budget = budget
        self.max_options = int(max_options)
        self.history_tricks = history_tricks
        self.model = model
        self.last_decision_record = None
        self.calls = 0
        self.search_secs = 0.0

    # -- live client, built lazily so registry import and tests need no key ----
    def _ensure_client(self):
        if self.ask is not None:
            return
        key = os.environ.get(API_KEY_ENV, "")
        if not key:
            raise JevError(f"{API_KEY_ENV} is not set")
        if self.budget is None:
            raw = os.environ.get(MAX_CALLS_ENV, "")
            if not raw.isdigit() or int(raw) < 1:
                raise JevError(f"{MAX_CALLS_ENV} must be a positive integer (no LLM spend without a ceiling)")
            self.budget = JevBudget(int(raw))
        self.ask = TypeSafeHTTP(key, base_url=os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL),
                                model=self.model or os.environ.get(MODEL_ENV, DEFAULT_MODEL))

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        started = time.perf_counter()
        self.last_decision_record = None
        incumbent = HeuristicBot.decide_play(self, rnd, seat)
        try:
            return self._jev_play(rnd, seat, incumbent, started)
        except Exception as exc:  # any failure: the heuristic plays, and the record says why
            reason = "no-api-key" if isinstance(exc, JevError) and API_KEY_ENV in str(exc) else \
                     "no-ceiling" if isinstance(exc, JevError) and MAX_CALLS_ENV in str(exc) else \
                     "ceiling" if isinstance(exc, _Ceiling) else \
                     "bad-answer" if isinstance(exc, _BadAnswer) else "api-error"
            if self.budget is not None:
                self.budget.fallbacks[reason] += 1
            self.last_decision_record = {
                "schema": FALLBACK_SCHEMA, "played": list(incumbent), "reason": reason,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "seconds": time.perf_counter() - started}
            return list(incumbent)
        finally:
            self.search_secs += time.perf_counter() - started

    def _jev_play(self, rnd, seat, incumbent, started):
        self._ensure_client()
        legal = enumerate_legal(rnd, seat, cap=max(self.max_options, 2000), must_include=[incumbent])
        actions = shortlist(legal.actions, incumbent, self.max_options)
        if len(actions) == 1:
            self.last_decision_record = {
                "schema": RECORD_SCHEMA, "played": list(actions[0]), "forced": True, "options": 1,
                "legal_complete": legal.complete, "seconds": time.perf_counter() - started}
            return list(actions[0])
        if self.budget is not None and not self.budget.take():
            raise _Ceiling("call ceiling reached")
        options = encode_options(rnd, seat, actions)
        state = encode_state(rnd, seat, history_tricks=self.history_tricks)
        team = "attackers" if rnd.is_attacker(seat) else "defenders"
        questions = {"play": {"type": "choice",
                              "instructions": INSTRUCTIONS.format(seat=seat, team=team),
                              "criteria": options}}
        response = self.ask(state, questions)
        self.calls += 1
        answer = (response or {}).get("answers", {}).get("play") or {}
        if self.budget is not None:
            self.budget.charge((response or {}).get("usage"))
        choice = answer.get("choice")
        if choice not in options:
            raise _BadAnswer(f"answer {choice!r} is not an offered option")
        played = choice.split("+")
        probs = answer.get("probabilities") or {}
        top = sorted(probs.items(), key=lambda kv: -kv[1])[:8]
        self.last_decision_record = {
            "schema": RECORD_SCHEMA, "played": played, "choice": choice,
            "confidence": answer.get("confidence"), "top_probabilities": top,
            "options": len(actions), "legal_count": legal.count, "legal_complete": legal.complete,
            "heuristic_incumbent": option_key(incumbent),
            "agrees_with_heuristic": choice == option_key(incumbent),
            "model": (response or {}).get("model"), "usage": (response or {}).get("usage"),
            "seconds": time.perf_counter() - started}
        return played


class _Ceiling(RuntimeError):
    pass


class _BadAnswer(RuntimeError):
    pass
