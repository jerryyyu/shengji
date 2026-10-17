"""Offline ballot-refill replay and full serving-call smoke checks.

Aliases here mean identical executed leads in every supplied world, not equal
average values. They do not imply equal public information after a failed
throw, nor equivalence under an arbitrary continuation policy.
"""

from shengji.harvest.legal import resolve_lead


def replay_logged_worlds(model, rnd, seat, record, expected_policy):
    """Refuse replay when any world came from an unlogged random stream."""
    from scripts import belief_debug
    from shengji.ai import belief_numpy as bn

    if record.get("policy") != expected_policy or not expected_policy:
        raise ValueError("record policy does not match the expected served policy")
    if record.get("schema") != "pv-search-decision-v1" or not record.get("work_complete"):
        raise ValueError("requires a complete search decision")
    n = record.get("worlds")
    if type(n) is not int or not 1 <= n <= 512:
        raise ValueError("invalid logged world count")
    if record.get("belief_fallback") != 0:
        raise ValueError("belief fallback cannot reproduce the served worlds")
    proposal, worlds, stats, fill = belief_debug.regenerate(model, rnd, seat, record, n)
    if fill != 0 or len(worlds) != n:
        raise ValueError("unlogged sampler fill prevents exact world replay")
    if not all(v is True for v in belief_debug.replay_checks(record, proposal, stats).values()):
        raise ValueError("missing or mismatched logged replay counters")
    if bn.encode_snapshot(proposal.P) != record.get("belief_snapshot"):
        raise ValueError("belief snapshot differs on replay")
    return worlds


def refill_lead_aliases(rnd, seat, admitted, ranked_actions, worlds):
    """Keep first representatives, refill in policy order, preserve ballot size.

    Callers supply the original sampled worlds and the already-ranked legal
    listing. If too few distinct signatures exist, retained duplicate actions
    fill the remaining slots. The first admitted action is never removed.
    """
    if rnd.trick is None or rnd.trick.plays or rnd.turn != seat:
        raise ValueError("alias refill requires the acting seat at a lead")
    if not worlds or not admitted:
        raise ValueError("alias refill requires worlds and an admitted ballot")
    if len(ranked_actions) > 4000 or len(admitted) > 512 or len(worlds) > 512:
        raise ValueError("offline probe input exceeds its bounded ballot/world cap")
    actor = sorted(rnd.hands[seat])
    if any(sorted(hands[seat]) != actor for hands, _ in worlds):
        raise ValueError("sampled worlds must preserve the actor hand")
    keys = [tuple(sorted(action)) for action in admitted]
    if len(set(keys)) != len(keys):
        raise ValueError("admitted actions must be distinct multisets")
    cache = {}

    def signature(action):
        key = tuple(sorted(action))
        if key not in cache:
            cache[key] = tuple(
                tuple(sorted(resolve_lead(rnd, seat, action, hands)[0]))
                for hands, _ in worlds
            )
        return cache[key]

    retained, duplicates, seen = [], [], set()
    for action in admitted:
        sig = signature(action)
        if sig in seen:
            duplicates.append(list(action))
        else:
            retained.append(list(action))
            seen.add(sig)
    alias_count = len(duplicates)
    for action in ranked_actions:
        if len(retained) == len(admitted):
            break
        sig = signature(action)
        if sig not in seen:
            retained.append(list(action))
            seen.add(sig)
    replacements = len(retained) - (len(admitted) - alias_count)
    retained.extend(duplicates[:len(admitted) - len(retained)])
    return {"admitted": retained, "alias_slots": alias_count,
            "replacement_slots": replacements, "examined_actions": len(cache)}


def score_refill(bot, rnd, seat, admitted, ranked_actions, worlds):
    """Score both ballots through the real leaf/value consumer on fixed worlds.

    The maximum-mean delta is evaluator-relative, not a selected-move or
    strength result. In particular, this does not apply downstream reselect
    rules, exact search, or hidden-information continuation penalties.
    """
    result = refill_lead_aliases(rnd, seat, admitted, ranked_actions, worlds)
    before, _ = bot._value_means(rnd, seat, admitted, worlds)
    after, _ = bot._value_means(rnd, seat, result["admitted"], worlds)
    return {**result, "original_means": before.tolist(),
            "refilled_means": after.tolist(),
            "max_mean_delta": float(max(after) - max(before))}


def score_logged_refill(bot, rnd, seat, record, worlds, *, serving_refill=False,
                        complete_listings=False):
    """Require the logged listing and baseline values to replay before refill."""
    import numpy as np

    admitted = record["admitted"]
    actions = list(bot._legal(rnd, seat, [admitted[0]]).actions)
    indices = record["admitted_indices"]
    if len(indices) != len(admitted) or any(
            i < 0 or i >= len(actions) or sorted(actions[i]) != sorted(action)
            for i, action in zip(indices, admitted)):
        raise ValueError("legal listing no longer aligns with logged admission")
    priors = record["policy_log_odds_listing"]
    regenerated = False
    if complete_listings and 0 < len(priors) < len(actions):
        full = bot.scores(rnd, seat, actions, worlds).mean(axis=0)
        if (not np.allclose(full[:len(priors)], priors, rtol=0, atol=1e-6)
                or not np.allclose(full[indices], record["policy_log_odds_admitted"],
                                   rtol=0, atol=1e-6)):
            raise ValueError("regenerated policy scores disagree with logged prefix/admission")
        priors = full.tolist()
        regenerated = True
    if len(priors) != len(actions) or not np.isfinite(priors).all():
        raise ValueError("complete finite logged policy listing unavailable")
    before, _ = bot._value_means(rnd, seat, admitted, worlds)
    if not np.allclose(before, record["value_means"], rtol=0, atol=1e-6):
        raise ValueError("real evaluator does not reproduce logged baseline means")
    ranked = [actions[i] for i in sorted(range(len(actions)), key=lambda i: (-priors[i], i))]
    if serving_refill:
        import time
        from shengji.train.lead_alias_refill import refill_indices
        started = time.perf_counter()
        chosen, diagnostics = refill_indices(rnd, seat, actions, priors, indices, worlds)
        elapsed = time.perf_counter() - started
        result = {"admitted": [actions[i] for i in chosen],
                  "replacement_slots": diagnostics["lead_alias_refill_replacements"],
                  "refill_seconds": elapsed, "refill_diagnostics": diagnostics}
    else:
        result = refill_lead_aliases(rnd, seat, admitted, ranked, worlds)
    after, _ = bot._value_means(rnd, seat, result["admitted"], worlds)
    prior_by_action = {tuple(sorted(a)): priors[i] for i, a in enumerate(actions)}

    def select(ballot, means):
        winner = bot._select(rnd, seat, ballot, means, worlds=worlds,
                             priors=[prior_by_action[tuple(sorted(a))] for a in ballot])
        played = bot._swap_doomed_throw(rnd, seat, ballot[winner], worlds)
        return winner, sorted(played)

    old_index, old_played = select(admitted, before)
    if old_played != sorted(record["played"]):
        raise ValueError("selection tail does not reproduce the logged played action")
    new_index, new_played = select(result["admitted"], after)
    return {**result, "original_means": before.tolist(), "refilled_means": after.tolist(),
            "listing_regenerated": regenerated,
            "max_mean_delta": float(max(after) - max(before)),
            "selection_changed": old_played != new_played,
            "selected_mean_delta": float(after[new_index] - before[old_index]),
            "original_played": old_played, "refilled_played": new_played}


def logged_play_modes(events):
    """Join each acted timing to its unmatched play, never infer a seat's mode."""
    modes, pending, plies = {}, {}, {}
    for event in events:
        rno = event.get("round")
        if event.get("e") == "play":
            ply = plies.get(rno, 0)
            plies[rno] = ply + 1
            key = (rno, ply)
            modes[key] = "human" if event.get("bot") is False else "unknown"
            if event.get("bot") is True:
                seat_key = (rno, event["seat"])
                if seat_key in pending:
                    raise ValueError("ambiguous unmatched bot plays for timing attribution")
                pending[seat_key] = (key, (event.get("decision") or {}).get("policy"))
        elif (event.get("e") == "bot_timing" and event.get("phase") == "play"
              and event.get("acted") is True and not event.get("stale_discarded")):
            previous = pending.pop((rno, event["seat"]), None)
            if previous is None:
                continue
            key, policy = previous
            if policy and policy != event.get("policy"):
                raise ValueError("play/timing policy mismatch")
            mode = event.get("mode")
            modes[key] = mode if mode in ("bot", "takeover") else "unknown"
    return modes


def serving_smoke(factory, rnd, seat, record, *, seed):
    """A complete serving call on a captured state, with fresh sampled worlds.

    This is correctness/latency validation, not a replay of the logged choice
    or a gameplay comparison. Only public refusal memory is restored.
    """
    import copy
    import time
    from scripts.belief_debug import refusals_of
    from shengji.ai.refusal import on_record

    bot = factory(seed=seed)
    if bot.serving_budget_seconds is None:
        raise ValueError("serving smoke requires a finite configured deadline")
    refusals = refusals_of(record)
    if not all(on_record(rnd, r) for r in refusals):
        raise ValueError("logged refusal memory does not match the captured round")
    bot._refusals.key = tuple(rnd.deck)
    bot._refusals.refusals = refusals
    state = copy.deepcopy(rnd)
    started = time.perf_counter()
    cards = bot.decide_play(state, seat)
    elapsed = time.perf_counter() - started
    decision = bot.last_decision_record
    legal = copy.deepcopy(rnd)
    legal.play(seat, list(cards))
    return {"policy": bot.policy_name, "elapsed_seconds": elapsed,
            "budget_seconds": bot.serving_budget_seconds,
            "schema": decision.get("schema"), "work_complete": decision.get("work_complete"),
            "played": list(cards), "legal": True,
            "fallback_reason": decision.get("reason"),
            "refill": {k: v for k, v in decision.items() if k.startswith("lead_alias_refill")}}


def main():
    import argparse
    import json
    from collections import Counter
    from pathlib import Path
    from scripts.belief_debug import room_log_decisions
    from shengji.ai.belief_numpy import load_belief_numpy

    parser = argparse.ArgumentParser(description="Census executed-lead aliases on logged belief worlds")
    parser.add_argument("--log", required=True)
    parser.add_argument("--belief-package", required=True)
    parser.add_argument("--belief-sha256", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--value-package", help="also score replacements with the pinned served recipe")
    parser.add_argument("--serving-refill", action="store_true", help="use the bounded serving helper")
    parser.add_argument("--complete-listings", action="store_true", help="recompute truncated policy scores")
    parser.add_argument("--serving-smoke", action="store_true", help="paired full serving calls, not gameplay")
    args = parser.parse_args()
    if args.serving_smoke and not args.value_package:
        parser.error("--serving-smoke requires --value-package")
    if Path(args.log).stat().st_size > 8 * 1024 * 1024:
        parser.error("room log exceeds the 8 MiB census bound")
    events = [json.loads(line) for line in Path(args.log).read_text().splitlines() if line.strip()]
    modes = logged_play_modes(events)
    policy_plays, plies = Counter(), Counter()
    for event in events:
        if event.get("e") != "play":
            continue
        rno = event.get("round")
        key = (rno, plies[rno])
        plies[rno] += 1
        if (event.get("decision") or {}).get("policy") == args.policy:
            policy_plays[modes[key]] += 1
    model = load_belief_numpy(args.belief_package, args.belief_sha256)
    bot = None
    if args.value_package:
        import tomllib
        from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries
        env = tomllib.loads((Path(__file__).resolve().parents[2] / "fly.toml").read_text())["env"]
        env.update(SHENGJI_PV_CKPT=args.value_package, SHENGJI_PV_BELIEF_CKPT=args.belief_package)
        if env["SHENGJI_PV_BELIEF_SHA256"] != args.belief_sha256:
            raise ValueError("belief package differs from the served recipe")
        entries = pv_registry_entries(**pv_env_recipe(env))
        bot = entries[args.policy](seed=0)
        if args.serving_smoke:
            base_factory = entries[args.policy]
            env["SHENGJI_PV_LEAD_ALIAS_REFILL"] = "1"
            candidate_entries = pv_registry_entries(**pv_env_recipe(env))
            candidate_factory = next(iter(candidate_entries.values()))
    rows, skipped = [], Counter()
    for rno, ply, rnd, seat, record in room_log_decisions(args.log):
        if record.get("policy") != args.policy or rnd.trick.plays:
            continue
        if record.get("exact_lead_status") == "complete":
            skipped["exact_complete"] += 1
            continue
        if len(rows) >= 200:
            raise ValueError("census exceeds 200 non-exact leads")
        if args.serving_smoke:
            if modes[(rno, ply)] != "bot":
                skipped["not_bot_mode"] += 1
                continue
            rows.append({"round": rno, "ply": ply, "seat": seat,
                         "baseline": serving_smoke(base_factory, rnd, seat, record, seed=ply),
                         "candidate": serving_smoke(candidate_factory, rnd, seat, record, seed=ply)})
            continue
        try:
            worlds = replay_logged_worlds(model, rnd, seat, record, args.policy)
        except ValueError as exc:
            skipped[str(exc)] += 1
            continue
        admitted = record["admitted"]
        result = refill_lead_aliases(rnd, seat, admitted, [], worlds)
        means = record["value_means"]
        if len(means) != len(admitted):
            raise ValueError("logged value means do not align with the ballot")
        row = {"round": rno, "ply": ply, "seat": seat, "mode": modes[(rno, ply)],
                     "slots": len(admitted), "alias_slots": result["alias_slots"],
                     "equal_mean_slots": len(means) - len(set(means))}
        if bot is not None:
            try:
                scored = score_logged_refill(bot, rnd, seat, record, worlds,
                                             serving_refill=args.serving_refill,
                                             complete_listings=args.complete_listings)
                row.update(replacement_slots=scored["replacement_slots"],
                           listing_regenerated=scored["listing_regenerated"],
                           max_mean_delta=scored["max_mean_delta"],
                           selection_changed=scored["selection_changed"],
                           selected_mean_delta=scored["selected_mean_delta"],
                           original_played=scored["original_played"],
                           refilled_played=scored["refilled_played"])
                if args.serving_refill:
                    row.update(refill_seconds=scored["refill_seconds"],
                               refill_diagnostics=scored["refill_diagnostics"])
            except ValueError as exc:
                row["score_refused"] = str(exc)
        rows.append(row)
    result = {"policy": args.policy, "belief_sha256": model.package_sha256,
              "policy_plays_by_mode": dict(policy_plays),
              "decisions": len(rows), "slots": sum(r.get("slots", 0) for r in rows),
              "alias_slots": sum(r.get("alias_slots", 0) for r in rows),
              "equal_mean_slots": sum(r.get("equal_mean_slots", 0) for r in rows),
              "skipped": dict(skipped), "rows": rows,
              "scope": ("non-exact leads in bot mode only" if args.serving_smoke else
                        "all logged served-policy bot decisions, including takeovers"),
              "claim": ("full serving correctness/latency smoke; fresh worlds; not gameplay strength"
                        if args.serving_smoke else
                        "executed-lead census and optional evaluator-relative selection replay; no gameplay strength estimate")}
    with open(args.output, "x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    main()
