"""S149 decision evidence for the RT3-FT versus whole-action duel."""
from duel_arm import ACTION, CONTROL, UNIFIED

CHALLENGER = f"{CONTROL}-uaction{ACTION[:8]}"


def record_play(bot, observations):
    decide = bot.decide_play

    def observed(rnd, seat):
        cards = decide(rnd, seat)
        rec = bot.last_decision_record
        if rec.get("policy") != bot.policy_name or sorted(rec["played"]) != sorted(cards):
            raise ValueError("decision record differs from the policy or played cards")
        observations.append({
            "seat": seat, "schema": rec["schema"], "worlds": rec.get("worlds"),
            "work_complete": rec["work_complete"], "deadline": rec.get("leaf_greedy_deadline_fired"),
            "cut_leaves": rec.get("leaf_greedy_deadline_cut_leaves"),
            "unified": dict(rec["unified"]) if "unified" in rec else None,
        })
        return cards

    bot.decide_play = observed
    return bot


def validate_row(row):
    if (row["arm"] != "identity" or row["defender"] != CONTROL or row["exploiter_base"] != CHALLENGER
            or row["fired"] != {"play": 0, "bury": 0, "declare": 0} or row["mirror"] not in (0, 1)
            or set(row["s149"]) != {"ex", "r45"}):
        raise ValueError("unexpected S149 arms")
    for side in ("ex", "r45"):
        obs = row["s149"][side]
        seats = [seat for phase, seat, *_ in row["dtrace"]
                 if phase == "P" and (seat % 2 == row["mirror"]) == (side == "ex")]
        if [r["seat"] for r in obs] != seats or len(seats) != len(row["dsecs"][side]) or not seats:
            raise ValueError(f"{side}: play evidence does not match trace")
        faults = [i for i, r in enumerate(obs) if r["schema"] == "pv-search-fallback-v1"]
        if faults != [fault["decision_index"] for fault in row["play_faults"][side]]:
            raise ValueError(f"{side}: fallback evidence differs")
        for r, history in zip(obs, row["dhist"][side], strict=True):
            if r["schema"][-12:] != history[0] or r["worlds"] != history[18]:
                raise ValueError(f"{side}: decision identity or work differs")
            u = r["unified"]
            if not isinstance(u, dict) or u.get("package") != UNIFIED[:8]:
                raise ValueError(f"{side}: missing unified evidence")
            completed = r["schema"] == "pv-search-decision-v1"
            if (not completed and r["schema"] != "pv-search-fallback-v1") or r["work_complete"] is not completed:
                raise ValueError(f"{side}: unexpected decision schema or completion flag")
            if completed:
                if (type(r["deadline"]) is not bool or type(r["cut_leaves"]) is not int
                        or r["cut_leaves"] < 0 or r["deadline"] != (r["cut_leaves"] > 0)):
                    raise ValueError(f"{side}: missing or inconsistent deadline evidence")
            if side == "ex":
                n, candidates = u.get("action_listings"), u.get("action_candidates")
                if (u.get("action_package") != ACTION or type(n) is not int or type(candidates) is not int
                        or n < 0 or candidates < 2 * n or (n == 0 and candidates != 0)):
                    raise ValueError("missing or inconsistent whole-action evidence")
            elif any(key in u for key in ("action_package", "action_listings", "action_candidates")):
                raise ValueError("control used the whole-action scorer")
