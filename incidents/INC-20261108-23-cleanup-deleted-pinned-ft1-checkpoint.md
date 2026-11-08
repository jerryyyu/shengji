# INC-23: Home cleanup deleted the only known training checkpoint of the served prior

**Date**: 2026-11-08

**Severity**: S3. No wrong data entered any training set or measurement. A
pinned input was lost, and X2 stage two waits until it is rebuilt and reviewed.

**Status**: open. The served export survives, and a rebuild from it is in
progress. The pin check now runs inside `safe_rm.py` (outside the repo), with
seven new witness cases; `test_safe_rm.sh` reports 14 passed and 0 failed.

## What happened

On 2026-11-08 at 04:24Z, a Mini home-folder cleanup deleted `~/mrt-b0` (897 MB)
with `safe_rm.py`. Claude had proposed the folder list and Jerry approved it.
The folder held `p0train/FT1/best.pt`, sha256 `0def7b31…`. That file is the
train_cwv checkpoint of FT1, the policy prior served in releases 50 and 51.
No other copy has been located in the inventories checked:
- the Ultra's 238 `.pt` files, hashed;
- the external SSD, searched by name;
- a `/usr/bin/find` of the Mini home. Its 766 `.pt` files were matched by name only, not hashed. The one FT1-named candidate, `~/shengji-scratch/ft2/reh/p0-orig-e1/FT1/best.pt`, hashes to `f7eb71b3…`.

Packets that pinned the path or the hash:

| packet | use |
|---|---|
| `2026-11-06-g5-packet` | `--init` and `--value-teacher` (`0def7b31`) |
| `2026-11-03-ft2-packet` | staging source |
| `2026-11-01-g3-readers` | reader inputs |
| `2026-11-08-x2-stage2-packet` | `--init` and `--value-teacher` for the X2 prior fine-tune |

The X2 stage-two packet build found the loss on 2026-11-08 at about 16:00Z,
when it could not stage FT1.

The same cleanup deleted three more folders that older packets reference.
`~/ft2` held the FT2 packages. `~/g2-uni` and `~/g2-ue` held the U and UE arm
checkpoints of G2. None of those models is served or pending. `~/g3A`, the
source of the served value net `f4f4127e`, was also deleted. Its
`epoch-04.avg.pt` has a copy that G4 staged on the Ultra.

## Why

- The folder list was built from names, ages and sizes ("old scratch from
  10-28"). No step hashed the large files under each folder or searched the
  archived packets for those hashes and paths.
- `safe_rm.py` protects only paths listed in `~/.safe_rm.keep` and symlink
  targets. A pinned file in a folder that is not on the keep list is
  unprotected.
- This is the second cleanup that removed something still in use. On
  2026-11-05 a cleanup deleted the gen-hybrid venv twice. So under the
  AGENTS.md rule this needs an enforcer, not more prose.

## Recovery

- The served export `p0-ft1-1fa201b2.npz` keeps every inference weight in
  fp32: the trunk, the outcome head, the policy head and the aux head. Its
  metadata records `original_checkpoint_sha256 = 0def7b31`.
- It lacks the training-only search head. It also lacks the `exposure` and
  `population` blobs; their canonical sha256s are recorded, so a rebuilt copy
  can be checked against them.
- The rebuild writes a train_cwv checkpoint from the export. It must prove
  identical outputs against the served numpy inference before X2 uses it. Any
  packet that consumes it rebinds to the new hash and goes through review again.
- FT1's parent checkpoint (`JS3-M1-policy-w1.0-soft/best.pt`) survives.

## Rules

- Before any cleanup delete, `safe_rm.py` hashes every model and data file
  over 1 MB under the target. It refuses the delete if a hash or path appears
  in an archived packet's `commands.json`, `slots*.json`, `source-pins.json`,
  `SHA256SUMS`, `stage_*.sh`, `*.sh` or `launch.py`.
- The pin files it reads are those under `~/shengji-archive/*/` and
  `~/fleet/*/`, one level deep.
- It matches a path written absolute or as `~/`, `$HOME/` or `${HOME}/`.
- It hashes only files of 1 MB or more with a model or data extension
  (`.pt .npz .ckpt .safetensors .bin .npy .jsonl .tar`). Smaller pinned files
  are protected by path only.
- To delete a pinned file, copy it first to
  `~/shengji-archive/<date>-pinned-inputs/` and re-hash the copy.
