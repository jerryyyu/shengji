"""Check the serving reference and isolated guest in the Fly Machines inventory."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from supervise import APP, reference_env

IMAGE = "sha256:e007928501d59402a226736f4051e5c6cfd2de066064b586b1029147227b1095"
GUEST = {"cpu_kind": "performance", "cpus": 1, "memory_mb": 2048}


def check(machines, dedicated, machine_id, config):
    if len(machines) != 1 or len(dedicated) != 1 or not re.fullmatch("[a-f0-9]+", machine_id):
        raise ValueError("expected singleton reference and isolated guest")
    reference, guest = machines[0], dedicated[0]
    if guest["id"] != machine_id or guest["id"] == reference["id"]:
        raise ValueError("wrong isolated machine ID")
    for machine in (reference, guest):
        if (machine["state"] != "started" or machine["region"] != "ewr"
                or machine["image_ref"]["digest"] != IMAGE
                or any(machine["config"]["guest"].get(k) != v for k, v in GUEST.items())):
            raise ValueError("image, region, guest size or state drift")
    if reference_env(reference["config"]["env"]) != reference_env(config):
        raise ValueError("served bot environment drift")
    if guest["config"].get("services") or guest["config"].get("mounts"):
        raise ValueError("isolated machine has services or mounts")
    if guest["config"].get("restart", {}).get("policy") != "no":
        raise ValueError("isolated machine may restart")


def inventory(app):
    return json.loads(subprocess.check_output(["flyctl", "machines", "list", "-a", app, "--json"]))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: admission.py ISOLATED_MACHINE_ID FROZEN_FLY_TOML")
    config = tomllib.loads(Path(sys.argv[2]).read_text())["env"]
    check(inventory("shengji"), inventory(APP), sys.argv[1], config)
    print("Fly admission passed")
