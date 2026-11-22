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


def record_bury(bot, side, observations):
    decide = bot.decide_bury

    def observed(rnd, seat):
        cards = decide(rnd, seat)
        rec = bot.last_bury_record
        chosen = (rec["candidates"][rec["picked_index"]] if rec["schema"] == "cwv-bury-policy-v1"
                  else rec["action"])
        if sorted(chosen) != sorted(cards):
            raise ValueError("bury record differs from the submitted cards")
        observations.append(dict(side=side, seat=seat, cards=sorted(cards), schema=rec["schema"],
                                 belief_worlds=rec.get("bury_belief_worlds"),
                                 belief_fallbacks=rec.get("bury_belief_fallbacks")))
        return cards

    bot.decide_bury = observed


def validate_bury(row):
    bury, = row["s149_bury"]
    seat = row["banker"]
    side = "ex" if seat % 2 == row["mirror"] else "r45"
    trace = [(entry[1], entry[-1]) for entry in row["dtrace"] if entry[0] == "B"]
    who, schema, reason, _, worlds, _ = row["bury_rec"]
    if (type(seat) is not int or not 0 <= seat < 4 or trace != [(seat, bury["cards"])]
            or row["ex_team"] != row["mirror"]
            or bury["seat"] != seat or who != side or bury["side"] != side or bury["schema"] != schema):
        raise ValueError("bury evidence differs from banker, side or trace")
    if "belief_worlds" not in bury or "belief_fallbacks" not in bury:
        raise ValueError("missing bury belief evidence")
    flag, count = bury["belief_worlds"], bury["belief_fallbacks"]
    if schema == "cwv-bury-fallback-v1":
        if reason not in ("budget", "search-error"):
            raise ValueError("missing bury fallback reason")
        if flag is None and count is None:
            return
    elif schema != "cwv-bury-policy-v1" or reason is not None or type(worlds) is not int or worlds != 32:
        raise ValueError("unexpected completed bury work")
    if flag is not True or type(count) is not int or count not in (0, 1):
        raise ValueError("missing or inconsistent bury belief evidence")


def validate_row(row):
    if (row["arm"] != "identity" or row["defender"] != CONTROL or row["exploiter_base"] != CHALLENGER
            or row["fired"] != {"play": 0, "bury": 0, "declare": 0} or row["mirror"] not in (0, 1)
            or set(row["s149"]) != {"ex", "r45"}):
        raise ValueError("unexpected S149 arms")
    validate_bury(row)
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
                if type(r["worlds"]) is not int or r["worlds"] != 64:
                    raise ValueError(f"{side}: completed play must deliver 64 worlds")
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
