"""Packs bake.mjs's masks into the atlas the server reads.

    python3 web/scripts/og-table/pack.py masks.json server/shengji/api/invite_atlas.npz

Each mask ``name`` becomes ``m_<name>`` (uint8 coverage, rows by columns) and
``x_<name>`` (float32: x0, y0, advance); ``spec`` holds the baked strings and
sizes as JSON. Only numpy is needed, and the file loads without pickle.
"""

import json
import sys

import numpy as np


def main(src: str, dst: str) -> None:
    with open(src, encoding="utf-8") as f:
        baked = json.load(f)
    arrays = {"spec": np.array(json.dumps(baked["spec"], ensure_ascii=False))}
    for name, m in baked["masks"].items():
        arrays[f"m_{name}"] = np.array(m["a"], dtype=np.uint8).reshape(m["h"], m["w"])
        arrays[f"x_{name}"] = np.array([m["x0"], m["y0"], m["adv"]], dtype=np.float32)
    np.savez_compressed(dst, **arrays)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
