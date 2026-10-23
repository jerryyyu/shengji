"""Bounded, repeatable storage for hash-verified screen shards.

The store deliberately accepts bytes from its caller.  It does not discover or
open producer files, so provenance and hashing remain the reader's job.
"""

from collections.abc import Iterator, Mapping
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile


class ShardStore(Mapping):
    """Spool shard bytes in a private SQLite database.

    ``outputs`` is the frozen output inventory.  Every output must be present
    with exactly clusters 0..519 before a caller treats it as complete; the
    store itself allows incremental insertion while a window is read.
    """

    CLUSTERS = 520
    CACHE_BYTES = 8 * 1024 * 1024

    def __init__(self, outputs, parent):
        values = tuple(outputs)
        if not values or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("outputs must be non-empty strings")
        if len(set(values)) != len(values):
            raise ValueError("duplicate output")
        self._outputs = values
        self._output_set = set(values)
        self._parent = Path(parent)
        self._parent.mkdir(parents=True, exist_ok=True)
        self._directory = Path(tempfile.mkdtemp(prefix="s58-shards-", dir=self._parent))
        self._closed = False
        self._db = None
        try:
            self._db = sqlite3.connect(self._directory / "shards.sqlite3")
            self._db.execute("PRAGMA cache_size = -8192")
            self._db.execute("PRAGMA temp_store = FILE")
            self._db.execute("CREATE TABLE shards (output TEXT NOT NULL, cluster INTEGER NOT NULL, payload BLOB NOT NULL, PRIMARY KEY (output, cluster))")
            self._db.commit()
        except Exception:
            self.close()
            raise

    @property
    def directory(self):
        return self._directory

    def _check_open(self):
        if self._closed:
            raise ValueError("shard store is closed")

    def add(self, output, cluster, data):
        self._check_open()
        if output not in self._output_set:
            raise KeyError(output)
        if type(cluster) is not int or not 0 <= cluster < self.CLUSTERS:
            raise ValueError("cluster must be an integer in 0..519")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes")
        payload = bytes(data)
        try:
            self._db.execute("INSERT INTO shards(output, cluster, payload) VALUES (?, ?, ?)",
                             (output, cluster, payload))
            self._db.commit()
        except sqlite3.IntegrityError as exc:
            self._db.rollback()
            raise ValueError("duplicate output/cluster") from exc

    def __getitem__(self, output):
        self._check_open()
        if output not in self._output_set:
            raise KeyError(output)

        def rows() -> Iterator[object]:
            cursor = self._db.execute(
                "SELECT payload FROM shards WHERE output = ? ORDER BY cluster", (output,))
            try:
                for (payload,) in cursor:
                    yield json.loads(payload)
            finally:
                cursor.close()

        return rows()

    def __iter__(self):
        return iter(self._outputs)

    def __len__(self):
        return len(self._outputs)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._db is not None:
                self._db.close()
        finally:
            shutil.rmtree(self._directory, ignore_errors=False)

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

