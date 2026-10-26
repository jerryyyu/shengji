#!/usr/bin/env python3
"""Projects S61's archived sealed read (~/shengji-archive/2026-09-13/readouts/s61dev/result.json) to s61_reference.json: the head-to-head
[mean, lo, hi] and the class / class x trick / class x trick x rank cells {cell: {contribution, ci, deals}}, with the source sha256.  The S69
reader pins the output's sha256 and builds its versus-S61 lines from it.  Usage: python3 make_s61_reference.py [result.json] > s61_reference.json"""
import hashlib, json, os, sys
src = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/shengji-archive/2026-09-13/readouts/s61dev/result.json")
raw = open(src, "rb").read()
d = json.loads(raw)
r = d["readout"]
assert d["lane"] == "s61dev" and d["validity"] == "VALID" and d["attribution_status"] == "ATTRIBUTION_OK" and d["deals"] == 600, (d["lane"], d["validity"])
t = r["attribution"]["tables"]
out = dict(schema="s69-s61-reference-v1", source=dict(path=src, sha256=hashlib.sha256(raw).hexdigest(), lane=d["lane"], launcher_sha256=d["launcher_sha256"],
                                                      reader_sha256=d["reader_sha256"], verdict=d["verdict"]),
           levels=d["levels"], deals=d["deals"], seeds=r["seeds"],
           tables={lvl: {c["cell"]: dict(contribution=c["contribution"], ci=c["ci"], deals=c["deals"]) for c in t[lvl]} for lvl in ("class", "class_trick", "class_trick_rank")})
json.dump(out, sys.stdout, indent=1, sort_keys=True)
sys.stdout.write("\n")
