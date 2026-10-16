#!/usr/bin/env python3
"""Score CWV checkpoints and numpy packages on the same held-out deals with the
trainer's rank regret, the served-leaf rank regret and val CE.

    SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/served_rank_regret.py \
        --model e05=CKPT --model r45=PKG.npz --exposure-checkpoint R45_CKPT \
        --data DIR [--data DIR ...] --out DIR [--per-bucket 2] [--workers 2]

See ``shengji/train/served_rescore.py`` and ``shengji/train/served_rank.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train.served_rescore import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
