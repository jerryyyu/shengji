"""Select a sealed named pair without decoding other rows' outcomes."""
import hashlib
import json
import re

from extract import LOCATOR, project_pair

HEADER = re.compile(rb'^\{"arm": "[A-Za-z0-9_-]{1,128}", "seed": ([0-9]{1,16}), "mirror": ([01]), ')
MAX_LINE = 8 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


def select_pair(stream, expected_sha256, *, locator=LOCATOR, expected_rows=1200):
    """Hash all bytes, inspect leading identities, decode only the sealed pair.

    The producer's ordered JSON header precedes all outcome fields. Non-target
    row bodies are discarded without JSON decoding. Callers must establish
    terminal, ownership and HOLD gates before supplying the stream.
    """
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('invalid input seal')
    digest, selected = hashlib.sha256(), {}
    count, total = 0, 0
    while True:
        raw = stream.readline(MAX_LINE + 1)
        if not raw:
            break
        count += 1
        total += len(raw)
        if len(raw) > MAX_LINE or total > MAX_TOTAL or count > expected_rows:
            raise ValueError('source exceeds extraction bounds')
        digest.update(raw)
        header = HEADER.match(raw[:256])
        if header is None:
            raise ValueError('producer identity header drift')
        seed, mirror = map(int, header.groups())
        if seed == locator['seed']:
            if mirror in selected:
                raise ValueError('duplicate target mirror')
            selected[mirror] = raw
    if count != expected_rows or digest.hexdigest() != expected_sha256:
        raise ValueError('source seal or population drift')
    if set(selected) != {0, 1}:
        raise ValueError('target mirror missing')
    rows = [json.loads(selected[mirror]) for mirror in (0, 1)]
    result = project_pair(rows, locator)
    result['source_sha256'] = expected_sha256
    return result
