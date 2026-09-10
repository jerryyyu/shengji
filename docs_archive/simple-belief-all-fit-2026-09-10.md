# Small belief: full eligible-deal run

Jerry requested training on all available eligible data after the positive
8k/32k scaling result (PR #333). No production change is part of this run.

## Population and exclusions

Use the complete A/C/D/E/F2/G/H/I trajectory sources from the existing
144,000-deal value-training recipe, not a new collection. Eligibility is the
115,200-deal value-fit allowlist at `volVOL-144k/best.pt`, with the original
value model's val/test exclusions also preserved. The original deterministic
belief split remains in force. Keep the original 68 dev / 97 check files and
the 14 earlier gameplay deals out of training.

The separately designated Luna-quality fit supplement contributes eligible
real-deck play records, not evaluation data. Its private source is used only
to reconstruct training labels and actor-visible features. Outcomes, teacher
actions/values, original-deck keys and source identities are not model inputs.

Run B is excluded as the known A duplicate; Run J is excluded as the same
deals as I under another teacher. Global original-deck grouping prevents
duplicate/mirrored records being counted as independent deals. Older highn,
PT1, Luna-RPC and room-log corpora are named evaluation holdouts in the value
receipt, not additional fit data. Unsealed cloud runs are not consumed.

The selected population is **92,371 training deals**, including the existing
32,000-deal training set. There are no additional arbitrary per-source quotas.
"All" means all eligible independent training deals under the retained split,
not all raw files or all decision rows: the same 16 unique phase-spread positions
per deal are used to keep this comparable to the preceding scaling experiment.
The new G/H/I policy mixture means this is a broader-data recipe, not a pure
same-distribution scaling ablation.

## Execution and memory

Same 315,400-parameter MLP, seed 0, AdamW 0.001, batch 256, 20 epochs, two Torch
threads. Select by original dev CE, not check/gameplay results. This is a single
DEV training run, not a promotion claim or a hyperparameter sweep.

Preparation reuses original arrays and the 32k cache, reconstructing only new
deals with four workers. Train arrays are assembled into disk-backed NumPy
arrays instead of loading and concatenating all NPZ files into RAM. Count
targets use uint8 storage and convert to identical int64 tensors at each batch;
prior counts accumulate in bounded integer chunks. Check arrays cannot be
opened by this loader. A same-seed training test proves exact tensor equality
between the in-memory and disk-backed paths.

Disk assembly checkpoints only after flushing all three arrays; a missing
committed array refuses rather than silently filling zeros. Per-deal cache
and epoch checkpoints remain resumable. No reference/world sampling or old R4
inference needs repeating for the saved-state evaluation.

Source: branch `codex/simple-belief-full-fit`.
Artifacts: `~/shengji-archive/2026-09-10/simple-belief-all-fit/`.
Preparation log: `~/shengji-archive/2026-09-10/simple-belief-all-fit-prepare.log`.
Status: preparation running; training and new ownership results pending.

Validation: 74 focused tests pass, including bit-identical disk/in-memory
training, no check reads, missing-disk-array refusal, exact chunked priors and
fit-only Luna admission. Prior models/data/evaluations are preserved.
