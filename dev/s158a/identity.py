"""Play identity: instrumented vs plain deal files. usage: identity.py A_DIR B_DIR SEED0 N"""
import json, os, sys
a, b, s0, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
same = diff = plays = 0
for s in range(s0, s0 + n):
    x = json.load(open(os.path.join(a, f"{s}.json"))); y = json.load(open(os.path.join(b, f"{s}.json")))
    plays += len(x["plays"])
    if x["plays"] == y["plays"] and x["attacker_points"] == y["attacker_points"]:
        same += 1
    else:
        diff += 1
        k = next((i for i, (p, q) in enumerate(zip(x["plays"], y["plays"])) if p != q), min(len(x["plays"]), len(y["plays"])))
        print("DIFF seed", s, "first differing play", k, x["plays"][k:k + 1], y["plays"][k:k + 1])
print(f"identity: {same}/{n} deals identical, {diff} differ, {plays} plays compared")
sys.exit(1 if diff else 0)
