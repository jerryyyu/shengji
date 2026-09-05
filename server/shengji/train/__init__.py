"""Value/prior training pipeline v0 (train_spec.md; ledger 29871a60, 7a799e1c,
784569ba).

``data``       decision-record stores -> encoded, cached training blocks
               (state rebuilt with ``harvest.rebuild``, encoded with the
               production ``rl.encode``; the PRIVACY witness runs on EVERY
               cached row and refuses an encoder that reads another seat's
               hand; every row carries its canonical DEAL key, a digest of
               the dealt deck shared by every store / policy / mirror of the
               deal; missing shard caches are built in a pool of spawned
               workers, byte-identical; decoded blocks live in an LRU with a
               byte budget -- the RESIDENCY contract)
``model``      the v0 MLP: trunk 531 -> 512 -> 256, value head, per-candidate
               prior head with a ballot-masked softmax, optional auxiliary
               search-mean head (the search's own estimate of the played action)
``baselines``  the stratified prior for value, the uniform / incumbent prior
               baselines, deal bootstrap CIs and the affine calibration
``train_v0``   the ``train`` / ``evaluate`` commands, receipts and checkpoints:
               a three-way split by deal (train / val = selection +
               calibration, tuning only / test = the reported, held-out
               metrics); the Luna set is refused when it shares a deal with
               the data stores
``sweep``      ``train`` over a grid of config overrides with one shared cache;
               ``sweep.json`` / ``sweep.md`` with one row per config, TEST
               numbers as the headline and the val numbers labelled tuning

Tier i: engine + torch only; nothing here spends LLM tokens.
"""
