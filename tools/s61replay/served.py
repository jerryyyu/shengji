"""Use a bound production bot factory for replies and independent leaf scores."""
import math


def reply_factory(make_bot):
    """Create fresh per-seat policy state with paired deterministic seeds."""
    def factory(rng):
        bots = [make_bot(seed=rng.randrange(2**32)) for _ in range(4)]
        def reply(state, seat):
            if seat != state.turn:
                raise ValueError('reply seat drift')
            bot = bots[seat]
            cards = bot.decide_play(state, seat)
            record = bot.last_decision_record
            if (not isinstance(record, dict)
                    or record.get('schema') != 'pv-search-decision-v1'
                    or record.get('work_complete') is not True
                    or record.get('fallback_reason')
                    or record.get('belief_fallback', 0)
                    or (getattr(bot, 'belief_worlds', False)
                        and record.get('belief_fallback') != 0)
                    or record.get('worlds') != bot.worlds):
                raise ValueError('reply lacks complete served decision evidence')
            return dict(cards=list(cards), fallback=False)
        return reply
    return factory


def endpoint_evaluator(bot):
    """Score with the package-bound evaluator, preserving the original seat."""
    evaluator = bot.evaluator
    def evaluate(state, root_seat):
        if type(root_seat) is not int or not 0 <= root_seat < 4:
            raise ValueError('invalid endpoint perspective seat')
        values = evaluator.score([state], root_seat)
        if len(values) != 1 or not math.isfinite(float(values[0])):
            raise ValueError('invalid endpoint score')
        return float(values[0])
    return evaluate


def replay_served_prefix(row, make_bot, *, seat):
    """Restore one seat's pre-first-lead policy state from checked decisions."""
    from collections import Counter
    from replay import replay_root
    if type(seat) is not int or seat not in range(4) or type(row.get('seed')) is not int:
        raise ValueError('invalid replay seat or seed')
    bot = make_bot(seed=row['seed'] * 16 + seat + 7)
    calls = []
    def advance(phase, state, actor, cards):
        if actor != seat or phase == 'P':
            return
        if phase in ('D', 'F'):
            actual = bot.decide_declare(state, seat, final=phase == 'F')
            record = getattr(bot, 'last_declare_record', None)
        elif phase == 'B':
            actual = bot.decide_bury(state, seat)
            record = getattr(bot, 'last_bury_record', None)
        else:
            raise ValueError('unexpected prefix phase')
        if isinstance(record, dict) and record.get('fallback_reason'):
            raise ValueError('prefix policy fallback')
        if Counter(actual or []) != Counter(cards):
            raise ValueError('served prefix decision drift')
        calls.append(phase)
    root, witness = replay_root(row, 0, on_decision=advance)
    if root.turn != seat:
        raise ValueError('target is not the first lead seat')
    return bot, root, dict(witness, prefix_policy_calls=calls,
                           policy_seed=row['seed'] * 16 + seat + 7)
