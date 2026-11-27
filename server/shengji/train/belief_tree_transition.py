"""Public evidence for a simulated lead that the engine reduced."""
from ..ai.refusal import observe_refusal
from ..engine.round import actual_play_after
from ..harvest.common import action_key


def lead_refusal_after(child, seat, attempted, previous_last_trick):
    played = action_key(actual_play_after(child, seat, previous_last_trick))
    attempted = action_key(attempted)
    if played == attempted:
        return None
    notice = observe_refusal(child)
    if (not played or notice is None or notice.seat != seat or notice.trick_index != len(child.history)
            or action_key(notice.attempted) != attempted or action_key(notice.forced) != played
            or child.trick is None or len(child.trick.plays) != 1):
        raise ValueError("substituted lead lacks a matching public refusal")
    return notice
