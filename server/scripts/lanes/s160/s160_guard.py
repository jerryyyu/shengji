#!/usr/bin/env python3
"""S160 guards around the pinned RT2-attrib reader (kit/ut_mix_read.py, unchanged): checks it does not make, and the
verification of every saved result before the launcher reuses it.

    s160_guard.py pilot-check   RECIPE ARM          -> one JSON line (s160-pilot-check-r1); rc 0 VALID, 3 not VALID
    s160_guard.py read          RECIPE ARM OUT      -> the mirror-team check, then ut_mix_read.main(); rc 3 refuses with no outcome
    s160_guard.py verify-seal   RECIPE ARM pilot|duel
    s160_guard.py verify-pilot  RECIPE ARM CHECK.json
    s160_guard.py verify-read   RECIPE ARM READ.json
    s160_guard.py verify-attrib RECIPE ATTRIB.json
verify-* print "ok" or the reasons and exit 0 / 1.

The mirror-team check: the two mirrors of every deal put the exploiter on opposite teams ({ex_team} == {0, 1}).  The pinned
reader pairs mirrors by seed only, so a pair with the exploiter on one team twice would read as a valid zero.
The seal check: the runner's status ends in its DONE line for this recipe with 2 x deals rows; SHA256SUMS hashes to the DONE
line's digest, lists exactly the sealed files and nothing else is in the output directory; each file matches; the manifest is
this recipe's for the mode, seed and count.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SEALED = ("duel.jsonl", "duel.jsonl.resume.json", "duel.time", "manifest.json", "run.log")
PILOT_DEALS = 20
TS = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Refusal(Exception):
    pass


def recipe_arm(recipe: str, arm: str):
    rc = json.loads(Path(recipe).read_text())
    if rc.get("schema") != "utd-mix-recipe-r1" or rc.get("lane") != "S160" or arm not in rc.get("arms", {}):
        raise Refusal("not an S160 recipe arm")
    return rc, rc["arms"][arm]


def span(ra: dict, arm: str, kind: str):
    """(mode, output dir, status file, seed0, deals) of an arm's pilot or duel, as s160_run.sh lays them out."""
    lane = Path(ra["out_root"]).parent.parent
    if kind == "pilot":
        return f"pilot{arm}", lane / f"pilot{arm}", lane / f"pilot{arm}.status", ra["pilot_seed0"], PILOT_DEALS
    return arm, Path(ra["out_root"]), Path(ra["status"]), ra["seed0"], ra["deals"]


def mirror_teams(rows, seed0: int, deals: int) -> list:
    """Reasons the mirrors of a deal do not put the exploiter on opposite teams (empty when every deal does)."""
    by, bad = {}, []
    for r in rows:
        by.setdefault((r.get("seed"), r.get("mirror")), []).append(r)
    for s in range(seed0, seed0 + deals):
        a, b = by.get((s, 0), []), by.get((s, 1), [])
        if len(a) != 1 or len(b) != 1:
            bad.append(f"deal {s}: {len(a)} mirror-0 and {len(b)} mirror-1 rows")
        elif sorted((a[0].get("ex_team"), b[0].get("ex_team")), key=str) != [0, 1]:
            bad.append(f"deal {s}: exploiter teams {a[0].get('ex_team')!r} / {b[0].get('ex_team')!r}")
    return bad


def seal(recipe: str, arm: str, kind: str) -> dict:
    """The verified seal of an arm's pilot or duel output; raises Refusal on any mismatch."""
    rc, ra = recipe_arm(recipe, arm)
    mode, out, status, seed0, deals = span(ra, arm, kind)
    rsha = sha(recipe)
    try:
        lines = [l for l in status.read_text().splitlines() if l.strip()]
    except OSError:
        raise Refusal(f"no status {status}") from None
    if any(re.match(r"UTD (ABORT|PAUSED|WARNING|REFUSING|FAILED) ", l) for l in lines):
        raise Refusal(f"{status} carries a failure line")
    body = [l for l in lines if not l.startswith("UTD UNLOCKED ")]
    m = re.fullmatch(f"UTD DONE {TS} recipe={rsha} rows={2 * deals} sums=([0-9a-f]{{64}}) rc=0", body[-1]) if body else None
    if not m:
        raise Refusal(f"{status} does not end in this recipe's DONE line with {2 * deals} rows")
    if not re.fullmatch(f"UTD START {TS} mode={mode} arm={arm} pid=\\d+ seed0={seed0} deals={deals} workers=\\d+ recipe={rsha}", body[0]):
        raise Refusal(f"{status} does not start with this mode, seed and count")
    sums = out / "SHA256SUMS"
    if not sums.is_file() or sha(sums) != m[1]:
        raise Refusal("SHA256SUMS is not the file the DONE line sealed")
    entries = {}
    for line in sums.read_text().splitlines():
        e = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if not e or e[2] in entries:
            raise Refusal(f"SHA256SUMS line {line[:80]!r}")
        entries[e[2]] = e[1]
    if sorted(entries) != sorted(SEALED):
        raise Refusal(f"SHA256SUMS lists {sorted(entries)}")
    on_disk = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() or p.is_symlink())
    if on_disk != sorted(SEALED + ("SHA256SUMS",)):
        raise Refusal(f"{out} holds {on_disk}")
    bad = [f for f in SEALED if (out / f).is_symlink() or sha(out / f) != entries[f]]
    if bad:
        raise Refusal(f"sealed files differ: {bad}")
    man = json.loads((out / "manifest.json").read_text())
    want = dict(schema="utd-manifest-r1", mode=mode, arm=arm, recipe_sha256=rsha, seed0=seed0, deals=deals, tree_head=rc["tree_head"], rc=0)
    if man != want:
        raise Refusal(f"manifest {man} is not {want}")
    return dict(mode=mode, terminal=body[-1], sums_sha256=m[1], duel_jsonl_sha256=entries["duel.jsonl"], seed0=seed0, deals=deals)


def rows_of(out: Path):
    return [json.loads(l) for l in open(out / "duel.jsonl")]


def load_reader(rc: dict):
    path = Path(rc["reader"])
    if sha(path) != rc["reader_sha256"]:
        raise Refusal("the reader is not the recipe's")
    spec = importlib.util.spec_from_file_location("ut_mix_read", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pilot_check(recipe: str, arm: str) -> tuple[int, dict]:
    rc, ra = recipe_arm(recipe, arm)
    s = seal(recipe, arm, "pilot")
    _, out, _, seed0, deals = span(ra, arm, "pilot")
    res = dict(schema="s160-pilot-check-r1", arm=arm, recipe_sha256=sha(recipe), checker_sha256=sha(HERE),
               reader_sha256=rc["reader_sha256"], seal=s)
    mt = mirror_teams(rows_of(out), seed0, deals)
    if mt:
        res.update(validity="DEV_INVALID", failing=[["mirror_teams", mt[:5]]])
        return 3, res
    rd = load_reader(rc)
    pa = dict(ra, seed0=seed0, deals=deals, out_root=str(out))
    va = rd.R.load_validity(rc["tree"])
    valid, checks, counts, by, ustat = rd.validate(pa, va)
    res.update(validity="VALID" if valid else "DEV_INVALID", failing=[[c["check"], c.get("reasons")] for c in checks if c["verdict"] != va.VALID],
               mirror_teams="ok", counts=counts, unified_prior=ustat, latency=rd.R.latency(by))
    return (0 if valid else 3), res


def read(recipe: str, arm: str, out: str) -> int:
    rc, ra = recipe_arm(recipe, arm)
    seal(recipe, arm, "duel")
    mt = mirror_teams(rows_of(Path(ra["out_root"])), ra["seed0"], ra["deals"])
    if mt:
        raise Refusal(f"mirror teams: {mt[:5]} ({len(mt)} deals); no outcome computed")
    return load_reader(rc).main(["--recipe", recipe, "--arm", arm, "--out", out])


def verify_pilot(recipe: str, arm: str, check: str) -> None:
    d = json.loads(Path(check).read_text())
    rc, _ = recipe_arm(recipe, arm)
    s = seal(recipe, arm, "pilot")
    want = dict(schema="s160-pilot-check-r1", arm=arm, recipe_sha256=sha(recipe), checker_sha256=sha(HERE),
                reader_sha256=rc["reader_sha256"], seal=s, validity="VALID", failing=[], mirror_teams="ok")
    bad = [k for k, v in want.items() if d.get(k) != v]
    if bad:
        raise Refusal(f"saved pilot check differs in {bad}")


def verify_read(recipe: str, arm: str, path: str) -> None:
    d = json.loads(Path(path).read_text())
    rc, ra = recipe_arm(recipe, arm)
    s = seal(recipe, arm, "duel")
    if sha(rc["reader"]) != rc["reader_sha256"]:
        raise Refusal("the reader is not the recipe's")
    b = d.get("binding") if isinstance(d.get("binding"), dict) else {}
    v = d.get("validity") if isinstance(d.get("validity"), dict) else {}
    checks = ((d.get("schema") == "utx-read-r1", "schema"), (d.get("arm") == arm, "arm"), (d.get("duel") == "UTX", "duel"),
              (d.get("reader_sha256") == rc["reader_sha256"], "reader"), (b.get("recipe_sha256") == sha(recipe), "recipe"),
              (b.get("sums_sha256") == s["sums_sha256"], "seal"), (b.get("duel_jsonl_sha256") == s["duel_jsonl_sha256"], "duel.jsonl"),
              (b.get("terminal") == s["terminal"], "terminal"), (v.get("verdict") == "VALID", "validity"),
              (isinstance(d.get("outcome"), dict) and isinstance(d["outcome"].get("levels"), dict), "outcome"))
    bad = [m for ok, m in checks if not ok]
    if bad:
        raise Refusal(f"saved read differs in {bad}")
    if mirror_teams(rows_of(Path(ra["out_root"])), ra["seed0"], ra["deals"]):
        raise Refusal("the sealed arm fails the mirror-team check")


def verify_attrib(recipe: str, path: str, attrib_py: Path = HERE.with_name("s160_attrib.py")) -> None:
    d = json.loads(Path(path).read_text())
    readout = Path(path).parent
    for arm in ("B4", "U4"):
        verify_read(recipe, arm, str(readout / f"{arm}.read.json"))
    want = dict(schema="s160-attrib-r1", attrib_sha256=sha(attrib_py), recipe_sha256=sha(recipe),
                reads={arm: sha(readout / f"{arm}.read.json") for arm in ("B4", "U4")})
    bad = [k for k, v in want.items() if d.get(k) != v]
    if bad or not isinstance(d.get("label"), str):
        raise Refusal(f"saved attribution differs in {bad or ['label']}")


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else ""
    try:
        a.pop(0)
        if cmd == "pilot-check":
            code, res = pilot_check(*a)
            print(json.dumps(res, default=str))
            return code
        if cmd == "read":
            return read(*a)
        if cmd == "verify-seal":
            seal(*a)
        elif cmd == "verify-pilot":
            verify_pilot(*a)
        elif cmd == "verify-read":
            verify_read(*a)
        elif cmd == "verify-attrib":
            verify_attrib(*a)
        else:
            print(f"unknown command {cmd}", file=sys.stderr)
            return 2
    except Refusal as exc:
        print(f"REFUSING: {exc}")
        return 3 if cmd in ("pilot-check", "read") else 1
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}")
        return 3 if cmd in ("pilot-check", "read") else 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
