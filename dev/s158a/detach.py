"""Detach a command into its own session (macOS has no setsid): detach.py LOGFILE CMD... ; prints the pid."""
import os, sys
log, cmd = sys.argv[1], sys.argv[2:]
pid = os.fork()
if pid:
    print(pid); sys.exit(0)
os.setsid()
fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(fd, 1); os.dup2(fd, 2)
nul = os.open(os.devnull, os.O_RDONLY); os.dup2(nul, 0)
os.execv(cmd[0], cmd)
