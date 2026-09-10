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
Preparation completed in 404.4 seconds; disk-array assembly took 36.1 seconds.
The cache contains 92,371 training deals / 1,477,936 positions. Training
completed all 20 epochs in 405.6 seconds; epoch 20 was selected by dev CE
(0.6029153, versus 0.6086597 for the 32k model). Both ownership readouts completed
using the saved ordinary/R4 forecasts. The training and readout processes exited
successfully; no new gameplay run was launched.

The named `lunaq` value holdout is the separately labeled **validation** file,
not the Luna fit source. Its 26 deck keys have zero intersection with the
26 fit-source keys and zero intersection with the complete selected training
population. This was checked against the actual `runACDEFGH-v2/receipt.json`
holdout path rather than inferring eligibility from the shared dataset name.

## Ownership results

Lower is better. Equal-deal Brier on uncertain **other-player hand** cells:

| Model / reference | Fixed 97 check deals | Earlier 14 DEV gameplay deals |
| --- | ---: | ---: |
| Ordinary sampler, debiased | 0.505248 | 0.494393 |
| Small model, 603 train deals | 0.513939 | 0.492678 |
| Small model, 8,000 train deals | 0.496493 | 0.466718 |
| Small model, 32,000 train deals | 0.486533 | 0.453565 |
| Small model, 92,371 train deals | **0.483430** | **0.452112** |
| Old R4 primary reference | 0.468794 | 0.438731 |

Full model minus ordinary: -0.021818, deal-bootstrap 95% interval
[-0.026039, -0.017794] on the 97 deals (4.32% relative reduction); -0.042281
[-0.051256, -0.033397] on the 14 deals (8.55%). The extra gain over 32k is
descriptively smaller; these intervals compare against ordinary, not against
32k. This is one training seed with a broader policy mixture and more optimizer
updates, not an isolated causal estimate of data volume.

Overall Brier is 0.457267 / 0.409365 and kitty Brier is 0.171395 / 0.177344
for the 97 / 14 populations respectively. The 97-deal reference contains 291
selected positions, of which 97 are deterministic and skipped; the 14-deal
reference contains 54 positions. Neither population is a newly unopened
holdout. Old R4 input/lineage comparability caveats from #332 remain; do not
interpret its reference row as a controlled architecture comparison.

Artifacts: `model-full/best.pt`, `model-full/last.pt`, `model-full/curves.json`,
`readout/receivers.json`, `readout/calibration.json`,
`fresh-readout/receivers.json`, and `fresh-readout/calibration.json` under the
run root. Next useful test is the selected full model in the unchanged W32
world-mixture consumer against ordinary/uniform controls. Prediction improvement
does not establish stronger gameplay, and production remains unchanged.

Validation: 74 focused tests pass, including bit-identical disk/in-memory
training, no check reads, missing-disk-array refusal, exact chunked priors and
fit-only Luna admission. Prior models/data/evaluations are preserved.
