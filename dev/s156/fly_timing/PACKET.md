# M2 serving cost on an isolated Fly machine

One comparison of R55 as served (A) against the M2 unified and belief packages (B). Both sides use the same serving image, single-thread caps and compiled engine. The parent deals six first rounds with seeds 53000 through 53005, sends identical state copies to both workers, alternates which is timed first, and applies A's move. The primary metric is mean copy-plus-decision wall time on paired plays. The gates are an unrounded B/A ratio ≤1.10, play and belief fallbacks each no worse than A, projected server memory ≤1,536 MiB, at least 300 paired plays, and shared unified serving on every B play. A missing or inconsistent capture gives no timing verdict.

Claude owns dispatch, RELEASE, archival and removal of the dedicated guest under the one-test handoff on #1799. Read the exact freeze comment on the PR for the archive path and SHA-256. Preserve the archive, its matched Python source, the result and the three captured JSONL files. The guest uses an empty root filesystem overlay and loopback reference server. No Fly production volume or secrets are needed.

## Admission

Run from an empty directory on Mini outside the repository so flyctl cannot inherit the production app config. Use the specific reviewed git checkout for the two local scripts. Set PACKET to the published absolute archive path, SHA to its published digest and SRC to the checked-out dev/s156/fly_timing directory. Verify the archive and materialize its frozen configuration in the empty directory.

```sh
test "$(shasum -a 256 < "$PACKET" | cut -c1-64)" = "$SHA" || exit 1
tar -xOf "$PACKET" fly.toml > reference.toml
app=shengji-m2-timing
image=registry.fly.io/shengji@sha256:e007928501d59402a226736f4051e5c6cfd2de066064b586b1029147227b1095
```

After exact review and operator admission, create the dedicated empty app and the single guest. Stop on any error. A pre-existing app or machine requires reconciliation with the recorded run. Do not create another guest after an observation timeout.

```sh
flyctl apps create "$app" --org personal
flyctl machine run "$image" /bin/sleep infinity --app "$app" --name m2-r55 --region ewr --vm-size performance-1x --vm-memory 2048 --restart no --skip-dns-registration --detach
```

Record the machine ID returned by Fly as MID. The following read-only check verifies the production reference image, settings, guest geometry and region; it also checks that the named guest has the same image and geometry, no services or mounts, and no automatic restart. A changed serving image needs review of the new identity.

```sh
python3 "$SRC/admission.py" "$MID" reference.toml
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

Observe the existing supervisor and metadata (process state, file sizes and terminal marker). The producer watches the reference health, activity, available memory (300 MiB floor) and 45-minute cap. The supervisor exits on a HOLD, host timeout or failed child and leaves the partial capture. Only a zero producer exit can generate producer.done, which binds archive digest, machine ID and seal digest. On a successful terminal, post these three values before reading the measurement. Copy the evidence off-machine on either terminal before removing the guest. Use the same exact app and machine ID.

```sh
# On the dedicated guest after the supervisor exits
cd /tmp/m2fly
tar -czf /tmp/m2fly-evidence.tgz out supervisor.log server.log launcher.RELEASE started $(test ! -f producer.done || echo producer.done)
```

```sh
# On Mini
flyctl ssh sftp shell --app "$app" --machine "$MID" -C "get /tmp/m2fly-evidence.tgz m2fly-evidence.tgz"
mkdir evidence
tar -xzf m2fly-evidence.tgz -C evidence
```

For a completed capture, verify the three fields in the downloaded producer.done against the posted terminal. Run the reviewed reader once on Mini with SEAL set to the posted seal digest, using a fresh output destination. Reader rc 0 indicates PASS, 3 a valid FAIL and 2 insufficient evidence. Preserve the JSON and exit code. A partial capture stays closed. Once the evidence copy is verified, Claude destroys only the recorded isolated machine via `flyctl machine destroy "$MID" --app shengji-m2-timing --force`. There is no retry in this packet.

```sh
(set -C; python3 -B "$SRC/read_timing.py" evidence/out --seal-sha256 "$SEAL" > result.json)
```
