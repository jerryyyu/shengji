# The external SSD: what shengji keeps there and the rules

The Mac Mini (M4, 460 GB internal disk) is the training box and fills up. Cold artifacts live on the
external SSD (`/Volumes/Extreme SSD`, ~2 TB, USB). The SSD is NOT always mounted; every script that
touches it checks the mount first and refuses otherwise.

**The one rule:** nothing under `shengji-*` on the SSD is deleted without Jerry's explicit word.

**Verification is per artifact** (the checksum file's name and coverage differ; the table says which):
`shasum -a 256 -c <checksum file>` from inside the directory that holds it.

**The inventory of record is on the SSD itself:** `/Volumes/Extreme SSD/shengji-INVENTORY.md`,
maintained by Claude and appended whenever something is added. This page is the pointer and the rules;
the inventory is the list.

## What is there (2026-09-20)

| path | what | verification | size |
|---|---|---|---|
| `shengji-backup/2026-09-13/` | the training-output tree as of 09-13 (older runs' checkpoints and receipts), as tars | the checksum files inside `train-out-cwv-tars/` (see that directory) | part of 99 GB |
| `shengji-backup/2026-09-18/` | full backup of the Mini's `train-out/cwv` and `~/shengji-archive` as of 09-18 | `SHA256SUMS.txt` (verified by read-back on 09-18: `SHA256SUMS.verified`, `README.md`) | part of 99 GB |
| `shengji-pack/v5-176k/` | FAILED first build of the decoded pack (PackError at shard 1,001, string width); incomplete, no manifest | **UNVERIFIED and incomplete** — no checksum of any kind; kept only until Jerry decides | 29 GB |
| `shengji-pack/v5-176k-r2/` | the decoded pack of the 176k v5 corpus (#531/#532/#549), built 2026-09-20 in 879 s | **no checksum file of the pack's own bytes.** `manifest.json` binds the encoder identity and the sha256 of every SOURCE cache shard — it certifies inputs, not the output bytes. The evidence that the pack is right is the trainer: an epoch from this pack produced tensors equal to the cache path's (#542, 2026-09-20). Rebuildable from the caches. | 29 GB |
| `shengji-moved/2026-09-20/checkpoints/<run>/checkpoints.tar` | per-epoch checkpoints of ten sealed runs (gen-1, gen-2, gen-3-warm, soft, soft-killed, JS-G1, M1-v5, JS-M1-v5, the two kitty pilots); `best.pt`, `receipt.json`, `metrics.json` and logs stayed on the Mini under `train-out/cwv/<run>/`, with a `checkpoints.MOVED.txt` pointer | `SHA256SUMS` in each `<run>/` directory (the tar's hash); every member was read back and compared with the original before the original was deleted | 6.3 GB |
| `shengji-moved/2026-09-20/policy_rows/policy_rows_v4.tar`, `policy_rows_v5.tar`, `policy_rows_v8.tar` | policy-row extracts that were inputs to sealed models (v4 = JS-M1's rows, v2 176k; v5 = the v5-ENCODER rows for JS-M1-v5; v8 = the soft arm's rows with search values, 256k); `fl-pilot/policy_rows_v<N>.MOVED.txt` pointers on the Mini | `SHA256SUMS` in `policy_rows/`; members read back and compared before deletion | 7.1 GB |

Moves are done by `fl-pilot/claude_move_to_ssd.armed.sh`: tar, then every file read back from the tar
and its sha256 compared with the original, then the original deleted, then the inventory appended.
A failed verification keeps the original.

## What the SSD is and is not good for

**Observed** (#542 lever 1, 2026-09-20, `PACK-v5-1epoch`): one epoch of M1's recipe from this pack
had `batch_wait` 666.2 s against 425.5 s for the cache path on the internal disk, with step and
to_device unchanged; the pack trained the identical model (tensor parity with the cache path).
`iostat -d` sampled during the epoch showed the SSD device at ~45–53 MB/s and ~1,950–2,190
transfers/s (~20–28 KB per transfer); the exact samples are in the #542 comment thread.

**Established from the source** (Codex, #542): `CwvPackStore.iter_batches` reconstructs, masks,
shuffles and gathers each window synchronously in the trainer process and ignores `--decode-workers`,
whereas the cache path decodes in worker processes.

**Hypotheses, not attribution:** part of the gap is that single-threaded reconstruction; part may be
the storage's per-request latency under the random-shard read order. Separating them needs the same
pack measured on the internal disk and/or worker-side reconstruction. Until then the practical rule is:
the SSD is cold storage and sequential I/O; do not train from a memory-mapped pack on it.

## Restoring something

```
cd "/Volumes/Extreme SSD/shengji-moved/2026-09-20/checkpoints/<run>" && shasum -a 256 -c SHA256SUMS
tar -xf checkpoints.tar -C /path/to/train-out/cwv/<run>/      # members start with checkpoints/, so this recreates <run>/checkpoints/
cd "/Volumes/Extreme SSD/shengji-moved/2026-09-20/policy_rows" && shasum -a 256 -c SHA256SUMS
tar -xf policy_rows_v8.tar -C /path/to/fl-pilot/                # recreates fl-pilot/policy_rows_v8/
```
