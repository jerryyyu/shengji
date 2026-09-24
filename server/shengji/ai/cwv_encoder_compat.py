"""Narrow compatibility for source moves that provably do not change tensors.

This is not a general source-drift exception. New checkpoints hash the actual
new closure. Old full-closure identities are accepted only if restoring the
single import recreates their hash AND the extracted helper has the same
computation/constants/import dependencies as the legacy reference. Other
encoder changes still refuse. The real tensors are also differential-tested.
"""
from __future__ import annotations

import ast
import copy
import hashlib


def _function(tree, error_name):
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "encode_public_history"]
    if len(functions) != 1:
        return None
    function = copy.deepcopy(functions[0])
    function.returns = None
    for arg in function.args.args:
        arg.annotation = None
    if (function.body and isinstance(function.body[0], ast.Expr)
            and isinstance(function.body[0].value, ast.Constant)
            and isinstance(function.body[0].value.value, str)):
        function.body.pop(0)
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id == error_name:
            node.id = "HistoryError"
    return ast.dump(function, include_attributes=False)


def _constant(tree, name):
    nodes = [n.value for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    return ast.dump(nodes[0], include_attributes=False) if len(nodes) == 1 else None


def history_import_move_identity(current, paths):
    """Return the exact legacy full identity, or None if migration is unsafe."""
    try:
        old = ast.parse(paths["douzero_micro"].read_text())
        new = ast.parse(paths["public_history"].read_text())
        if _function(old, "DouZeroMicroError") != _function(new, "PublicHistoryError"):
            return None
        if any(_constant(old, key) != _constant(new, key)
               for key in ("HISTORY_MAX_EVENTS", "HISTORY_EVENT_DIM")):
            return None
        imports = {ast.unparse(node) for node in new.body
                   if isinstance(node, (ast.Import, ast.ImportFrom))}
        if imports != {"from __future__ import annotations", "from typing import Any",
                       "import numpy as np", "from ..engine.cards import points",
                       "from .encode import CARD_INDEX, N_CARDS"}:
            return None
        source = paths["value_afterstate"].read_bytes()
        moved = b"from .public_history import HISTORY_EVENT_DIM, encode_public_history"
        original = b"from .douzero_micro import HISTORY_EVENT_DIM, encode_public_history"
        if source.count(moved) != 1:
            return None
        sources = dict(current["source_sha256s"])
        if "public_history" not in sources:
            return None
        sources.pop("public_history")
        sources["value_afterstate"] = hashlib.sha256(source.replace(moved, original)).hexdigest()
        parts = [current["identity_schema"], current["afterstate_schema"]]
        version = current.get("enc_version", 1)
        if version != 1:
            parts.append(f"enc_version:{version}")
        payload = "|".join(parts + [f"{name}:{sha}" for name, sha in sorted(sources.items())])
        return hashlib.sha256(payload.encode("ascii")).hexdigest()
    except (OSError, KeyError, SyntaxError, TypeError, ValueError):
        return None


#: ROUND REVISIONS PROVEN ENCODING-EQUIVALENT, newest tree source -> the source it
#: replaces, as sha256 of ``engine/round.py``.  A pair earns its place here ONLY by
#: a differential tensor test that encodes the same states under BOTH revisions and
#: asserts the bytes are identical (tests/test_encoder_round_compat.py); it is not
#: earned by reading the diff and judging it harmless.
#:
#: 02e7831e -> 2ec9c567 is the failed-throw notice (#621, 4ab306e2): +48 lines adding
#: ``notice``, ``NOTICE_PLAYS``, ``_set_notice`` and ``_age_notice`` to ``Round``.
#: The encoder never reads any of them, and #634 is what happened because the guard
#: cannot tell: a tree at main refused the package production serves.
ROUND_EQUIVALENT_SOURCES = {
    "2ec9c5677e80449560f69abac53db271710cf8a64b2afe7ae15949698d3a4e95":
        "02e7831ec58c224dc1eee83cab465c9e4b3002e1f52eff03125cd84809c2432c",
}


def round_notice_identity(current, paths=None):
    """The exact legacy identity when ``round.py`` is the only drifted source.

    WHY THIS IS NOT A PIN.  ``cwv_data.PUBLISHED_SOURCE_SHA256`` would also fix
    #634, in one line, by pinning ``round``'s digest forever -- and that is why it
    is the wrong tool: it would blind the identity to EVERY future change to
    ``round.py``, including one that really does move the tensors.  This accepts
    one named pair and nothing else.

    WHY IT CANNOT LEAK.  The legacy identity is rebuilt from the CURRENT source
    digests with only ``round`` substituted, so if any other source has also
    drifted the rebuilt hash simply will not equal what the checkpoint declared
    and the caller refuses as before.  The narrowing is structural, not a check
    somebody has to remember to write.
    """
    del paths                      # signature parity with the migration above
    try:
        sources = dict(current["source_sha256s"])
        legacy = ROUND_EQUIVALENT_SOURCES.get(sources.get("round"))
        if legacy is None:
            return None
        sources["round"] = legacy
        parts = [current["identity_schema"], current["afterstate_schema"]]
        version = current.get("enc_version", 1)
        if version != 1:
            parts.append(f"enc_version:{version}")
        payload = "|".join(parts + [f"{name}:{sha}" for name, sha in sorted(sources.items())])
        return hashlib.sha256(payload.encode("ascii")).hexdigest()
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
