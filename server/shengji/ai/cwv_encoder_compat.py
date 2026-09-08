"""Narrow compatibility for the Torch-free public-history source move.

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
