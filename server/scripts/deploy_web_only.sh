#!/usr/bin/env bash
# Web-only Fly deploy: the served release's tree with only web/ taken from a newer ref.
#
# Usage:
#   server/scripts/deploy_web_only.sh --served-sha <sha> [--web-ref origin/main]
#       [--branch name] [--worktree dir] [--marker text] [--receipt file]
#       [--app shengji] [--url https://shengji.fly.dev] [--repo dir] [--dry-run]
#
# Steps: build a worktree at the served commit, replace web/ with the web ref's web/,
# commit; refuse unless every path outside web/ is byte-identical to the served commit
# and web/ is identical to the web ref; refuse on a dirty worktree; read /healthz and
# refuse unless rooms == 0; push the branch; fly deploy --ha=false; re-read /healthz and
# refuse (printing the rollback command, never running it) if the bot identity changed;
# require exactly one started machine; with --marker, build web/ of the deploy tree
# locally, refuse before the push unless the marker is in that build's JS, and after
# the deploy require the served index.html to equal the local build's byte for byte
# and the local asset carrying the marker to be served at its URL as JavaScript with
# the local bytes.
# --dry-run runs every step except the push and fly deploy.
# A JSON receipt records the tree, served and web shas, /healthz and the Fly version
# before and after, and the outcome.
#
# Sourcing this file defines the functions without running main, so tests can call
# build_deploy_tree, check_deploy_tree and check_clean_worktree on a scratch repo.
set -euo pipefail

APP=shengji
URL=https://shengji.fly.dev
SERVED_SHA=
WEB_REF=origin/main
BRANCH=
WORKTREE=
MARKER=
RECEIPT=
REPO=
DRY_RUN=0
HEALTHZ_WAIT=${DEPLOY_WEB_HEALTHZ_WAIT:-180}

STATUS=started
TREE_SHA=
DEPLOY_SHA=
WEB_SHA=
HEALTHZ_BEFORE=null
HEALTHZ_AFTER=null
FLY_VERSION_BEFORE=null
FLY_VERSION_AFTER=null
FLY_IMAGE_BEFORE=
FLY_IMAGE_AFTER=
STARTED_MACHINES=null
BUNDLES_BEFORE=
BUNDLES_AFTER=
MARKER_FOUND=null
MARKER_ASSET=
MARKER_DETAIL=
LOCAL_DIST=
LOCAL_ENTRIES=
SERVED_ENTRIES=
ROLLBACK_CMD=
PUSHED=0
DEPLOYED=0

say() { printf 'deploy_web_only: %s\n' "$*" >&2; }

usage() {
  sed -n '3,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
}

refuse() {
  STATUS="refused: $*"
  say "REFUSING: $*"
  write_receipt
  exit 1
}

# build_deploy_tree REPO SERVED_SHA WEB_SHA WORKTREE BRANCH
# Creates WORKTREE on a new BRANCH at SERVED_SHA and replaces web/ with WEB_SHA's web/
# (files removed upstream are removed here too), then commits. Prints the commit sha.
build_deploy_tree() {
  local repo=$1 served=$2 web=$3 wt=$4 branch=$5
  if [ -e "$wt" ]; then
    say "worktree path already exists: $wt"
    return 1
  fi
  if git -C "$repo" rev-parse -q --verify "refs/heads/$branch" >/dev/null; then
    say "branch already exists: $branch"
    return 1
  fi
  git -C "$repo" worktree add -q -b "$branch" "$wt" "$served" >&2
  git -C "$wt" rm -r -q --ignore-unmatch -- web >&2
  git -C "$wt" checkout "$web" -- web >&2
  if git -C "$wt" diff --cached --quiet; then
    say "web/ at $web is already identical to the served commit; nothing to deploy"
    return 1
  fi
  git -C "$wt" commit -q -m "Web-only deploy tree: served $served with web/ from $web" >&2
  git -C "$wt" rev-parse HEAD
}

# check_deploy_tree REPO DEPLOY_SHA SERVED_SHA WEB_SHA
# Succeeds only when every root entry except web/ has the served commit's object id,
# web/ has the web ref's tree id, and the deploy commit's parent is the served commit.
check_deploy_tree() {
  local repo=$1 deploy=$2 served=$3 web=$4 differ
  differ=$(git -C "$repo" diff --name-only "$served" "$deploy" -- . ':(exclude)web')
  if [ -n "$differ" ]; then
    say "paths outside web/ differ from the served commit:"
    printf '  %s\n' $differ >&2
    return 1
  fi
  local a b
  a=$(git -C "$repo" ls-tree "$served" | awk -F'\t' '$2 != "web"')
  b=$(git -C "$repo" ls-tree "$deploy" | awk -F'\t' '$2 != "web"')
  if [ "$a" != "$b" ]; then
    say "root entries outside web/ differ from the served commit"
    return 1
  fi
  if [ "$(git -C "$repo" rev-parse "$deploy:web")" != "$(git -C "$repo" rev-parse "$web:web")" ]; then
    say "web/ differs from the web ref:"
    git -C "$repo" diff --name-only "$web" "$deploy" -- web >&2
    return 1
  fi
  if [ "$(git -C "$repo" rev-parse "$deploy^")" != "$(git -C "$repo" rev-parse "$served^{commit}")" ]; then
    say "deploy commit's parent is not the served commit"
    return 1
  fi
}

# check_clean_worktree DIR: no staged, unstaged, untracked or ignored files.
check_clean_worktree() {
  local dirty
  dirty=$(git -C "$1" status --porcelain --ignored --untracked-files=all)
  if [ -n "$dirty" ]; then
    say "worktree is dirty:"
    printf '%s\n' "$dirty" >&2
    return 1
  fi
}

# healthz_identity JSON: the fields a web-only deploy must leave unchanged.
healthz_identity() {
  python3 -c '
import json, math, re, sys
h = json.loads(sys.argv[1])
def require(condition, message):
    if not condition:
        raise ValueError(message)
def integer(value, minimum):
    return type(value) is int and value >= minimum
require(isinstance(h, dict), "health must be an object")
require(h.get("ok") is True and h.get("fast") is True, "healthy compiled engine required")
require(isinstance(h.get("bot"), str) and h["bot"].startswith("pv-search-") and len(h["bot"]) > 10, "pv-search bot identity required")
require(integer(h.get("rooms"), 0), "rooms must be a nonnegative integer")
if sys.argv[2] == "before":
    require(h["rooms"] == 0, "rooms = %s (need 0)" % h["rooms"])
for key in ("prior", "pv_search"):
    package = h.get(key)
    require(isinstance(package, dict) and "error" not in package, key + " package required")
    require(isinstance(package.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", package["sha256"]), key + " full sha256 required")
for key, fields in (("prior", ("threshold", "top")), ("pv_search", ("worlds", "candidates"))):
    for field in fields:
        require(integer(h[key].get(field), 1), key + "." + field + " must be positive integer")
pv = h["pv_search"]
require(isinstance(pv.get("bury_arm"), str) and bool(pv["bury_arm"].strip()), "bury_arm required")
for key in ("budget_seconds", "bury_budget_seconds"):
    require(key in pv, key + " required")
    value = pv[key]
    if value is not None:
        require(type(value) in (str, int, float), key + " must be numeric or null")
        require(math.isfinite(float(value)) and float(value) > 0, key + " must be finite and positive")
require(isinstance(pv.get("latency_switches"), dict) and bool(pv["latency_switches"]), "latency_switches required")
require(all(type(v) is bool for v in pv["latency_switches"].values()), "latency switches must be boolean")
print(json.dumps({k: h[k] for k in ("bot", "fast", "prior", "pv_search")}, sort_keys=True))
' "$1" "${2:-after}"
}

# Preserve the supplied served tree configuration independently of the deploy worktree.
prepare_rollback() {
  python3 - "$REPO" "$SERVED_SHA" "$RECEIPT" "$APP" "$FLY_IMAGE_BEFORE" <<'PYROLLBACK'
import os, pathlib, shlex, subprocess, sys
repo, served, receipt, app, image = sys.argv[1:]
if not image.strip():
    raise ValueError("previous image is unavailable")
config = subprocess.run(["git", "-C", repo, "show", served + ":fly.toml"],
                        check=True, capture_output=True).stdout
if not config.strip():
    raise ValueError("served fly.toml is empty")
path = pathlib.Path(receipt).absolute().with_name(pathlib.Path(receipt).name + ".rollback.fly.toml")
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("xb") as handle:
    handle.write(config)
    handle.flush()
    os.fsync(handle.fileno())
path.chmod(0o444)
print(shlex.join(["fly", "deploy", "--app", app, "--ha=false", "--image", image,
                  "--config", str(path)]))
PYROLLBACK
}

fetch_healthz() {
  curl -fsS --max-time 20 "$URL/healthz"
}

# Prints "<version> <image>" of the newest Fly release.
fly_release() {
  fly releases -a "$APP" --image --json | python3 -c '
import json, sys
rows = json.load(sys.stdin)
def pick(r, *keys):
    for k in keys:
        if r.get(k) not in (None, ""):
            return r[k]
    return None
rows = [r for r in rows if pick(r, "Version", "version") is not None]
top = max(rows, key=lambda r: int(pick(r, "Version", "version")))
print(int(pick(top, "Version", "version")), pick(top, "ImageRef", "imageRef", "image_ref", "Image", "image") or "")
'
}

started_machines() {
  fly machines list -a "$APP" --json | python3 -c '
import json, sys
print(sum(1 for m in json.load(sys.stdin) if (m.get("state") or m.get("State")) == "started"))
'
}

# Prints the /assets/*.js paths the served index.html loads, one per line.
served_bundles() {
  curl -fsS --max-time 20 "$URL/" | grep -o -E '/assets/[A-Za-z0-9._-]+\.js' | sort -u
}

# entry_refs < INDEX_HTML: the /assets/*.js and /assets/*.css files an index.html
# names, sorted, one per line.
entry_refs() {
  grep -o -E '/assets/[A-Za-z0-9._-]+\.(js|css)' | sort -u
}

served_entries() {
  curl -fsS --max-time 20 "$URL/" | entry_refs
}

# build_local_web WORKTREE: builds web/ of WORKTREE's HEAD the way the Dockerfile does
# (npm ci, npm run build) in a fresh export, leaving WORKTREE untouched, with the
# build-switch variables vite.config reads unset as they are in the image build.
# Prints the dist directory.
build_local_web() {
  local out tmp=${TMPDIR:-/tmp}
  out=$(mktemp -d "${tmp%/}/deploy-web-build.XXXXXX") || return 1
  git -C "$1" archive HEAD web | tar -x -C "$out" || return 1
  (
    cd "$out/web" || exit 1
    for v in $(compgen -e); do
      case "$v" in VITE_*|SHENGJI_NEARBY_*|NODE_ENV) unset "$v" ;; esac
    done
    npm ci --no-audit --no-fund >&2 && npm run build >&2
  ) || return 1
  [ -f "$out/web/dist/index.html" ] || return 1
  # keep the built dist (the receipt names it), not the installed dependencies
  if [ -d "$out/web/node_modules" ]; then
    python3 "$(dirname "${BASH_SOURCE[0]}")/safe_rm.py" "$out/web/node_modules" >&2 \
      || say "could not remove $out/web/node_modules"
  fi
  printf '%s\n' "$out/web/dist"
}

# marker_asset DIST: the first JS file of the local build (by name) that contains the
# marker, as /assets/<name>; nothing when none does. Every file in dist/assets is an
# output of the build's module graph.
marker_asset() {
  local f
  for f in "$1"/assets/*.js; do
    [ -f "$f" ] || continue
    if grep -qF -- "$MARKER" "$f"; then
      printf '/assets/%s\n' "${f##*/}"
      return 0
    fi
  done
  return 1
}

marker_in_build() {
  marker_asset "$1" >/dev/null
}

# marker_served: the deploy serves the local build's bytes. The served index.html is
# byte-identical to the local dist/index.html (Vite's output is deterministic; it
# names the content-hashed entries and their preloads), and the local asset that
# carries the marker is served at its exact URL with HTTP 200, a JavaScript content
# type and the local bytes. Sets MARKER_DETAIL to the reason on failure.
marker_served() {
  local tmp code type
  MARKER_DETAIL=
  if [ -z "$LOCAL_DIST" ] || [ -z "${LOCAL_ENTRIES// /}" ]; then
    MARKER_DETAIL="the local build names no /assets entry"; return 1
  fi
  MARKER_ASSET=$(marker_asset "$LOCAL_DIST") || { MARKER_DETAIL="no local asset contains the marker"; return 1; }
  tmp=${TMPDIR:-/tmp}
  tmp=$(mktemp "${tmp%/}/deploy-web-served.XXXXXX") || return 1
  if ! curl -fsS --max-time 20 -o "$tmp" "$URL/"; then
    rm -f "$tmp"; MARKER_DETAIL="could not read $URL/"; return 1
  fi
  SERVED_ENTRIES=$(entry_refs < "$tmp" | tr '\n' ' ' || true)
  if ! cmp -s "$tmp" "$LOCAL_DIST/index.html"; then
    rm -f "$tmp"; MARKER_DETAIL="the served index.html differs from the local build's"; return 1
  fi
  read -r code type < <(curl -sS --max-time 30 -o "$tmp" -w '%{http_code} %{content_type}\n' "$URL$MARKER_ASSET" || echo "000 none")
  if [ "$code" != 200 ]; then
    rm -f "$tmp"; MARKER_DETAIL="$URL$MARKER_ASSET returned HTTP $code"; return 1
  fi
  case "$type" in
    text/javascript*|application/javascript*) ;;
    *) rm -f "$tmp"; MARKER_DETAIL="$URL$MARKER_ASSET is served as ${type:-no content type}, not JavaScript"; return 1 ;;
  esac
  if ! cmp -s "$tmp" "$LOCAL_DIST$MARKER_ASSET"; then
    rm -f "$tmp"; MARKER_DETAIL="$URL$MARKER_ASSET differs from the local build's bytes"; return 1
  fi
  rm -f "$tmp"
}

write_receipt() {
  [ -n "$RECEIPT" ] || return 0
  mkdir -p "$(dirname "$RECEIPT")"
  R_STATUS=$STATUS R_TREE=$TREE_SHA R_DEPLOY=$DEPLOY_SHA R_SERVED=$SERVED_SHA \
  R_WEB_REF=$WEB_REF R_WEB=$WEB_SHA R_BRANCH=$BRANCH R_WT=$WORKTREE R_APP=$APP R_URL=$URL \
  R_DRY=$DRY_RUN R_HB=$HEALTHZ_BEFORE R_HA=$HEALTHZ_AFTER R_VB=$FLY_VERSION_BEFORE \
  R_VA=$FLY_VERSION_AFTER R_IB=$FLY_IMAGE_BEFORE R_IA=$FLY_IMAGE_AFTER R_SM=$STARTED_MACHINES \
  R_BB=$BUNDLES_BEFORE R_BA=$BUNDLES_AFTER R_MARKER=$MARKER R_MF=$MARKER_FOUND \
  R_LD=$LOCAL_DIST R_LE=$LOCAL_ENTRIES R_SE=$SERVED_ENTRIES \
  R_MA=$MARKER_ASSET R_MD=$MARKER_DETAIL \
  R_ROLLBACK=$ROLLBACK_CMD R_PUSHED=$PUSHED R_DEPLOYED=$DEPLOYED \
  python3 - "$RECEIPT" <<'PY'
import json, os, sys, datetime
e = os.environ
def js(key):
    v = e.get(key, "null")
    try:
        return json.loads(v)
    except ValueError:
        return v
receipt = {
    "status": e["R_STATUS"],
    "written_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "dry_run": e["R_DRY"] == "1",
    "app": e["R_APP"], "url": e["R_URL"],
    "served_sha": e["R_SERVED"], "web_ref": e["R_WEB_REF"], "web_ref_sha": e["R_WEB"],
    "deploy_commit": e["R_DEPLOY"], "tree_sha": e["R_TREE"],
    "branch": e["R_BRANCH"], "worktree": e["R_WT"],
    "pushed": e["R_PUSHED"] == "1", "fly_deploy_ran": e["R_DEPLOYED"] == "1",
    "healthz_before": js("R_HB"), "healthz_after": js("R_HA"),
    "fly_version_before": js("R_VB"), "fly_version_after": js("R_VA"),
    "fly_image_before": e["R_IB"] or None, "fly_image_after": e["R_IA"] or None,
    "started_machines": js("R_SM"),
    "bundles_before": e["R_BB"].split(), "bundles_after": e["R_BA"].split(),
    "marker": e["R_MARKER"] or None, "marker_found": js("R_MF"),
    "local_build": e["R_LD"] or None,
    "local_entries": e["R_LE"].split(), "served_entries": e["R_SE"].split(),
    "marker_asset": e["R_MA"] or None, "marker_detail": e["R_MD"] or None,
    "rollback_command": e["R_ROLLBACK"] or None,
}
with open(sys.argv[1], "w") as f:
    json.dump(receipt, f, indent=2, sort_keys=True)
    f.write("\n")
PY
  say "receipt: $RECEIPT"
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --served-sha) SERVED_SHA=$2; shift 2 ;;
      --web-ref) WEB_REF=$2; shift 2 ;;
      --branch) BRANCH=$2; shift 2 ;;
      --worktree) WORKTREE=$2; shift 2 ;;
      --marker) MARKER=$2; shift 2 ;;
      --receipt) RECEIPT=$2; shift 2 ;;
      --app) APP=$2; shift 2 ;;
      --url) URL=${2%/}; shift 2 ;;
      --repo) REPO=$2; shift 2 ;;
      --dry-run) DRY_RUN=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) usage; say "unknown argument: $1"; exit 2 ;;
    esac
  done
  [ -n "$SERVED_SHA" ] || { usage; say "--served-sha is required"; exit 2; }
  if [ "$DRY_RUN" = 0 ] && [ -z "$MARKER" ]; then
    say "--marker is required for a real deploy (text that only the new web build contains)"
    exit 2
  fi
  [ -n "$REPO" ] || REPO=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)

  git -C "$REPO" fetch -q origin
  SERVED_SHA=$(git -C "$REPO" rev-parse --verify "$SERVED_SHA^{commit}")
  WEB_SHA=$(git -C "$REPO" rev-parse --verify "$WEB_REF^{commit}")
  [ -n "$BRANCH" ] || BRANCH="claude/deploy-web-${SERVED_SHA:0:8}-${WEB_SHA:0:8}"
  [ -n "$WORKTREE" ] || WORKTREE="$HOME/Projects/shengji-wt/claude-deploy-web-${SERVED_SHA:0:8}-${WEB_SHA:0:8}"
  [ -n "$RECEIPT" ] || RECEIPT="$HOME/shengji-archive/deploy-web/$(date -u +%Y%m%dT%H%M%SZ)-${SERVED_SHA:0:8}-${WEB_SHA:0:8}.json"
  say "served $SERVED_SHA, web/ from $WEB_REF = $WEB_SHA"

  DEPLOY_SHA=$(build_deploy_tree "$REPO" "$SERVED_SHA" "$WEB_SHA" "$WORKTREE" "$BRANCH") \
    || refuse "could not build the deploy tree"
  TREE_SHA=$(git -C "$WORKTREE" rev-parse "HEAD^{tree}")
  check_deploy_tree "$REPO" "$DEPLOY_SHA" "$SERVED_SHA" "$WEB_SHA" \
    || refuse "deploy tree is not served tree + web/ only"
  say "deploy commit $DEPLOY_SHA (tree $TREE_SHA): outside web/ identical to served, web/ identical to $WEB_REF"
  check_clean_worktree "$WORKTREE" || refuse "dirty worktree $WORKTREE"

  if [ -n "$MARKER" ]; then
    LOCAL_DIST=$(build_local_web "$WORKTREE") || refuse "could not build web/ of the deploy tree locally"
    LOCAL_ENTRIES=$(entry_refs < "$LOCAL_DIST/index.html" | tr '\n' ' ' || true)
    [ -n "${LOCAL_ENTRIES// /}" ] || refuse "the local build's index.html names no /assets entry"
    say "local build $LOCAL_DIST, entries: $LOCAL_ENTRIES"
    if [ "$DRY_RUN" = 0 ] && ! marker_in_build "$LOCAL_DIST"; then
      refuse "the local build of the deploy tree lacks the marker; nothing was pushed or deployed"
    fi
  fi

  HEALTHZ_BEFORE=$(fetch_healthz) || refuse "could not read $URL/healthz"
  local identity_before identity_after
  identity_before=$(healthz_identity "$HEALTHZ_BEFORE" before) || refuse "invalid /healthz before deployment"
  say "healthz before: rooms 0, identity $identity_before"
  local rel
  rel=$(fly_release) || refuse "could not read fly releases"
  FLY_VERSION_BEFORE=${rel%% *}
  FLY_IMAGE_BEFORE=${rel#* }
  BUNDLES_BEFORE=$(served_bundles | tr '\n' ' ' || true)
  ROLLBACK_CMD=$(prepare_rollback) || refuse "could not preserve previous image/config for rollback"
  say "fly v$FLY_VERSION_BEFORE ($FLY_IMAGE_BEFORE); rollback: $ROLLBACK_CMD"

  if [ "$DRY_RUN" = 1 ]; then
    say "dry run: skipping git push and fly deploy"
  else
    git -C "$WORKTREE" push -q -u origin "$BRANCH" || refuse "git push failed"
    PUSHED=1
    check_clean_worktree "$WORKTREE" || refuse "dirty worktree $WORKTREE"
    say "fly deploy --ha=false -a $APP (from $WORKTREE)"
    if ! (cd "$WORKTREE" && fly deploy --ha=false -a "$APP"); then
      DEPLOYED=1
      refuse "fly deploy failed; check fly releases; rollback if needed: $ROLLBACK_CMD"
    fi
    DEPLOYED=1
  fi

  local waited=0
  until HEALTHZ_AFTER=$(fetch_healthz); do
    if [ "$waited" -ge "$HEALTHZ_WAIT" ]; then
      HEALTHZ_AFTER=null
      refuse "/healthz unreadable ${waited}s after the deploy; rollback: $ROLLBACK_CMD"
    fi
    sleep 5
    waited=$((waited + 5))
  done
  identity_after=$(healthz_identity "$HEALTHZ_AFTER") \
    || refuse "invalid /healthz after deployment; rollback: $ROLLBACK_CMD"
  if [ "$identity_after" != "$identity_before" ]; then
    say "healthz identity before: $identity_before"
    say "healthz identity after:  $identity_after"
    refuse "bot identity changed after the deploy; NOT rolling back automatically. Rollback: $ROLLBACK_CMD"
  fi
  say "healthz identity unchanged"

  rel=$(fly_release) || refuse "could not read fly releases after the deploy"
  FLY_VERSION_AFTER=${rel%% *}
  FLY_IMAGE_AFTER=${rel#* }
  if [ "$DRY_RUN" = 0 ] && [ "$FLY_VERSION_AFTER" -le "$FLY_VERSION_BEFORE" ]; then
    refuse "fly version did not advance (v$FLY_VERSION_BEFORE -> v$FLY_VERSION_AFTER)"
  fi
  STARTED_MACHINES=$(started_machines) || refuse "could not list machines"
  [ "$STARTED_MACHINES" = 1 ] || refuse "$STARTED_MACHINES started machines (need exactly 1; --ha=false)"
  BUNDLES_AFTER=$(served_bundles | tr '\n' ' ' || true)

  if [ -n "$MARKER" ]; then
    if marker_served; then MARKER_FOUND=true; else MARKER_FOUND=false; fi
    if [ "$DRY_RUN" = 0 ] && [ "$MARKER_FOUND" = false ]; then
      refuse "$MARKER_DETAIL; the new web build is not served. Rollback: $ROLLBACK_CMD"
    fi
    say "local build served (index.html and $MARKER_ASSET byte-identical): $MARKER_FOUND${MARKER_DETAIL:+ ($MARKER_DETAIL)}"
  fi

  if [ "$DRY_RUN" = 1 ]; then STATUS=dry-run-ok; else STATUS=deployed; fi
  write_receipt
  say "$STATUS: fly v$FLY_VERSION_BEFORE -> v$FLY_VERSION_AFTER, $STARTED_MACHINES started machine; rollback: $ROLLBACK_CMD"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
