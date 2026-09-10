"""Bounded local DEV client for archived actor-only inference; no network."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time


def actor_for_round(rnd, seat, archive_server):
    """Import only archived contract onto CURRENT exact Round/Memory classes."""
    import shengji.rl
    archive = Path(archive_server).resolve()/'shengji'/'rl'
    if str(archive) not in shengji.rl.__path__:
        shengji.rl.__path__.append(str(archive))
    contract = importlib.import_module('shengji.rl.belief_contract')
    if Path(contract.__file__).resolve() != archive/'belief_contract.py':
        raise ValueError('runtime actor contract source mismatch')
    return contract.build_actor_observation(rnd, seat)


class R4RuntimeClient:
    def __init__(self, archive_server, training_root, *, timeout=60.):
        self.archive_server = Path(archive_server).resolve()
        self.timeout = timeout
        self.request_id = 0
        self.pending = b''
        self.process = subprocess.Popen([
            sys.executable, '-u', str(Path(__file__).with_name('r4_inference_service.py')),
            '--archive-server', str(self.archive_server), '--training-root', str(training_root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            ready = self._read()
            if ready.get('ready') is not True:
                raise ValueError('R4 service did not become ready')
            self.identity = ready['identity']
        except BaseException:
            self.close()
            raise

    def _read(self):
        deadline = time.monotonic()+self.timeout
        while b'\n' not in self.pending:
            remaining = deadline-time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError('R4 inference response deadline exceeded')
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('R4 inference service exited before response')
            self.pending += chunk
            if len(self.pending) > 4*1024*1024:
                raise ValueError('R4 response size exceeded')
        line, self.pending = self.pending.split(b'\n', 1)
        return json.loads(line)

    def predict(self, actor):
        self.request_id += 1
        request = {'request_id': self.request_id, 'actor': actor.to_dict()}
        try:
            self.process.stdin.write((json.dumps(request, allow_nan=False)+'\n').encode())
            self.process.stdin.flush()
            response = self._read()
            if response.get('request_id') != self.request_id or response.get('actor_sha256') != actor.sha256() \
                    or response.get('joint_posterior') is not False or set(response['arms']) != set(self.identity):
                raise ValueError('R4 inference response identity differs')
            return response
        except BaseException:
            self.close()
            raise

    def close(self):
        # Own child only. Never terminate another user's process or retry it.
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.selector.close()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
