import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'receipt', Path(__file__).parents[1] / 'scripts/verify_puct_predecessor.py')
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


def rows():
    common = dict(UNIT=receipt.UNIT, INVOCATION_ID=receipt.INVOCATION,
                  _MACHINE_ID=receipt.MACHINE, _BOOT_ID=receipt.BOOT,
                  _PID='1', _UID='0')
    return [dict(common, __MONOTONIC_TIMESTAMP='1', JOB_TYPE='start', JOB_RESULT='done'),
            dict(common, __MONOTONIC_TIMESTAMP='2', _PID='1183266',
                 _SYSTEMD_UNIT=receipt.UNIT, MESSAGE='G1 SEQUENTIAL LADDER DONE'),
            dict(common, __MONOTONIC_TIMESTAMP='3', CODE_FUNC='unit_log_success',
                 MESSAGE_ID='7ad2d189f7e94e70a38c781354912448')]


def test_complete():
    receipt.verify(rows())


@pytest.mark.parametrize('index', [0, 1, 2])
def test_missing_event(index):
    data = rows()
    data.pop(index)
    with pytest.raises(ValueError):
        receipt.verify(data)


@pytest.mark.parametrize('key,value', [
    ('INVOCATION_ID', 'other'), ('_MACHINE_ID', 'other'), ('_BOOT_ID', 'other'),
    ('_PID', '123'), ('_UID', '1'), ('CODE_FUNC', 'unit_log_failure'),
    ('MESSAGE_ID', 'other'), ('__MONOTONIC_TIMESTAMP', '1')])
def test_invalid_success(key, value):
    data = rows()
    data[2][key] = value
    with pytest.raises(ValueError):
        receipt.verify(data)


def test_later_invocation():
    data = rows()
    data.append(dict(data[0], INVOCATION_ID='new', __MONOTONIC_TIMESTAMP='4'))
    with pytest.raises(ValueError):
        receipt.verify(data)


def test_empty():
    with pytest.raises(ValueError):
        receipt.verify([])
