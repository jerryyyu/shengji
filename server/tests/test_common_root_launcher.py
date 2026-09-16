import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/launch_common_root_after_continuation.sh'


@pytest.fixture
def launch_check(tmp_path):
    systemctl = tmp_path / 'systemctl'
    systemctl.write_text('#!/bin/sh\ncase "$4" in\n'
                        'LoadState) echo "${TEST_LOAD-loaded}";;\n'
                        'ActiveState) echo "${TEST_STATE-active}";;\n'
                        'SubState) echo "${TEST_SUB-exited}";;\n'
                        'MainPID) echo "${TEST_PID-0}";;\n'
                        'Result) echo "${TEST_RESULT-success}";;\n'
                        'InvocationID) echo "${TEST_INV-70384b5d5002458aace414dc0a795173}";;\n'
                        'esac\n')
    systemctl.chmod(0o755)
    git = tmp_path / 'git'
    git.write_text('#!/bin/sh\necho REACHED_SOURCE_CHECK >&2\nexit 77\n')
    git.chmod(0o755)

    def run(**changes):
        env = dict(os.environ, PATH=f'{tmp_path}:/usr/bin:/bin', **changes)
        return subprocess.run(['bash', str(SCRIPT), '--check'], env=env,
                              capture_output=True, text=True, timeout=5)
    return run


@pytest.mark.parametrize('changes', [
    {'TEST_LOAD': 'not-found'}, {'TEST_STATE': 'inactive'},
    {'TEST_SUB': 'running', 'TEST_PID': '123'}, {'TEST_PID': '123'},
    {'TEST_RESULT': 'timeout'}, {'TEST_INV': 'other'},
])
def test_predecessor_refuses_before_source(launch_check, changes):
    result = launch_check(**changes)
    assert result.returncode == 3
    assert 'HOLD continuation' in result.stdout
    assert 'REACHED_SOURCE_CHECK' not in result.stderr


def test_exact_success_reaches_source_check_only(launch_check):
    result = launch_check()
    assert result.returncode == 4
    assert 'REACHED_SOURCE_CHECK' in result.stderr
