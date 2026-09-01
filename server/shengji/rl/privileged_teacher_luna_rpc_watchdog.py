"""Parent-death containment wrapper for one zero-tool Codex RPC process."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading


def main(argv: list[str] | None = None) -> int:
    """Run one child and kill its process group if the controller disappears."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        return 125
    try:
        controller_fd = int(args[0])
    except ValueError:
        return 125
    command = tuple(args[1:])
    normal_completion = threading.Event()

    def terminate_on_parent_death() -> None:
        try:
            while os.read(controller_fd, 1):
                pass
        except OSError:
            pass
        if normal_completion.is_set():
            return
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        except ProcessLookupError:
            pass

    threading.Thread(
        target=terminate_on_parent_death,
        name="pt-luna-parent-death-watchdog", daemon=True).start()
    try:
        child = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True)
        prompt = sys.stdin.buffer.read()
        stdout, stderr = child.communicate(input=prompt)
        sys.stdout.buffer.write(stdout)
        sys.stderr.buffer.write(stderr)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        normal_completion.set()
        return int(child.returncode or 0)
    except OSError:
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
