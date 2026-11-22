"""S158A supervisor: W capture workers over [SEED0, SEED0+N) by stride, resumable (a worker skips finished
deal files). Writes OUT/status.json every 30 s and appends OUT/status.log; terminal line 'RUN DONE' or
'RUN ABORT <reason>'. Stops (terminating only the worker Popen objects it started) when free disk drops
under MIN_FREE_GIB or the projected output exceeds MAX_OUT_GIB.

usage: run.py SEED0 N OUT WORKERS [--plain] [--selftest M]
"""
import json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(os.path.dirname(HERE)), "server")
PY = "/Users/jerryyu/Projects/shengji/server/.venv/bin/python"
MIN_FREE_GIB, MAX_OUT_GIB = 10.0, 5.0


def out_bytes(out):
    return sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out) if f.endswith(".json")
               and f[0].isdigit())


def main():
    a = sys.argv[1:]
    seed0, n, out, workers = int(a[0]), int(a[1]), a[2], int(a[3])
    extra = a[4:]
    os.makedirs(out, exist_ok=True)
    log = open(os.path.join(out, "status.log"), "a")
    def say(msg):
        log.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg + "\n"); log.flush()
    done0 = sum(os.path.exists(os.path.join(out, f"{s}.json")) for s in range(seed0, seed0 + n))
    say(f"RUN START pid {os.getpid()} seeds [{seed0},{seed0 + n}) workers {workers} already done {done0} extra {extra}")
    procs = []
    env = dict(os.environ, PYTHONPATH=".")
    for k in range(workers):
        lf = open(os.path.join(out, f"worker{k}.log"), "a")
        p = subprocess.Popen([PY, os.path.join(HERE, "capture.py"), str(seed0), str(n), out,
                              "--stride", str(workers), "--offset", str(k), *extra],
                             cwd=SERVER, env=env, stdout=lf, stderr=subprocess.STDOUT)
        procs.append(p)
    say("workers " + " ".join(str(p.pid) for p in procs))
    t0 = time.time(); reason = None
    while True:
        alive = [p for p in procs if p.poll() is None]
        done = sum(os.path.exists(os.path.join(out, f"{s}.json")) for s in range(seed0, seed0 + n))
        new = done - done0; el = time.time() - t0
        rate = new / el if el > 0 else 0.0
        eta_h = (n - done) / rate / 3600 if rate > 0 else None
        ob = out_bytes(out)
        proj_gib = ob / max(done, 1) * n / 2**30 if done else 0.0
        free_gib = shutil.disk_usage(out).free / 2**30
        st = dict(pid=os.getpid(), workers=[p.pid for p in procs], alive=len(alive), done=done, n=n,
                  elapsed_h=round(el / 3600, 3), deals_per_h=round(rate * 3600, 1),
                  eta_h=None if eta_h is None else round(eta_h, 2), out_mib=round(ob / 2**20, 1),
                  projected_gib=round(proj_gib, 3), free_gib=round(free_gib, 1),
                  updated=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        tmp = os.path.join(out, "status.json.tmp")
        with open(tmp, "w") as f: json.dump(st, f)
        os.replace(tmp, os.path.join(out, "status.json"))
        if free_gib < MIN_FREE_GIB: reason = f"free disk {free_gib:.1f} GiB < {MIN_FREE_GIB}"
        elif done >= 20 and proj_gib > MAX_OUT_GIB: reason = f"projected output {proj_gib:.2f} GiB > {MAX_OUT_GIB}"
        if reason or not alive: break
        time.sleep(30)
    if reason:
        for p in procs:
            if p.poll() is None: p.terminate()
        for p in procs:
            try: p.wait(timeout=60)
            except subprocess.TimeoutExpired: p.kill()
        say(f"RUN ABORT {reason}")
        return 1
    rcs = [p.returncode for p in procs]
    done = sum(os.path.exists(os.path.join(out, f"{s}.json")) for s in range(seed0, seed0 + n))
    if any(rcs) or done != n:
        say(f"RUN ABORT worker rcs {rcs} done {done}/{n}")
        return 1
    say(f"RUN DONE {done}/{n} deals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
