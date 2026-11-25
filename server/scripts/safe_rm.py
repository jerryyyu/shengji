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
              A sha256 match is exempt (printed as EXEMPT) only in a linked worktree whose common dir and object
              stores (alternates included, no symlink anywhere in them) lie outside R, when the file is tracked at
              HEAD, byte-identical to HEAD's blob, `cat-file blob` in the common dir streams bytes with the pinned
              sha256, and a remote-tracking main/HEAD ref or local main holds it (same path, or the ref contains
              HEAD).  Standalone clones, untracked, ignored and modified files stay pinned.
              A sha256 match is also exempt (EXEMPT pin <sha12> vaulted at <path>) when the model vault
              (SAFE_RM_VAULT, default ~/model-vault; inert where absent) lists the sha in MANIFEST.sha256 and that
              copy is a regular file reached without symlinks, outside R, hashing to the pin when read now.  Never
              when R is inside the vault or the vault inside R.  Path pins are never exempt.
Checks run per path immediately before its delete, so a queued list is re-validated at delete time.
Every decision is appended to ~/.safe_rm.log.
"""
import glob, hashlib, os, re, shutil, stat, subprocess, sys, time

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


def _links_into(top, r, max_depth, hits, cap=None):
    """Append symlinks under top (not under r) that resolve into r; top is a realpath, links are never followed.
    DirEntry type bits come from the directory read, so only the links themselves cost a stat."""
    stack = [(top, 0)]
    while stack:
        d, depth = stack.pop()
        if under(d, r):
            continue
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    if e.name in SKIP and os.path.isdir(e.path):
                        continue
                    if not under(e.path, r) and under(os.path.realpath(e.path), r):
                        hits.append(e.path)
                        if cap and len(hits) >= cap:
                            return True
                elif e.is_dir() and e.name not in SKIP and (max_depth is None or depth < max_depth):
                    stack.append((e.path, depth + 1))
            except OSError:
                continue
    return False


def live_links(r):
    roots = os.environ.get("SAFE_RM_ROOTS", f"{home()}:/root").split(":")
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        rroot = os.path.realpath(root)
        _links_into(rroot, r, 4, hits)
        # the shallow scan above stops at depth 4; links from a sibling tree inside the same packet
        # (e.g. ~/shengji-archive/<packet>/views/*/shards/* -> <packet>/data/...) sit deeper, so the
        # target's own neighbourhood (root + its first two path components) is scanned without a depth cap
        if under(r, rroot) and r != rroot:
            parts = os.path.relpath(r, rroot).split(os.sep)
            hood = os.path.join(rroot, *parts[:2]) if len(parts) > 2 else None
            if hood and os.path.isdir(hood):
                found = []
                _links_into(hood, r, None, found, cap=50)
                hits += found
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
    matched = []
    for fp in walk:
        if not fp.endswith(PIN_EXT) or os.path.islink(fp):
            continue
        try:
            size = os.path.getsize(fp)
            if size < 1 << 20:
                continue
            h = hashlib.sha256()
            # git's raw blob ids, so a match can be compared with HEAD's tree without reading the file again
            b1, b256 = hashlib.sha1(b"blob %d\0" % size), hashlib.sha256(b"blob %d\0" % size)
            with open(fp, "rb") as fh:
                for b in iter(lambda: fh.read(1 << 22), b""):
                    h.update(b); b1.update(b); b256.update(b)
        except OSError:
            continue
        if h.hexdigest() in hexes:
            matched.append((fp, h.hexdigest(), {b1.hexdigest(), b256.hexdigest()}))
    recoverable = git_recoverable(r, matched)
    vault = Vault(r)
    exempt = []
    for fp, digest, _ in matched:
        line = f"{fp} sha256 {digest[:12]} pinned by {hexes[digest]}"
        if fp in recoverable:
            exempt.append(f"{line}: {recoverable[fp]}")
        elif vault.copy(digest):
            exempt.append(f"{digest[:12]} vaulted at {vault.copy(digest)} ({fp}, pinned by {hexes[digest]})")
        else:
            hits.append(line)
    return hits, exempt


def file_sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 22), b""):
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


class Vault:
    """The model vault (SAFE_RM_VAULT, default ~/model-vault): a sha256 pin on a file under R is satisfied by a
    vault copy that MANIFEST.sha256 lists under that sha, that is a regular file reached from the vault root with
    no symlink on the way, whose realpath is outside R, and whose bytes hash to the pin when read now.  Inert
    when the vault or its manifest is missing, and whenever R and the vault overlap in either direction."""

    def __init__(self, r):
        self.r, self.listed, self.verified = r, {}, {}
        root = os.path.abspath(os.path.expanduser(os.environ.get("SAFE_RM_VAULT", "~/model-vault")))
        self.root = root
        real = os.path.realpath(root)
        if os.path.islink(root) or not os.path.isdir(root) or under(real, r) or under(r, real):
            return
        manifest = os.path.join(root, "MANIFEST.sha256")
        if os.path.islink(manifest) or not os.path.isfile(manifest):
            return
        try:
            lines = open(manifest, errors="surrogateescape").read().splitlines()
        except OSError:
            return
        for line in lines:
            parts = line.split(None, 1)
            if len(parts) == 2 and HEX.fullmatch(parts[0]):
                self.listed.setdefault(parts[0], []).append(parts[1].strip().lstrip("*"))

    def clean(self, rel):
        """the vault path for a manifest entry, or None unless every component below the root is a real dir or
        file (no symlink, no '..') and the file is regular and outside R"""
        rel = os.path.normpath(rel)
        if os.path.isabs(rel) or rel == ".." or rel.startswith("../"):
            return None
        path = self.root
        for part in rel.split(os.sep):
            path = os.path.join(path, part)
            if os.path.islink(path):
                return None
        try:
            st = os.lstat(path)
        except OSError:
            return None
        if not stat.S_ISREG(st.st_mode) or under(os.path.realpath(path), self.r):
            return None
        return path

    def copy(self, digest):
        if digest not in self.verified:
            self.verified[digest] = None
            for rel in self.listed.get(digest, ()):
                path = self.clean(rel)
                if path and file_sha256(path) == digest:
                    self.verified[digest] = path
                    break
        return self.verified[digest]


def git(top, *args, git_dir=None):
    # inherited GIT_DIR / GIT_OBJECT_DIRECTORY / GIT_ALTERNATE_OBJECT_DIRECTORIES would point git at another store
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    loc = ["--git-dir", git_dir] if git_dir else ["-C", top]
    try:
        p = subprocess.run(["git", "--literal-pathspecs", *loc, *args], capture_output=True, timeout=120, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def object_stores(objects):
    """objects plus every alternate it names, transitively, as realpaths.  None (the pin stays) when an alternates
    file cannot be read, or any store, fanout dir, loose object, pack file or alternates file is a symlink: git
    would read through it, so the bytes may live in the target after all."""
    seen, todo = [], [objects]
    while todo:
        raw = os.path.abspath(todo.pop())
        if os.path.islink(raw):
            return None
        o = os.path.realpath(raw)
        if o in seen:
            continue
        seen.append(o)
        for d, dirs, files in os.walk(o, followlinks=False):
            if any(os.path.islink(os.path.join(d, n)) for n in dirs + files):
                return None
        alt = os.path.join(o, "info", "alternates")
        if not os.path.lexists(alt):
            continue
        try:
            lines = open(alt, errors="surrogateescape").read().splitlines()
        except OSError:
            return None
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith('"'):
                    return None
                todo.append(os.path.join(o, line))
    return seen


def blob_sha256(common, blob):
    """sha256 of the blob as git streams it from the common dir, or None when git cannot read it in full."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    h = hashlib.sha256()
    try:
        with subprocess.Popen(["git", "--git-dir", common, "cat-file", "blob", blob], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, env=env) as p:
            for b in iter(lambda: p.stdout.read(1 << 22), b""):
                h.update(b)
            rc = p.wait(timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return h.hexdigest() if rc == 0 else None


def git_recoverable(r, matched):
    """{path: reason} for hash-pinned files that git can restore after R is gone.  Only a linked worktree
    qualifies (its .git is a file naming a common dir); the common dir and every object store it reads, alternates
    included, lie outside R; the file is tracked at HEAD and byte-identical to HEAD's blob; that blob is readable
    there in full with the pinned sha256, no store path being a symlink; and a retained ref in the common dir
    (remote-tracking main/HEAD or local main at the same path, or a remote-tracking ref or local main containing
    HEAD) holds it.  A standalone clone keeps its pins: its
    remote may be inside R or no longer hold the commit.  Any git failure leaves the pin in force."""
    tops = {}
    for fp, digest, blob_ids in matched:
        out = git(os.path.dirname(fp), "rev-parse", "--show-toplevel", "--absolute-git-dir", "--git-common-dir",
                  "--git-path", "objects")
        if out is None:
            continue
        lines = out.decode(errors="surrogateescape").splitlines()
        if len(lines) != 4:
            continue
        d = os.path.dirname(fp)
        top, gdir, common = (os.path.realpath(os.path.join(d, x)) for x in lines[:3])
        objects = os.path.abspath(os.path.join(d, lines[3]))
        tops.setdefault((top, gdir, common, objects), []).append((fp, digest, blob_ids))
    found = {}
    for (top, gdir, common, objects), files in tops.items():
        if not os.path.isfile(os.path.join(top, ".git")) or gdir == common:
            continue
        stores = object_stores(objects)
        if not stores or under(common, r) or under(gdir, r) or any(under(o, r) for o in stores):
            continue
        rel = {os.path.relpath(fp, top): (fp, digest, ids) for fp, digest, ids in files}

        def tree(ref):
            out = git(top, "ls-tree", "-z", ref, "--", *rel)
            blobs = {}
            for rec in (out or b"").split(b"\0"):
                meta, _, path = rec.partition(b"\t")
                f = meta.split()
                if len(f) == 3 and f[1] == b"blob":
                    blobs[path.decode(errors="surrogateescape")] = f[2].decode()
            return blobs

        head = tree("HEAD")
        clean = {p: head[p] for p, (_, _, ids) in rel.items() if head.get(p) in ids}
        # a store that only answers cat-file -e may still hold a corrupt or substituted object
        clean = {p: b for p, b in clean.items() if blob_sha256(common, b) == rel[p][1]}
        if not clean:
            continue
        refs = (git(top, "for-each-ref", "--format=%(refname)", "refs/remotes/", "refs/heads/main") or b"").decode().split()
        mains = [x for x in refs if x == "refs/heads/main" or x.rsplit("/", 1)[-1] in ("main", "HEAD")]
        where = {}
        for ref in mains:
            for p, blob in tree(ref).items():
                if clean.get(p) == blob:
                    where.setdefault(p, ref)
        if len(where) < len(clean):
            on = git(top, "for-each-ref", "--count=1", "--contains", "HEAD", "--format=%(refname)",
                     "refs/remotes/", "refs/heads/main")
            on = (on or b"").decode().strip()
            if on:
                for p in clean:
                    where.setdefault(p, f"{on} (contains HEAD)")
        for p, ref in where.items():
            found[rel[p][0]] = f"linked worktree, tracked at HEAD, unmodified, blob {clean[p][:12]} readable in {common} on {ref}"
    return found


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
            pins, exempt = pinned(r, typed)
            reasons += [f"pinned {h}" for h in pins]
            reasons = list(dict.fromkeys(reasons))
            for x in exempt:
                print(f"safe_rm: EXEMPT pin {x}")
                log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} EXEMPT {typed} {x}\n")
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
