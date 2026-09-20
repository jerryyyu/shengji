# The external SSD: what shengji keeps there and the rules

The Mac Mini (M4, 460 GB internal disk) is the training box and fills up. Cold artifacts live on the
external SSD (`/Volumes/Extreme SSD`, ~2 TB, USB). The SSD is NOT always mounted; every script that
touches it checks the mount first and refuses otherwise.

**The one rule:** nothing under `shengji-*` on the SSD is deleted without Jerry's explicit word. Every
directory carries a `SHA256SUMS`; verify with `shasum -a 256 -c SHA256SUMS`.

**The inventory of record is on the SSD itself:** `/Volumes/Extreme SSD/shengji-INVENTORY.md`,
maintained by Claude and appended whenever something is added. This page is the pointer and the rules;
the inventory is the list.

## What is there (2026-09-20)

| path | what | size |
|---|---|---|
| `shengji-backup/2026-09-13/` | the training-output tree as of 09-13 (older runs' checkpoints and receipts), tarred with checksums | ~half of 99 GB |
| `shengji-backup/2026-09-18/` | full backup of the Mini's `train-out/cwv` and `~/shengji-archive` as of 09-18, verified by read-back (`README.md`, `SHA256SUMS.verified`) | ~half of 99 GB |
| `shengji-pack/v5-176k/` | FAILED first build of the decoded pack (PackError at shard 1,001, string width); incomplete, no manifest; kept until Jerry decides | 29 GB |
| `shengji-pack/v5-176k-r2/` | the decoded pack of the 176k v5 corpus (#531/#532/#549), built 2026-09-20 in 879 s; `manifest.json` binds the encoder identity and every shard's sha256 | 29 GB |
| `shengji-moved/2026-09-20/checkpoints/<run>/checkpoints.tar` | per-epoch checkpoints of ten sealed runs (gen-1, gen-2, gen-3-warm, soft, soft-killed, JS-G1, M1-v5, JS-M1-v5, the two kitty pilots); `best.pt`, `receipt.json`, `metrics.json` and logs stayed on the Mini under `train-out/cwv/<run>/`, with a `checkpoints.MOVED.txt` pointer | 6.3 GB |
| `shengji-moved/2026-09-20/policy_rows/{v4,v5,v8}.tar` | policy-row extracts that were inputs to sealed models (v4 = JS-M1's rows, v2 176k; v5 = the v5-ENCODER rows for JS-M1-v5; v8 = the soft arm's rows with search values, 256k); `fl-pilot/<name>.MOVED.txt` pointers on the Mini | 7.1 GB |

Moves are done by `fl-pilot/claude_move_to_ssd.armed.sh`: tar, then every file read back from the tar
and its sha256 compared with the original, then the original deleted, then the inventory appended.
A failed verification keeps the original.

## What the SSD is and is not good for

A measured epoch (#542 lever 1, 2026-09-20) read the decoded pack from the SSD at ~50 MB/s in ~20 KB
random requests: the pack store reads each shard as a handful of small contiguous column slices in
random shard order, and USB per-request latency made `batch_wait` 666 s against 426 s for decoding
the compressed cache from the internal disk. The pack itself trained the identical model (tensor
parity with the cache path). So: the SSD is cold storage and sequential I/O; a memory-mapped pack
that is read in random shard order belongs on the internal disk (or the store reads windows in
offset order and permutes in RAM).

## Restoring something

```
cd /Volumes/Extreme\ SSD/shengji-moved/2026-09-20/checkpoints/<run> && shasum -a 256 -c SHA256SUMS
tar -xf checkpoints.tar -C /path/to/train-out/cwv/<run>/      # recreates <run>/checkpoints/
```
