"""Opt-in throw-component admission; leaves MC selection/report unchanged.

The model shortlist is retained in full. Its direct lead components join the
same candidate set, scored on the same selection worlds. No inference about
the actual opponents' cards or throw-failure probability is made here.
"""
from ..engine.combos import decompose
from .cwv_shortlist import CWVShortlistBot
from .cwv_bury_policy import CWVBuryBot


class CWVThrowComponentsBot(CWVShortlistBot):
    def _augment_selected(self, rnd, actions, selected):
        if rnd.trick is not None and rnd.trick.plays:
            return selected
        indices = {tuple(sorted(action)): i for i, action in enumerate(actions)}
        expanded = list(selected)
        seen = set(selected)
        # Iterate only the original model ballot, not recursively added moves.
        for index in selected:
            components = decompose(actions[index], rnd.ordering).components
            if len(components) < 2:
                continue
            for component in components:
                key = tuple(sorted(component.cards))
                if key not in indices:
                    raise ValueError("throw component missing from exhaustive legal population")
                component_index = indices[key]
                if component_index not in seen:
                    expanded.append(component_index)
                    seen.add(component_index)
        return expanded


class CWVThrowComponentsBuryBot(CWVThrowComponentsBot, CWVBuryBot):
    """Same admission experiment with the unchanged hybrid-bury implementation."""
