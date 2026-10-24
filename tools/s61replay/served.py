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
                    or record.get('fallback_reason')):
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
