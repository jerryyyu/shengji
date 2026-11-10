#!/usr/bin/env python3
"""safe_rm.py -- the only way a cleanup deletes a directory or file on a fleet host.  Runs ON the host:
    safe_rm.py [--dry-run] PATH...                       (local)
    ssh HOST python3 - [--dry-run] PATH... < safe_rm.py  (remote; same checks, run where the files live)
exit: 0 every path deleted (or would be, with --dry-run) | 1 some path REFUSED (nothing else is skipped) | 2 usage

A path is REFUSED, with the reason printed, when any of these holds for it or its realpath R:
  protected   R is /, a top-level dir, $HOME, /root, or a parent of $HOME.
  live-link   a symlink outside R resolves into R (scanned under SAFE_RM_ROOTS, default $HOME and /root, depth 4,
              skipping Library, .Trash, .git, node_modules).  The KEEP lane python /root/gen-hybrid/server/.venv ->
              /root/ij-tree/server/.venv is this case.
  in-use      a running process has R (or the path as typed) in its command line, or its cwd/exe under R.
  referenced  an installed launcher, waiter or crontab names R, the typed path, or a live-link into R
              (globs in SAFE_RM_LAUNCHERS, default ~/fleet/*.sh ~/fleet/*/*.sh ~/claude_*.sh /root/claude_*.sh
              /root/fleet/*.sh /root/fleet/*/*.sh, plus `crontab -l`).
  kept        R is listed in ~/.safe_rm.keep (one path per line, # comments; SAFE_RM_KEEP overrides the file), is
              under a listed path, or contains one.  For stores read by archived scripts that no launcher names
              (e.g. ~/perf-archive/root/train-out, the JS-M1 checkpoint every seed clear reads).
  pinned      an archived packet names R or the typed path (absolute, or as ~/, $HOME/ or ${HOME}/ when under $HOME), or pins by sha256 a model/data file (>= 1 MB; .pt .npz .ckpt
              .safetensors .bin .npy .jsonl .tar) under R.  Pin files are SAFE_RM_PINS globs (default ~/shengji-archive/*/
              {commands.json,slots*.json,source-pins.json,SHA256SUMS,stage_*.sh,launch.py,*.sh} and the same names under
              ~/fleet/*/), skipping pin files inside R itself.  INC-23: ~/mrt-b0 held FT1 best.pt, pinned by G5 and X2.
Checks run per path immediately before its delete, so a queued list is re-validated at delete time.
Every decision is appended to ~/.safe_rm.log.
"""
import glob, hashlib, os, re, shutil, subprocess, sys, time

SKIP = {"Library", ".Trash", ".git", "node_modules", "__pycache__", ".cache"}


def under(p, root):
    return p == root or p.startswith(root.rstrip("/") + "/")


def home():
    return os.path.realpath(os.path.expanduser("~"))


def protected(r):
    h = home()
    return r in ("/", "/root", h) or r.count("/") < 2 or under(h, r)


def kept(r):
    f = os.environ.get("SAFE_RM_KEEP", os.path.expanduser("~/.safe_rm.keep"))
    if not os.path.isfile(f):
        return []
    hits = []
    for line in open(f):
        k = line.split("#", 1)[0].strip()
        if not k:
            continue
        kr = os.path.realpath(os.path.expanduser(k))
        if kr == r or under(kr, r) or under(r, kr):
            hits.append(kr)
    return hits


def live_links(r):
    roots = os.environ.get("SAFE_RM_ROOTS", f"{home()}:/root").split(":")
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base = root.rstrip("/").count("/")
        for d, dirs, files in os.walk(root, followlinks=False):
            if under(os.path.realpath(d), r):
                dirs[:] = []
                continue
            depth = d.rstrip("/").count("/") - base
            dirs[:] = [x for x in dirs if x not in SKIP and depth < 4]
            for n in dirs + files:
                p = os.path.join(d, n)
                if os.path.islink(p) and not under(p, r) and under(os.path.realpath(p), r):
                    hits.append(p)
            for n in list(dirs):
                if os.path.islink(os.path.join(d, n)):
                    dirs.remove(n)
        # the shallow scan above stops at depth 4; links from a sibling tree inside the same packet
        # (e.g. ~/shengji-archive/<packet>/views/*/shards/* -> <packet>/data/...) sit deeper, so the
        # target's own neighbourhood (root + its first two path components) is scanned without a depth cap
        rroot = os.path.realpath(root)
        if under(r, rroot) and r != rroot:
            parts = os.path.relpath(r, rroot).split(os.sep)
            hood = os.path.join(rroot, *parts[:2]) if len(parts) > 2 else None
            if hood and os.path.isdir(hood):
                for d, dirs, files in os.walk(hood, followlinks=False):
                    if under(os.path.realpath(d), r):
                        dirs[:] = []
                        continue
                    dirs[:] = [x for x in dirs if x not in SKIP]
                    for n in dirs + files:
                        p = os.path.join(d, n)
                        if os.path.islink(p) and not under(p, r) and under(os.path.realpath(p), r):
                            hits.append(p)
                            if len(hits) >= 50:
                                return list(dict.fromkeys(hits))
                    for n in list(dirs):
                        if os.path.islink(os.path.join(d, n)):
                            dirs.remove(n)
    return list(dict.fromkeys(hits))


def process_inventory(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"inventory unavailable ({command[0]}: {type(exc).__name__})"
    if result.returncode != 0:
        return None, f"inventory unavailable ({command[0]} rc={result.returncode})"
    if not result.stdout.strip():
        return None, f"inventory unavailable ({command[0]} empty output)"
    return result.stdout, None


def proc_owner(pd):
    try:
        return os.stat(pd).st_uid
    except OSError:
        return None


def in_use(r, typed):
    hits = []
    ps, error = process_inventory(["ps", "-axww", "-o", "pid=,ppid=,command="])
    if error:
        return [error]
    me = str(os.getpid())
    rows = []
    for line in ps.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit() or not fields[2].strip():
            return ["inventory unavailable (ps malformed output)"]
        rows.append((fields[0], fields[1], fields[2]))
    parent = {pid: ppid for pid, ppid, _ in rows}
    if me not in parent:
        return ["inventory unavailable (ps omitted current process)"]
    # The shells that launched this run carry the target path in their own argv; only this process's ancestor
    # chain is exempt, never another process that merely mentions safe_rm.
    launchers = set()
    pid = me
    while pid in parent and pid not in launchers and pid != "0":
        launchers.add(pid)
        pid = parent[pid]
    for pid, _, cmd in rows:
        if pid in launchers:
            continue
        if r in cmd or typed in cmd:
            hits.append(f"pid {pid}: {cmd[:120]}")
    if os.path.isdir("/proc"):
        for pd in glob.glob("/proc/[0-9]*"):
            for k in ("cwd", "exe"):
                try:
                    target = os.readlink(os.path.join(pd, k))
                    if under(os.path.realpath(target), r):
                        hits.append(f"pid {os.path.basename(pd)} {k} under R")
                except (FileNotFoundError, ProcessLookupError):
                    # Exited processes and kernel threads have no cwd/exe link.
                    continue
                except PermissionError as exc:
                    # Another user's process cannot be inspected without root; its argv is still checked
                    # above. An unreadable process of this user (or anything, as root) is not trusted.
                    if os.geteuid() != 0 and proc_owner(pd) not in (None, os.geteuid()):
                        continue
                    hits.append(f"inventory unavailable ({pd}/{k}: {type(exc).__name__})")
                except OSError as exc:
                    hits.append(f"inventory unavailable ({pd}/{k}: {type(exc).__name__})")
    else:
        out, error = process_inventory(["lsof", "-a", "-d", "cwd,txt", "-Fn"])
        if error:
            return hits + [error]
        names = [line[1:] for line in out.splitlines() if line.startswith("n")]
        if not names:
            return hits + ["inventory unavailable (lsof missing file records)"]
        hits += [f"lsof {name}" for name in names if under(name, r)][:5]
    return hits


def referenced(r, typed, links):
    globs = os.environ.get("SAFE_RM_LAUNCHERS",
                           "~/fleet/*.sh ~/fleet/*/*.sh ~/claude_*.sh /root/claude_*.sh /root/fleet/*.sh /root/fleet/*/*.sh").split()
    needles = {r, typed.rstrip("/")} | set(links)
    hits = []
    for g in globs:
        for f in glob.glob(os.path.expanduser(g)):
            try:
                text = open(f, errors="replace").read()
            except OSError:
                continue
            for n in needles:
                if n and n in text:
                    hits.append(f"{f} names {n}")
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        hits += [f"crontab names {n}" for n in needles if n and n in cron]
    except OSError:
        pass
    return hits


PIN_GLOBS = ("~/shengji-archive/*/commands.json ~/shengji-archive/*/slots*.json ~/shengji-archive/*/source-pins.json "
             "~/shengji-archive/*/SHA256SUMS ~/shengji-archive/*/stage_*.sh ~/shengji-archive/*/launch.py "
             "~/shengji-archive/*/*.sh ~/fleet/*/commands.json ~/fleet/*/slots*.json ~/fleet/*/source-pins.json "
             "~/fleet/*/SHA256SUMS ~/fleet/*/launch.py")
PIN_EXT = (".pt", ".npz", ".ckpt", ".safetensors", ".bin", ".npy", ".jsonl", ".tar")
HEX = re.compile(r"\b[0-9a-f]{64}\b")


def pin_files():
    out = set()
    for g in os.environ.get("SAFE_RM_PINS", PIN_GLOBS).split():
        out.update(glob.glob(os.path.expanduser(g)))
    return sorted(out)


def pinned(r, typed):
    texts = []
    for f in pin_files():
        if under(os.path.realpath(f), r):
            continue
        try:
            texts.append((f, open(f, errors="replace").read()))
        except OSError:
            pass
    hits = []
    needles = {r, typed.rstrip("/")}
    for n in list(needles):
        # a packet may name the target home-relatively: ~/x, $HOME/x or ${HOME}/x
        h = home()
        if n and under(n, h) and n != h:
            rel = os.path.relpath(n, h)
            needles |= {"~/" + rel, "$HOME/" + rel, "${HOME}/" + rel}
    for f, t in texts:
        for n in needles:
            if n and (n + "/" in t or n + '"' in t or n + "'" in t or n + " " in t or n + "\n" in t):
                hits.append(f"{f} names {n}")
    hexes = {}
    for f, t in texts:
        for h in HEX.findall(t):
            hexes.setdefault(h, f)
    walk = [r] if os.path.isfile(r) else []
    if os.path.isdir(r):
        for d, dirs, files in os.walk(r):
            dirs[:] = [x for x in dirs if x not in SKIP]
            walk += [os.path.join(d, x) for x in files]
    for fp in walk:
        if not fp.endswith(PIN_EXT) or os.path.islink(fp):
            continue
        try:
            if os.path.getsize(fp) < 1 << 20:
                continue
            h = hashlib.sha256()
            with open(fp, "rb") as fh:
                for b in iter(lambda: fh.read(1 << 22), b""):
                    h.update(b)
        except OSError:
            continue
        if h.hexdigest() in hexes:
            hits.append(f"{fp} sha256 {h.hexdigest()[:12]} pinned by {hexes[h.hexdigest()]}")
    return hits


def main(argv):
    dry = "--dry-run" in argv
    paths = [a for a in argv if a != "--dry-run"]
    if not paths or any(a.startswith("-") for a in paths):
        sys.stderr.write(__doc__); return 2
    log = open(os.path.expanduser("~/.safe_rm.log"), "a")
    refused = 0
    for typed in paths:
        if not os.path.lexists(typed):
            print(f"safe_rm: ABSENT {typed}"); continue
        r = os.path.realpath(typed)
        reasons = []
        if protected(r):
            reasons.append(f"protected path {r}")
        else:
            reasons += [f"kept {k} (listed in the keep file)" for k in kept(r)]
            links = live_links(r)
            reasons += [f"live-link {l} -> {os.path.realpath(l)}" for l in links]
            reasons += [f"in-use {h}" for h in in_use(r, typed)]
            reasons += [f"referenced {h}" for h in referenced(r, typed, links)]
            reasons += [f"pinned {h}" for h in pinned(r, typed)]
            reasons = list(dict.fromkeys(reasons))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if reasons:
            refused += 1
            print(f"safe_rm: REFUSED {typed} (R={r})")
            for x in reasons[:12]:
                print(f"  - {x}")
            log.write(f"{stamp} REFUSED {typed} R={r} {reasons[:3]}\n")
            continue
        if dry:
            print(f"safe_rm: WOULD DELETE {typed} (R={r})"); log.write(f"{stamp} DRYRUN {typed}\n"); continue
        try:
            if os.path.islink(typed) or os.path.isfile(typed):
                os.unlink(typed)
            else:
                # read-only files inside our own trees (e.g. chmod a-w witnesses) must not abort the whole list
                def _chmod_retry(fn, path, exc):
                    os.chmod(os.path.dirname(path), 0o700)
                    if os.path.lexists(path) and not os.path.islink(path):
                        os.chmod(path, 0o700)
                    fn(path)
                shutil.rmtree(typed, onerror=_chmod_retry)
        except OSError as e:
            refused += 1
            print(f"safe_rm: FAILED {typed} ({e}); continuing")
            log.write(f"{stamp} FAILED {typed} R={r} {e}\n")
            continue
        print(f"safe_rm: DELETED {typed}"); log.write(f"{stamp} DELETED {typed} R={r}\n")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
