#!/usr/bin/env python3
"""Fail-closed compatibility receipt for PR71's heuristic prefilter.

RLCB-C1's receipt and the live-champion parent deliberately retain their
historical ``59fa...`` policy identity.  PR71 changes the source text of the
rollout heuristic, which correctly moves the source-derived ballot identity,
even though the changed loop skips only tractor lengths that cannot exist.

This module records the narrow compatibility claim separately.  It binds the
old/new heuristic bytes, the three historical and current RLCB policy
contracts, the unchanged non-ballot portion of those contracts, one exact
native runtime, and reproducible fixed-seed full-round transcripts.  It does
not rewrite historical evidence, run an experiment, promote a policy, or
authorize deployment.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Mapping


SCHEMA = "pr71-policy-compatibility-receipt-v1"
PARENT_GIT = "093ec33d8d9e137d276b84ffd907ca4417ba44af"
HISTORICAL_GIT = "ced1033e47bcb27b82136f72c757de40387a94f0"
PRE_OPTIMIZATION_GIT = "2443be9978e8cb36825d41f31c6dd6c20bdd6644"
HEURISTIC_PATH = "server/shengji/ai/heuristic.py"
HISTORICAL_HEURISTIC_SHA256 = (
    "a99dfb089fd17e7c17ddcc4d76542552d317598fbe233269c3e7c0501b9b15ef"
)
CURRENT_HEURISTIC_SHA256 = (
    "84f1968697c2518fa719c79582f01f3e05f6df5a2c365d07be603fc5ebf88bd5"
)
POLICIES = (
    "mc-s0-report-lcb", "mc-strong", "mc-strong-null-rlcb-c1",
)
HISTORICAL_BALLOT = "mc_candidates@v1[a68f7b8bced6]"
CURRENT_BALLOT = "mc_candidates@v1[fb231baf1959]"
HISTORICAL_POLICY_CONTRACT_SHA256S = {
    "mc-s0-report-lcb": (
        "59fa033dc22d8a055b5d7f3fbcbaf9d7fb0b71993b74c4d9bb7587e3d90dc72b"
    ),
    "mc-strong": (
        "64aa5d0a21dfc5608675c30adf2089f8da2668d528a8985be3fdd7f32e98a35d"
    ),
    "mc-strong-null-rlcb-c1": (
        "5629a69390be122149c8e6809c0869e35288067948f315bde8415541d524b968"
    ),
}
CURRENT_POLICY_CONTRACT_SHA256S = {
    "mc-s0-report-lcb": (
        "a8475fb372d2410f80e99215aabd6a5420973584c798486d824ccccad96dd446"
    ),
    "mc-strong": (
        "a6716f1e27be97f65c1b326f42ac30ce9666136351186c91b22fdadd655a41a3"
    ),
    "mc-strong-null-rlcb-c1": (
        "eef8b2bdf0c87a855aed5f6861f30321686add22d6e97bed345027299a72939a"
    ),
}
NON_BALLOT_POLICY_CONTRACT_SHA256S = {
    "mc-s0-report-lcb": (
        "6898c2e42f42502e8cebe6b74543a4c3fdbba33f0286a7cc3969bab1ca8c2e05"
    ),
    "mc-strong": (
        "3115cc911f90719575e27e34e2742f893c5d1e2be683fe5c935d02d68282d377"
    ),
    "mc-strong-null-rlcb-c1": (
        "f4990e69e821a50be14cbeb82ed32ee388c473346b283c9068ba4954afeda055"
    ),
}
POLICY_CONTRACT_RUNTIME = {
    "python": "3.14.3",
    "system": "Darwin",
    "machine": "arm64",
    "fast_binary_sha256": (
        "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1"
    ),
}
PARITY_RUNTIME = {
    "python": "3.14.4",
    "system": "Linux",
    "machine": "x86_64",
    "base_fast_binary_sha256": (
        "e00c0fa56f74643bea3fb4ee2a6aa4248587196beac1a38acbb9212ac2ad3b8f"
    ),
    "current_fast_binary_sha256": (
        "63207d8d68e0a69058d4b0cc442c6cd5e8a148e66c65bc76df1db60d4740978c"
    ),
    "elf_text_section_bytes": 108_462,
    "base_elf_text_sha256": (
        "5f53fdd25a7d801b003bddb5dd9170daa44aeabde276efda5c2a1254b8344fa5"
    ),
    "current_elf_text_sha256": (
        "5f53fdd25a7d801b003bddb5dd9170daa44aeabde276efda5c2a1254b8344fa5"
    ),
    "architecture_normalization": "SHA256(ELF .text section bytes)",
}
TRANSCRIPT_SEEDS = (701, 733, 769)
TRANSCRIPT_WITNESSES = {
    "701": {
        "transcript_sha256": (
            "21d5fc8e162ae64fb82542167f6c5f9a76135af55309fdca09681efc1c26a14d"
        ),
        "history_plays": 80,
        "rollouts": [10_170, 13_290, 11_400, 13_890],
        "searches": [13, 18, 15, 17],
        "short_search_decisions": [0, 0, 0, 0],
        "zero_world_decisions": [0, 0, 0, 0],
    },
    "733": {
        "transcript_sha256": (
            "9d4c603e9ecff55856e96d9bb2e35eb02257475e84afb3339300a5d4927cb627"
        ),
        "history_plays": 72,
        "rollouts": [13_620, 9_270, 10_320, 12_540],
        "searches": [17, 12, 14, 16],
        "short_search_decisions": [0, 0, 0, 0],
        "zero_world_decisions": [0, 0, 0, 0],
    },
    "769": {
        "transcript_sha256": (
            "be03a70715f26600292a5c65cb5ec0e3d5a395b79cd8eeacd8119725fb178fc2"
        ),
        "history_plays": 76,
        "rollouts": [12_510, 14_730, 12_810, 11_040],
        "searches": [16, 18, 16, 14],
        "short_search_decisions": [0, 0, 0, 0],
        "zero_world_decisions": [0, 0, 0, 0],
    },
}
PARITY_GEOMETRY = {
    "policy": "mc-s0-report-lcb",
    "opponent": "mc-strong",
    "n_determinizations": 30,
    "report_fold_worlds": 300,
    "seeds": list(TRANSCRIPT_SEEDS),
    "game_rng": "random.Random(seed)",
    "bot_seed": "seed * 100 + seat",
    "environment": {
        "SHENGJI_FAST": "1",
        "SHENGJI_REQUIRE_VOIDS": "1",
        "PYTHONHASHSEED": "0",
    },
    "rounds_per_implementation": 3,
    "independent_process_pairs": 3,
}


class CompatibilityRefused(RuntimeError):
    """The supplied receipt is not the exact reviewed compatibility claim."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def self_hash(receipt: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json({
        key: value for key, value in receipt.items()
        if key != "receipt_sha256"
    }))


def expected_receipt() -> dict:
    parity_evidence = copy.deepcopy(PARITY_GEOMETRY)
    parity_evidence.update({
        "witnesses": copy.deepcopy(TRANSCRIPT_WITNESSES),
        "full_actions_equal": True,
        "full_transcripts_equal": True,
        "rollout_search_short_zero_counters_equal": True,
    })
    receipt = {
        "schema": SCHEMA,
        "parent_git": PARENT_GIT,
        "historical_rlcb_c1": {
            "git": HISTORICAL_GIT,
            "heuristic_sha256": HISTORICAL_HEURISTIC_SHA256,
            "ballot": HISTORICAL_BALLOT,
            "policy_contract_sha256s":
                dict(HISTORICAL_POLICY_CONTRACT_SHA256S),
            "rewritten": False,
        },
        "pre_optimization": {
            "git": PRE_OPTIMIZATION_GIT,
            "heuristic_sha256": HISTORICAL_HEURISTIC_SHA256,
        },
        "current_pr71": {
            "git": PARENT_GIT,
            "heuristic_sha256": CURRENT_HEURISTIC_SHA256,
            "ballot": CURRENT_BALLOT,
            "policy_contract_sha256s":
                dict(CURRENT_POLICY_CONTRACT_SHA256S),
        },
        "live_champion_parent": {
            "schema": "live-champion-parent-v1",
            "policy": "mc-s0-report-lcb",
            "historical_policy_contract_sha256":
                HISTORICAL_POLICY_CONTRACT_SHA256S["mc-s0-report-lcb"],
            "historical_parent_mutated": False,
        },
        "semantic_contract": {
            "excluded_field": "ballot",
            "historical_non_ballot_policy_contract_sha256s":
                dict(NON_BALLOT_POLICY_CONTRACT_SHA256S),
            "current_non_ballot_policy_contract_sha256s":
                dict(NON_BALLOT_POLICY_CONTRACT_SHA256S),
            "non_ballot_contracts_equal": True,
            "ballot_difference_is_source_identity_only": True,
        },
        "native_runtime": {
            "policy_contract_runtime": dict(POLICY_CONTRACT_RUNTIME),
            "parity_runtime": dict(PARITY_RUNTIME),
        },
        "parity_evidence": parity_evidence,
        "claim_boundary": {
            "compatibility_only": True,
            "historical_evidence_rewritten": False,
            "strength_claim": False,
            "run_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    receipt["receipt_sha256"] = self_hash(receipt)
    return receipt


def receipt_problems(receipt: object) -> list[str]:
    expected = expected_receipt()
    if not isinstance(receipt, dict):
        return ["compatibility receipt is not an object"]
    problems = []
    if set(receipt) != set(expected):
        problems.append("compatibility receipt fields drifted")
    for field in expected:
        if receipt.get(field) != expected[field]:
            problems.append(f"compatibility receipt {field} drifted")
    if receipt.get("receipt_sha256") != self_hash(receipt):
        problems.append("compatibility receipt self-hash drifted")
    return sorted(set(problems))


def require_receipt(receipt: object) -> dict:
    problems = receipt_problems(receipt)
    if problems:
        raise CompatibilityRefused("; ".join(problems))
    return dict(receipt)


if __name__ == "__main__":
    print(canonical_json(expected_receipt()).decode(), end="")
