# M2 serving cost on an isolated Fly machine

One comparison of R55 as served (A) against the M2 unified and belief packages (B). Both sides use the same serving image, single-thread caps and compiled engine. The parent deals six first rounds with seeds 53000 through 53005, sends identical state copies to both workers, alternates which is timed first, and applies A's move. Both workers receive every declaration opportunity on the same snapshot; only A changes the game. The primary metric is mean copy-plus-decision wall time on paired plays. The gates are an unrounded B/A ratio ≤1.10, play and belief fallbacks each no worse than A, idle reference server peak plus the full B worker peak ≤1,536 MiB (a conservative upper bound that counts shared runtime memory twice), at least 300 paired plays, and shared unified serving on every B play. A missing or inconsistent capture gives no timing verdict.

Claude owns dispatch, RELEASE, archival and removal of the dedicated guest under the one-test handoff on #1799. Read the exact freeze comment on the PR for the archive path and SHA-256. Preserve the archive, its matched Python source, the result and the three captured JSONL files. The guest uses an empty root filesystem overlay and loopback reference server. No Fly production volume or secrets are needed.

## Admission

Run from an empty directory on Mini outside the repository so flyctl cannot inherit the production app config. Use the specific reviewed git checkout for the two local scripts. Set PACKET to the published absolute archive path, SHA to its published digest and SRC to the checked-out dev/s156/fly_timing directory. Verify the archive and materialize its frozen configuration in the empty directory.

```sh
set -eu
PY=/Users/jerryyu/Projects/shengji/server/.venv/bin/python
"$PY" -B -c 'import hashlib, tomllib; assert hasattr(hashlib, "file_digest")'
test "$(shasum -a 256 < "$PACKET" | cut -c1-64)" = "$SHA" || exit 1
tar -xOf "$PACKET" fly.toml > reference.toml
app=shengji-m2-timing
image=registry.fly.io/shengji@sha256:e007928501d59402a226736f4051e5c6cfd2de066064b586b1029147227b1095
```

After exact review and operator admission, create the dedicated empty app and the single guest. Keep the app creation result and machine ID on Mini so another operator session can recover them. Stop the launch sequence on any error and follow the teardown procedure below. A pre-existing app or machine requires reconciliation with the recorded run. Do not create another guest after an observation timeout.

```sh
flyctl apps create "$app" --org personal
flyctl machine run "$image" /bin/sleep 10800 --app "$app" --name m2-r55 --region ewr --vm-size performance-1x --vm-memory 2048 --rm --restart no --skip-dns-registration --detach
```

Record the machine ID returned by Fly as MID immediately. From this point, every exit path goes through **Evidence retrieval and teardown**, including an admission refusal, failed upload, in-guest preflight failure and operator disconnect. The guest auto-destroys after three hours even if Mini disconnects. If creation reports an ambiguous outcome, reconcile the named guest in the dedicated app. If only the app was created, remove that empty app. An app that predated this invocation is outside this cleanup. The following read-only check verifies the production reference image, settings, guest geometry and region; it also checks that the named guest has the same image and geometry, no services or mounts, and no automatic restart. A changed serving image needs review of the new identity.

```sh
"$PY" -B "$SRC/admission.py" "$MID" reference.toml
flyctl ssh sftp shell --app "$app" --machine "$MID" -C "put $PACKET /tmp/m2fly.tgz"
```

In an SSH console addressed to this exact app and machine, set SHA and MID to the recorded values. Verify before unpacking. Claude writes the release with noclobber after checking the local queue, current HOLDs and exclusive ownership. The release is scoped to this guest and digest.

```sh
set -eu
test "$FLY_APP_NAME" = shengji-m2-timing
test "$FLY_MACHINE_ID" = "$MID"
test "$(sha256sum /tmp/m2fly.tgz | cut -c1-64)" = "$SHA"
mkdir /tmp/m2fly
cd /tmp/m2fly
mv /tmp/m2fly.tgz m2fly.tgz
tar -xzf m2fly.tgz
sha256sum --quiet --strict --check SHA256SUMS
test ! -e launcher.HOLD
(set -C; printf '%s %s\n' "$SHA" "$MID" > launcher.RELEASE)
nohup setsid /app/server/.venv/bin/python -B supervise.py "$SHA" >supervisor.log 2>&1 </dev/null &
```

## Terminal and readout

Observe the existing supervisor and metadata (process state, file sizes and terminal marker). The producer watches the reference health, activity, available memory (300 MiB floor) and 45-minute cap. The supervisor exits on a HOLD, host timeout or failed child and leaves the partial capture. Only a zero producer exit can generate producer.done, which binds archive digest, machine ID and seal digest. On a successful terminal, post these three values before reading the measurement. A lost observation or SSH session calls for reconnecting to the same MID. Allow a live supervisor to reach its terminal and retrieve evidence before the three-hour guest expiry.

## Evidence retrieval and teardown

On every terminal or prelaunch failure, retrieve whichever evidence exists. If staging failed before the packet directory existed, preserve the Mini operator logs. Use a fresh local evidence directory for this guest. If transfer is interrupted, resume retrieval against the same guest while it exists.

```sh
# On the dedicated guest after supervisor exit, or on a prelaunch failure
if test -d /tmp/m2fly; then
    cd /tmp/m2fly
    set --
    for entry in out supervisor.log server.log launcher.RELEASE launcher.HOLD started producer.done; do
        if test -e "$entry"; then set -- "$@" "$entry"; fi
    done
    if test "$#" -gt 0; then tar -czf /tmp/m2fly-evidence.tgz "$@"; fi
fi
```

```sh
# On Mini, when an evidence bundle exists
flyctl ssh sftp shell --app "$app" --machine "$MID" -C "get /tmp/m2fly-evidence.tgz m2fly-evidence.tgz"
mkdir evidence
tar -xzf m2fly-evidence.tgz -C evidence
```

Claude owns teardown on success and failure, including recovery after an operator disconnect. After copying the available evidence, verify the machine ID against the original creation record. Destroy that exact guest and then the dedicated app. If the platform has already auto-destroyed the guest, verify its absence and proceed to app cleanup. If inventory shows an unexpected machine, reconcile ownership before destroying the app. Record any unavailable evidence and the cleanup outcome on the PR.

```sh
flyctl machine destroy "$MID" --app shengji-m2-timing --force
flyctl apps destroy shengji-m2-timing --yes
```

For a completed capture, verify the three fields in the downloaded producer.done against the posted terminal. Run the reviewed reader once on Mini with SEAL set to the posted seal digest, using a fresh output destination. Reader rc 0 indicates PASS, 3 a valid FAIL and 2 insufficient evidence. Preserve the JSON and exit code. A partial capture stays closed. There is no retry in this packet.

```sh
(set -C; "$PY" -B "$SRC/read_timing.py" evidence/out --seal-sha256 "$SEAL" > result.json)
```
