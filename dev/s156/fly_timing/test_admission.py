import copy

import pytest

from admission import GUEST, IMAGE, check

ENV = {"SHENGJI_BOT": "reference", "SHENGJI_PV_UNIFIED_SHA256": "pinned"}


def inventory():
    reference = {"id": "a1", "state": "started", "region": "ewr", "image_ref": {"digest": IMAGE},
                 "config": {"guest": GUEST, "env": ENV}}
    guest = copy.deepcopy(reference)
    guest["id"] = "b2"
    guest["config"].update(services=[], mounts=[], restart={"policy": "no"})
    return reference, guest


def test_matching_singleton_with_no_services_or_mounts():
    reference, guest = inventory()
    check([reference], [guest], "b2", ENV)


@pytest.mark.parametrize("field,value", [("services", [{"ports": [443]}]), ("mounts", [{"path": "/data"}]),
                                       ("guest", dict(GUEST, cpus=2)), ("restart", {"policy": "always"})])
def test_refuse_wrong_or_serving_guest(field, value):
    reference, guest = inventory()
    guest["config"][field] = value
    with pytest.raises(ValueError):
        check([reference], [guest], "b2", ENV)


def test_refuse_wrong_machine_or_changed_control():
    reference, guest = inventory()
    with pytest.raises(ValueError):
        check([reference], [guest], "a1", ENV)
    with pytest.raises(ValueError):
        check([reference], [guest], "b2", dict(ENV, SHENGJI_BOT="different"))
