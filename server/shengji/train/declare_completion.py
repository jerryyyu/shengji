"""Actor-visible declaration completions; no live hidden-deal access.

Named proposal: pin publicly shown copies before their reveal deadlines, then
shuffle the remaining physical cards. This is a feasible completion proposal,
not a uniform conditional posterior or a model of opponents' declaration intent.
Only completed sampled Rounds may reach the downstream bury/play evaluator.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
from types import SimpleNamespace

from ..ai.smart import SmartBot
from ..engine.cards import RANKS, card_rank, make_deck
from ..engine.round import Round


@dataclass(frozen=True)
class PublicDeclaration:
    seat: int
    cards: tuple[str, ...]
    deal_pos: int


@dataclass(frozen=True)
class DeclareObservation:
    seat: int
    rank: str
    banker: int | None
    deal_pos: int
    final: bool
    own_hand: tuple[str, ...]
    shown: tuple[PublicDeclaration, ...]
    options: tuple[tuple[str, ...], ...]
    passed: tuple[int, ...]


def _seat(value):
    return type(value) is int and 0 <= value < 4


def _strength(cards, rank):
    if len(cards) == 1 and card_rank(cards[0]) == rank:
        return 1
    if len(cards) == 2 and cards[0] == cards[1]:
        return 3 if cards[0] == 'LJ' else 4 if cards[0] == 'BJ' else 2 if card_rank(cards[0]) == rank else 0
    return 0


def validate_observation(obs):
    if type(obs) is not DeclareObservation or not _seat(obs.seat) \
            or obs.rank not in RANKS or (obs.banker is not None and not _seat(obs.banker)) \
            or type(obs.deal_pos) is not int or not 1 <= obs.deal_pos <= 100 \
            or type(obs.final) is not bool:
        raise ValueError('invalid declaration observation identity')
    if obs.final and obs.deal_pos != 100 or not obs.final and (obs.deal_pos-1) % 4 != obs.seat:
        raise ValueError('observation is not at its bot declaration callback')
    if not all(type(x) is tuple for x in (obs.own_hand, obs.shown, obs.options, obs.passed)):
        raise ValueError('immutable observation channels required')
    population = Counter(make_deck())
    own = Counter(obs.own_hand)
    own_size = len(range(obs.seat, obs.deal_pos, 4))
    if len(obs.own_hand) != own_size or own-population:
        raise ValueError('own hand disagrees with physical population or deal position')
    if any(not _seat(s) for s in obs.passed) or tuple(sorted(set(obs.passed))) != obs.passed \
            or obs.passed and obs.deal_pos != 100:
        raise ValueError('invalid public pass state')
    previous_pos, previous_strength = 0, 0
    bounds = [Counter() for _ in range(4)]
    for event in obs.shown:
        if type(event) is not PublicDeclaration or not _seat(event.seat) \
                or type(event.cards) is not tuple or Counter(event.cards)-population \
                or type(event.deal_pos) is not int or not previous_pos <= event.deal_pos <= obs.deal_pos \
                or event.deal_pos < 1:
            raise ValueError('invalid public declaration history')
        strength = _strength(event.cards, obs.rank)
        if strength <= previous_strength:
            raise ValueError('public declaration strengths must strictly increase')
        bounds[event.seat] |= Counter(event.cards)
        if sum(bounds[event.seat].values()) > len(range(event.seat, event.deal_pos, 4)):
            raise ValueError('shown cards exceed hand capacity at reveal')
        previous_pos, previous_strength = event.deal_pos, strength
    if bounds[obs.seat]-own:
        raise ValueError('own shown cards missing from current hand')
    required = own.copy()
    for seat, bound in enumerate(bounds):
        if seat != obs.seat:
            required.update(bound)
    if required-population:
        raise ValueError('public shown cards contradict the physical population')


def capture_observation(rnd, seat, shown, *, final=False):
    """Read only current actor cards and public fields, never deck/kitty/RNG.

    The caller maintains only accepted public declarations, not the privileged
    multi-seat capture event list. Old overwritten declarations remain evidence.
    """
    if not _seat(seat) or rnd.phase not in ('deal', 'declare'):
        raise ValueError('declaration callback required')
    history = tuple(shown)
    obs = DeclareObservation(seat, rnd.trump_rank, rnd.banker, rnd._deal_pos,
        final, tuple(sorted(rnd.hands[seat])), history,
        tuple(tuple(cards) for cards in rnd.declare_options(seat)), tuple(sorted(rnd.passed)))
    validate_observation(obs)
    expected = None
    if history:
        last = history[-1]
        expected = {'seat': last.seat, 'cards': list(last.cards),
                    'strength': _strength(last.cards, obs.rank)}
    if rnd.declaration != expected:
        raise ValueError('public history does not match the current declaration')
    return obs


def baseline_action(obs):
    """Reuse SmartBot's actual declaration rule through an own-hand-only view."""
    validate_observation(obs)
    class OwnHandOnly:
        def __getitem__(self, seat):
            if seat != obs.seat:
                raise AssertionError('baseline declaration read a hidden hand')
            return list(obs.own_hand)
    def options(seat):
        if seat != obs.seat:
            raise AssertionError('baseline requested another actor options')
        return [list(cards) for cards in obs.options]
    visible = SimpleNamespace(hands=OwnHandOnly(), trump_rank=obs.rank, declare_options=options)
    action = SmartBot().decide_declare(visible, obs.seat, final=obs.final)
    return None if action is None else tuple(action)


def sample_completion_deck(obs, seed):
    """Return a full physical deck using this immutable observation alone."""
    validate_observation(obs)
    if type(seed) is not int or seed < 0:
        raise ValueError('nonnegative independent completion seed required')
    rng = random.Random(seed)
    deck = [None]*108
    own = Counter(obs.own_hand)
    unknown = Counter(make_deck())-own
    shown = [Counter() for _ in range(4)]
    for event in obs.shown:
        # A single later shown as a pair contributes one new copy, not three.
        additional = Counter(event.cards)-shown[event.seat]
        for card in sorted(additional.elements()):
            available = [i for i in range(event.seat, event.deal_pos, 4) if deck[i] is None]
            if not available:
                raise ValueError('no legal slot before public reveal deadline')
            slot = rng.choice(available)
            source = own if event.seat == obs.seat else unknown
            if source[card] < 1:
                raise ValueError('shown-card placement exhausted physical copies')
            source[card] -= 1
            deck[slot] = card
        shown[event.seat] |= Counter(event.cards)
    own_remaining = sorted(own.elements())
    rng.shuffle(own_remaining)
    own_slots = [i for i in range(obs.seat, obs.deal_pos, 4) if deck[i] is None]
    if len(own_slots) != len(own_remaining):
        raise ValueError('own prefix capacity mismatch')
    for slot, card in zip(own_slots, own_remaining, strict=True):
        deck[slot] = card
    unknown_remaining = sorted(unknown.elements())
    rng.shuffle(unknown_remaining)
    open_slots = [i for i, card in enumerate(deck) if card is None]
    if len(open_slots) != len(unknown_remaining):
        raise ValueError('unknown completion capacity mismatch')
    for slot, card in zip(open_slots, unknown_remaining, strict=True):
        deck[slot] = card
    if Counter(deck) != Counter(make_deck()):
        raise ValueError('completion lost physical conservation')
    return tuple(deck)


def build_sampled_prefix(obs, seed):
    """Replay public declarations on a fresh sampled engine prefix."""
    deck = sample_completion_deck(obs, seed)
    rnd = Round(obs.rank, obs.banker, random.Random(0))
    rnd.deck, rnd.kitty = list(deck), list(deck[100:])
    event_index = 0
    for deal_pos in range(1, obs.deal_pos+1):
        rnd.deal_next()
        while event_index < len(obs.shown) and obs.shown[event_index].deal_pos == deal_pos:
            event = obs.shown[event_index]
            rnd.declare(event.seat, list(event.cards))
            event_index += 1
    rnd.passed = set(obs.passed)
    if tuple(sorted(rnd.hands[obs.seat])) != obs.own_hand \
            or tuple(tuple(cards) for cards in rnd.declare_options(obs.seat)) != obs.options:
        raise ValueError('sampled prefix does not reproduce actor hand/legal options')
    return rnd
