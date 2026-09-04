"""``shengji-decision-record-v1``: one JSONL line per decision afterstate.

Spec fields (harvest_spec.md, ledger 29871a60 / 7a799e1c)
----------------------------------------------------------
schema, source, source_ref, policy, round_seed / deck, setup, plays_prefix,
seat, ply, trick, role, legal_actions, ballot, allocation, action_values,
action, outcome, hidden_hands, record_sha256.

Fields this implementation adds (all documented here, none silently)
--------------------------------------------------------------------
decision_kind         "play" (default) or "bury" — bury decisions are a
                      separate record kind (spec: human extractor).
legal_actions_complete  false when the exhaustive set was capped or when the
                      source stored only a ballot (spec note on legal_actions).
legal_actions_count   exact size of the exhaustive legal set (or null when it
                      could not be counted — see legal.py).
production_ballot     the production ``MCBot._candidates`` ballot when the
                      source recorded it beside a wider search ballot
                      (Luna ``production_prior``, PT1 ``production_ballot``).
authority             governance labels carried from the source, never
                      adjudicated (spec: "carried, not adjudicated").
state_private         true when the record's deck lives only in the private
                      split (Luna trajectories carry no deck; the synthetic
                      deal order derived from the hidden hands is hidden-hand
                      data and stays in ``*.private.jsonl``).
public_record_sha256  private-split rows only: hash of the public projection,
                      linking the private row to its public twin.
engine_play           only when the engine recorded different cards than the
                      submitted ``action`` (a failed lead throw is forced to
                      its lowest beatable component); ``plays_prefix`` of the
                      following records carries the engine's cards.
exploration           self-play generator (``trajectory``) records only:
                      ``{"rate": r, "added": [actions], "pool_count": n}``
                      when the root exploration draw fired for this decision
                      (``added`` are the legal actions appended to the search
                      ballot, drawn uniformly over the FULL exhaustive legal
                      set minus the ballot -- ``pool_count`` is that set's
                      exact size, null when it was uncountable and the draw
                      was skipped), ``null`` when the draw did not fire (every
                      decision of an ``--explore-rate 0`` run, and
                      tractor-locked leads that never reach a ballot).
                      Sources that do not explore omit the key.
preference            self-play generator records only: the preregistered
                      policy target, ``{"softmax": [...], "final": [...],
                      "tau", "means", "paired_se", "refined_indices",
                      "played_index"}`` -- two distributions aligned with
                      ``ballot`` (each sums to 1, zero outside the ballot):
                      ``softmax_i`` proportional to ``exp((mean_i - max mean)
                      / tau)`` over the search's own per-candidate means, and
                      ``final`` one-hot on the played action.  The
                      ``trajectory`` ``allocation`` (kind ``search-work``) is
                      the search's fixed-design work split, NOT a preference;
                      see ``trajectory.py`` for the exact definition.

Conventions
-----------
* ``setup`` = ``{trump_rank, banker, declarations: [{seat, cards}] in order,
  declaration: final {seat, cards, strength} | null, trump_suit, trump_is_nt,
  buried | null, passed?: [seats that passed after the last declaration —
  only PT1 records it; the PT0 public-state hash covers it]}``.
* ``plays_prefix`` is ``[{"seat": s, "cards": [...]}, ...]`` in engine order;
  card order inside a play is kept as the source recorded it (RAW).
* ``ply`` counts plays before this decision (0 = the opening lead);
  ``trick`` = ``ply // 4``.  Bury records have ``ply = trick = null``.
* ``role`` is ``banker-team`` / ``attacker-team`` for the acting seat.
* ``outcome.signed_level_utility`` is signed for the ACTING seat's
  partnership (PT0 ``signed_level_utility`` convention: +gain when the seat
  that made this decision won the round).  ``winner_team`` is seat parity.
* ``hidden_hands`` = ``{"hands_by_seat": [4 sorted hands AT THIS DECISION],
  "buried": sorted}``.
* ``record_sha256`` = sha256 of the canonical JSON (sorted keys, compact,
  ASCII) of the record minus ``record_sha256`` itself.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "shengji-decision-record-v1"
SOURCES = ("luna-rpc", "room-log", "highn", "pt1", "human", "trajectory")
DECISION_KINDS = ("play", "bury")
ROLES = ("banker-team", "attacker-team")

#: Every field a public record may carry, in documentation order.
FIELDS = (
    "schema", "source", "source_ref", "policy", "decision_kind",
    "round_seed", "deck", "setup", "plays_prefix",
    "seat", "ply", "trick", "role",
    "legal_actions", "legal_actions_complete", "legal_actions_count",
    "ballot", "production_ballot", "allocation", "preference", "action_values",
    "action", "engine_play", "outcome", "authority", "exploration",
    "state_private", "hidden_hands", "record_sha256",
)
PRIVATE_ONLY_FIELDS = ("hidden_hands", "public_record_sha256")
REQUIRED = (
    "schema", "source", "source_ref", "policy", "decision_kind",
    "round_seed", "deck", "setup", "plays_prefix", "seat", "ply", "trick",
    "role", "legal_actions", "legal_actions_complete", "legal_actions_count",
    "ballot", "allocation", "action_values", "action", "outcome",
    "hidden_hands", "record_sha256",
)


class SchemaError(ValueError):
    """A record does not satisfy ``shengji-decision-record-v1``."""


def canonical_json(value: Any) -> str:
    """Closed canonical encoding: sorted keys, compact separators, ASCII."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def record_sha256(record: Mapping[str, Any]) -> str:
    """Canonical JSON hash of the record minus ``record_sha256``."""
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    return hashlib.sha256(canonical_json(body).encode("ascii")).hexdigest()


def _is_card_list(value: Any) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(isinstance(c, str) and c for c in value))


def _is_action_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_card_list(a) for a in value)


def validate_record(record: Mapping[str, Any]) -> None:
    """Fail closed on a malformed record (types and cross-field rules)."""
    missing = [k for k in REQUIRED if k not in record]
    if missing:
        raise SchemaError(f"missing fields: {missing}")
    unknown = [k for k in record
               if k not in FIELDS and k not in PRIVATE_ONLY_FIELDS]
    if unknown:
        raise SchemaError(f"unknown fields: {unknown}")
    if record["schema"] != SCHEMA:
        raise SchemaError(f"schema must be {SCHEMA!r}")
    if record["source"] not in SOURCES:
        raise SchemaError(f"unknown source {record['source']!r}")
    if not isinstance(record["source_ref"], str) or not record["source_ref"]:
        raise SchemaError("source_ref must be a non-empty string")
    if not isinstance(record["policy"], str) or not record["policy"]:
        raise SchemaError("policy must be a non-empty string")
    if record["decision_kind"] not in DECISION_KINDS:
        raise SchemaError(f"decision_kind must be one of {DECISION_KINDS}")
    seed, deck = record["round_seed"], record["deck"]
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise SchemaError("round_seed must be an int or null")
    if deck is not None and not (_is_card_list(deck) and len(deck) == 108):
        raise SchemaError("deck must be the 108-card deal order or null")
    if seed is None and deck is None and not record.get("state_private"):
        raise SchemaError("one of round_seed/deck is required unless "
                          "state_private is set")
    if not isinstance(record["setup"], dict):
        raise SchemaError("setup must be an object")
    for key in ("trump_rank", "banker", "declarations", "trump_suit",
                "trump_is_nt"):
        if key not in record["setup"]:
            raise SchemaError(f"setup.{key} missing")
    prefix = record["plays_prefix"]
    if not isinstance(prefix, list) or not all(
            isinstance(p, dict) and isinstance(p.get("seat"), int)
            and _is_card_list(p.get("cards")) for p in prefix):
        raise SchemaError("plays_prefix must be a list of {seat, cards}")
    seat = record["seat"]
    if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
        raise SchemaError("seat must be an int in [0, 3]")
    if record["decision_kind"] == "play":
        for key in ("ply", "trick"):
            v = record[key]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise SchemaError(f"{key} must be a non-negative int")
        if record["trick"] != record["ply"] // 4:
            raise SchemaError("trick must equal ply // 4")
        if record["ply"] != len(prefix):
            raise SchemaError("ply must equal len(plays_prefix)")
    else:
        if record["ply"] is not None or record["trick"] is not None:
            raise SchemaError("bury records carry ply = trick = null")
        if prefix:
            raise SchemaError("bury records have an empty plays_prefix")
    if record["role"] not in ROLES:
        raise SchemaError(f"role must be one of {ROLES}")
    la = record["legal_actions"]
    if la is not None and not _is_action_list(la):
        raise SchemaError("legal_actions must be a list of card lists or null")
    if not isinstance(record["legal_actions_complete"], bool):
        raise SchemaError("legal_actions_complete must be a bool")
    cnt = record["legal_actions_count"]
    if cnt is not None and (isinstance(cnt, bool) or not isinstance(cnt, int)
                            or cnt < 0):
        raise SchemaError("legal_actions_count must be a non-negative int/null")
    if la is not None and record["legal_actions_complete"] and cnt != len(la):
        raise SchemaError("a complete legal set must have count == len")
    for key in ("ballot", "production_ballot"):
        b = record.get(key)
        if b is not None and not _is_action_list(b):
            raise SchemaError(f"{key} must be a list of card lists or null")
    for key in ("allocation", "action_values", "outcome", "hidden_hands",
                "authority"):
        v = record.get(key)
        if v is not None and not isinstance(v, dict):
            raise SchemaError(f"{key} must be an object or null")
    if not _is_card_list(record["action"]):
        raise SchemaError("action must be a non-empty card list")
    if "engine_play" in record and not _is_card_list(record["engine_play"]):
        raise SchemaError("engine_play must be a non-empty card list")
    if record["decision_kind"] == "bury" and len(record["action"]) != 8:
        raise SchemaError("a bury action has exactly 8 cards")
    if "exploration" in record and record["exploration"] is not None:
        ex = record["exploration"]
        rate = ex.get("rate") if isinstance(ex, dict) else None
        pool = ex.get("pool_count") if isinstance(ex, dict) else None
        if (not isinstance(ex, dict) or set(ex) != {"rate", "added", "pool_count"}
                or isinstance(rate, bool) or not isinstance(rate, (int, float))
                or not 0 <= rate <= 1 or not _is_action_list(ex["added"])
                or (pool is not None and (isinstance(pool, bool)
                                          or not isinstance(pool, int) or pool < 0))):
            raise SchemaError("exploration must be {rate in [0, 1], added: "
                              "[card lists], pool_count: int >= 0 | null} or null")
        if record["ballot"] is not None:
            keys = {tuple(sorted(a)) for a in record["ballot"]}
            if any(tuple(sorted(a)) not in keys for a in ex["added"]):
                raise SchemaError("exploration.added must be on the ballot")
    if "preference" in record and record["preference"] is not None:
        pref = record["preference"]
        if not isinstance(pref, dict) or not {"softmax", "final"} <= set(pref):
            raise SchemaError("preference must carry softmax and final, or be null")
        width = None if record["ballot"] is None else len(record["ballot"])
        for key in ("softmax", "final"):
            dist = pref[key]
            if (not isinstance(dist, list) or not dist
                    or any(isinstance(p, bool) or not isinstance(p, (int, float))
                           or not 0 <= p <= 1 for p in dist)
                    or abs(sum(dist) - 1.0) > 1e-9
                    or (width is not None and len(dist) != width)):
                raise SchemaError(f"preference.{key} must be a distribution "
                                  "over the ballot (sum 1, aligned with ballot)")
    if la is not None and record["decision_kind"] == "play":
        key = tuple(sorted(record["action"]))
        if key not in {tuple(sorted(a)) for a in la}:
            raise SchemaError("action must be a member of legal_actions")
    if record["outcome"] is not None:
        for key in ("attacker_points", "winner_team", "signed_level_utility"):
            if key not in record["outcome"]:
                raise SchemaError(f"outcome.{key} missing")
    if record["hidden_hands"] is not None:
        hh = record["hidden_hands"]
        if (not isinstance(hh.get("hands_by_seat"), list)
                or len(hh["hands_by_seat"]) != 4
                or not isinstance(hh.get("buried"), list)):
            raise SchemaError("hidden_hands must carry hands_by_seat[4] + buried")
    if record_sha256(record) != record["record_sha256"]:
        raise SchemaError("record_sha256 drift")


def finalize_record(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Fill defaults, stamp ``record_sha256`` and validate.

    ``fields`` may omit optional keys; ``record_sha256`` is always recomputed.
    """
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "decision_kind": "play",
        "round_seed": None, "deck": None,
        "legal_actions": None, "legal_actions_complete": False,
        "legal_actions_count": None,
        "ballot": None, "allocation": None, "action_values": None,
        "outcome": None, "hidden_hands": None, "authority": None,
    }
    record.update({k: v for k, v in fields.items() if k != "record_sha256"})
    for optional in ("production_ballot", "engine_play"):
        if optional in record and record[optional] is None:
            del record[optional]
    if not record.get("state_private"):
        record.pop("state_private", None)
    record["record_sha256"] = record_sha256(record)
    validate_record(record)
    return record


def public_projection(record: Mapping[str, Any],
                      private_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    """The public row: ``hidden_hands`` (and any private-only field) removed.

    ``private_fields`` are set to null (the key stays, so the schema shape is
    stable; a dotted name such as ``setup.buried`` nulls a nested key) and
    ``state_private`` is stamped when a state field is withheld.
    """
    public = {k: v for k, v in record.items()
              if k not in PRIVATE_ONLY_FIELDS}
    public["hidden_hands"] = None
    for key in private_fields:
        if "." in key:
            parent, child = key.split(".", 1)
            if isinstance(public.get(parent), dict) and child in public[parent]:
                public[parent] = {**public[parent], child: None}
        elif key in public:
            public[key] = None
    if any(key in ("deck", "round_seed") for key in private_fields):
        public["state_private"] = True
    return finalize_record(public)


def split_record(record: Mapping[str, Any],
                 private_fields: tuple[str, ...] = ()) -> tuple[dict, dict | None]:
    """Return ``(public_row, private_row)``.

    ``private_row`` is None when the record carries no hidden hands.  A
    private row is the full record plus ``public_record_sha256``.
    """
    public = public_projection(record, private_fields)
    if record.get("hidden_hands") is None and not private_fields:
        return public, None
    private = dict(record)
    private["public_record_sha256"] = public["record_sha256"]
    private = finalize_record(private)
    return public, private


def encode_line(record: Mapping[str, Any]) -> str:
    """One JSONL line: canonical JSON + newline (byte-identical on re-run)."""
    return canonical_json(record) + "\n"
