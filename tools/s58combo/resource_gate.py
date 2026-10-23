"""Conservative admission before a one-shot in-memory JSON read."""
from pathlib import Path
import shutil

# JSON object expansion and analysis scratch space need separate headroom.
EXPANSION_FACTOR = 16
RESERVE_BYTES = 2 * 1024**3
MAX_INPUT_BYTES = 6 * 1024**3
MAX_FILE_BYTES = 16 * 1024**2


def available_memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        values[key] = value.strip()
    return int(values['MemAvailable'].split()[0]) * 1024


def check_resources(seals, *, available=None, streaming=False, root=None):
    total = 0
    largest = 0
    for seal in seals.values():
        for name, pin in seal['files'].items():
            size = pin.get('size')
            if type(size) is not int or size < 0:
                raise ValueError('invalid sealed size')
            if size > MAX_FILE_BYTES:
                raise ValueError('sealed file exceeds reader size limit')
            total += size
            largest = max(largest, size)
    if total > MAX_INPUT_BYTES:
        raise ValueError('sealed input exceeds reader aggregate limit')
    available = available_memory() if available is None else available
    required = (largest if streaming else total) * EXPANSION_FACTOR + RESERVE_BYTES
    if streaming:
        if root is None or shutil.disk_usage(root).free < total * 2 + 128 * 1024**2:
            raise ValueError("insufficient reader spool disk space")
    if type(available) is not int or available < required:
        raise ValueError(f'insufficient reader memory: need {required}, available {available}')
    return dict(input_bytes=total, required_memory_bytes=required, available_memory_bytes=available)
