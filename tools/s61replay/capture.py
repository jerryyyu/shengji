"""Capture a single flat served decision's worlds for paired diagnostics."""
from copy import deepcopy

from continuation import compare_continuations
from shengji.train.cwv_prior_admission import root_clone


def capture_lead(bot, root):
    """Observe one decision without resampling or changing its selection path.

    The supplied bot must be dedicated to this call, not shared with a server.
    Capturing references adds overhead: this is not a serving-latency benchmark.
    """
    if root.phase != 'play' or root.trick is None or root.trick.plays or max(map(len, root.hands)) <= 7:
        raise ValueError('a lead above exact coverage is required')
    if any(getattr(bot, name, False) for name in
           ('adaptive_worlds', 'adaptive_worlds_leads', 'oracle_worlds', 'oracle_mix_k', 'oracle_pin_q')):
        raise ValueError('capture requires one non-oracle flat world population')
    original = bot._worlds
    had_override = '_worlds' in vars(bot)
    override = vars(bot).get('_worlds')
    calls = []
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        calls.append(value[0])
        return value
    bot._worlds = observe
    try:
        played = bot.decide_play(deepcopy(root), root.turn)
    finally:
        if had_override:
            bot._worlds = override
        else:
            del bot._worlds
    rec = deepcopy(bot.last_decision_record)
    if (len(calls) != 1 or not calls[0] or not isinstance(rec, dict)
            or rec.get('schema') != 'pv-search-decision-v1' or rec.get('work_complete') is not True
            or rec.get('worlds') != len(calls[0]) or not rec.get('admitted')):
        raise ValueError('missing complete served ballot or single world population')
    worlds = []
    for hands, buried in calls[0]:
        world = root_clone(root, hands, buried)
        if sorted(world.hands[root.turn]) != sorted(root.hands[root.turn]):
            raise ValueError('sampled world changed actor hand')
        worlds.append(world)
    return dict(worlds=worlds, weights=[1 / len(worlds)] * len(worlds),
                served_ballot=deepcopy(rec['admitted']), served_record=rec, played=list(played))


def compare_captured(capture, alternatives, **options):
    """Use the captured served choice as baseline with the same sampled worlds."""
    actions = [capture['played'], *alternatives]
    return compare_continuations(capture['worlds'], capture['weights'], actions,
        served_ballot=capture['served_ballot'], **options)
