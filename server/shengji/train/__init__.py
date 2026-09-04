"""Value/prior training pipeline v0 (train_spec.md; ledger 29871a60, 7a799e1c,
784569ba).

``data``       decision-record stores -> encoded, cached training blocks
               (state rebuilt with ``harvest.rebuild``, encoded with the
               production ``rl.encode``; the PRIVACY witness refuses an
               encoder that reads another seat's hand; missing shard caches
               are built in a pool of spawned workers, byte-identical)
``model``      the v0 MLP: trunk 531 -> 512 -> 256, value head, per-candidate
               prior head with a ballot-masked softmax, optional auxiliary
               search-mean head (the search's own estimate of the played action)
``baselines``  the stratified prior for value, the uniform / incumbent prior
               baselines, cluster bootstrap CIs and the affine calibration
``train_v0``   the ``train`` / ``evaluate`` commands, receipts and checkpoints
``sweep``      ``train`` over a grid of config overrides with one shared cache;
               ``sweep.json`` / ``sweep.md`` with one row per config

Tier i: engine + torch only; nothing here spends LLM tokens.
"""
