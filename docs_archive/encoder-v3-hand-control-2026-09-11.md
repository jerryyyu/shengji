# Encoder v3: matched production-data comparison

Jerry's September 11 direction: train a new v3 model on the same data as
production, then compare it against production in W32. This supersedes the
suggested smaller 8,192-deal feature screen. No production change is authorized.

## Fixed baseline and data

Production source checkpoint: `runACDEF-v2/best.pt`, SHA256
`3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.
Its compact serving export is `fd6bb411…`, configured in `fly.toml`.
Recipe and exact split membership are in
`~/.claude/jobs/68f9c8bd/tmp/train-out/cwv/runACDEF-v2/receipt.json`.

- Sources: Run A + C + D + E + F2; 96,000 distinct deals total.
- Fit: 76,800 deals; validation: 9,600; test: 9,600. **Not 96,000 fit deals.**
- Require the original source/shard identities and exact split digests:
  train `355fea285281f94c22c20ee199099c858faa1fce096695f0d54ba01a00c13c0e`,
  validation `09d638d42e5950a2dbff7c93ef5b365e1c83c22bf0b55370de7f2fdaf4dab921`,
  test `bae5cb256a1490ba3aade5b54770ba2613778e4a17be9b22fcf771bbd9177a71`.
- Preserve all existing holdout exclusions. Reused test/diagnostic populations
  are historical comparisons, not fresh confirmatory evidence.

## Single training change

Append eight own-hand control features to v2: boss plain/trump card copies,
boss plain/trump pairs, longest plain/trump tractor, and plain/trump tractor
component counts. These use the actor's hand and public unseen-card counts;
banker-private kitty remains excluded. "Boss" means no higher unseen card of
the effective suit, not a guaranteed trick winner (ruffing still matters).

Keep the production recipe: MLP 512→256, dropout .1, AdamW, learning rate
.0003, weight decay .0001, batch 1024, seed 1, auxiliary points weight 1,
maximum 20 epochs, patience 3, checkpoint selection by validation CE. Train
from scratch. Input gains eight columns; hidden sizes and targets do not
change. The production checkpoint selected epoch 5; do not force v3 to that
epoch. Report ranking/coverage alongside CE without selecting on gameplay.

This tests the eight-feature group, not eight individually identified effects.
Reuse the archived v2 model for the direct product comparison; if the current
trainer differs semantically from its original recipe, use a matched v2 control
or explicitly separate trainer effects before crediting v3.

## Execution and gameplay

1. Finish actual-consumer tests before data preparation: reference cache
   construction, v3 compact NumPy export/load, training/static encoding parity,
   source-identity invalidation, privacy and old-checkpoint compatibility.
2. Re-encode the original eligible rows with bounded, resumable parallel
   preparation. Coordinate Mini MPS with Claude's existing training; do not
   overlap competing GPU jobs or interrupt the running belief W32 screen.
3. Train the v3 model with visible epoch/loss/throughput progress, retained
   checkpoints and an ETA based on measured preparation/epoch pace.
4. Compare v3 against the production v2 checkpoint in otherwise unchanged W32
   on paired, disjoint gameplay deals. Keep ordinary legal world sampling,
   W32/K4/N30/R300, declaration and the same production hybrid-bury checkpoint
   on both sides. Only the **play-ranking model** changes; do not also switch
   bury to v3 or introduce learned belief sampling.
5. Report signed levels per round and paired uncertainty, ranking/coverage,
   latency/CPU/memory and failures. Publish negative or inconclusive outcomes.
   Fix the bounded gameplay population before launch; do not keep expanding
   it until a positive result appears. No deployment without a separate decision.

Status: source integration repaired and independently reviewed PASS. Focused
regression: 112 tests passed; the real public+CWV training/evaluation smoke
also passes for v2 and v3. Tests exercise cache reconstruction, public-head
loaders, exported NumPy inference, version/width binding and stale-source
refusal, not just helper outputs. The NumPy package remains Torch-free.

The source delta from the production trainer at `fda20f64` to base `32fe13a`
changes the default encoder (the production command explicitly chose v2)
and compatibility for an identity-preserving history import move, not the
explicit optimizer/training loop. Reuse the archived production checkpoint
as the baseline rather than add a duplicate full v2 training by default.

Training and v3 gameplay have not started. Production and the independent
260-deal full-belief gameplay run are unchanged. Next: measure retained-cache
preparation pace, then prepare the full original population and train.
