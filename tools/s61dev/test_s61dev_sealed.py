#!/usr/bin/env python3
"""Synthetic contract checks for the host-mode S61 sealed reader wrapper."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("s61dev_sealed", Path(__file__).with_name("read_s61dev_sealed.py"))
sealed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sealed)


@contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def reservation(trusted, *, launcher=None, output_root=None):
    return json.dumps({
        "schema": "claude-reservation-v1",
        "lane": trusted["lane"],
        "launcher_sha256": launcher or trusted["launcher_sha256"],
        "status": trusted["status"],
        "output_root": output_root or trusted["root"],
    })


def fixture(base):
    root = base / "root"
    root.mkdir()
    (root / "duel.jsonl").write_text("synthetic\n")
    (root / "SHA256SUMS").write_text("synthetic  ./duel.jsonl\n")
    status = base / "status"
    status.write_text("synthetic status\n")
    reservation_path = base / "reservation.json"
    launcher = "a" * 64
    trusted = dict(sealed.TRUSTED, launcher_sha256=launcher, root=str(root),
                   status=str(status), reservation=str(reservation_path))
    reservation_path.write_text(reservation(trusted))
    result = base / "readout" / "result.json"
    result.parent.mkdir()
    return root, status, reservation_path, trusted, result


class SealedReaderTests(unittest.TestCase):
    def test_wrong_root_refuses_before_reader_load(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root, status, reservation_path, trusted, result = fixture(base)
            wrong = base / "wrong-root"
            wrong.mkdir()
            (wrong / "duel.jsonl").write_text("raw\n")
            (wrong / "SHA256SUMS").write_text("raw  ./duel.jsonl\n")
            wrong_trusted = dict(trusted, root=str(wrong))
            with patched(sealed, "TRUSTED", wrong_trusted), patched(
                    sealed, "RESULT_PATH", str(result)), patched(
                    sealed, "_load_verified_reader", lambda: self.fail("reader loaded before binding")):
                with self.assertRaisesRegex(ValueError, "output_root"):
                    sealed.read_once()

    def test_wrong_reservation_refuses_before_reader_load(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root, status, reservation_path, trusted, result = fixture(base)
            reservation_path.write_text(reservation(trusted, launcher="b" * 64))
            with patched(sealed, "TRUSTED", trusted), patched(
                    sealed, "RESULT_PATH", str(result)), patched(
                    sealed, "_load_verified_reader", lambda: self.fail("reader loaded before binding")):
                with self.assertRaisesRegex(ValueError, "reservation"):
                    sealed.read_once()

    def test_valid_bound_read_publishes_small_claim_once(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root, status_path, reservation_path, trusted, result_path = fixture(base)

            class SyntheticReader:
                def analyze(self, data, *, status, sums):
                    self.asserted = (data, status, sums)
                    return {
                        "deals": 600,
                        "validity": {"verdict": "VALID"},
                        "bar": {"verdict": "EXPLOITER_AHEAD", "attribution_status": "ATTRIBUTION_OK"},
                        "levels": [0.06, 0.03, 0.09],
                        "points": [2.0, 1.0, 3.0],
                        "attribution": {"sentinel": "preserved"},
                        "canonical_lines": ["sentinel canonical line"],
                    }

            synthetic = SyntheticReader()
            with patched(sealed, "TRUSTED", trusted), patched(
                    sealed, "RESULT_PATH", str(result_path)), patched(
                    sealed, "_load_verified_reader", lambda: synthetic):
                self.assertEqual(sealed.read_once(), result_path)
                self.assertEqual(synthetic.asserted,
                                 (str(root / "duel.jsonl"), str(status_path), str(root / "SHA256SUMS")))
                claim = json.loads(result_path.read_text())
                self.assertEqual(claim["schema"], sealed.RESULT_SCHEMA)
                self.assertEqual(claim["reader_sha256"], sealed.READER_SHA256)
                self.assertEqual(claim["launcher_sha256"], trusted["launcher_sha256"])
                self.assertEqual(claim["verdict"], "EXPLOITER_AHEAD")
                self.assertEqual(claim["readout"]["attribution"], {"sentinel": "preserved"})
                self.assertEqual(claim["readout"]["canonical_lines"], ["sentinel canonical line"])
                self.assertEqual(set(claim), {
                    "schema", "lane", "host", "reader_sha256", "launcher_sha256", "binding", "deals",
                    "validity", "verdict", "attribution_status", "levels", "points", "readout",
                })
                with self.assertRaisesRegex(ValueError, "one-shot"):
                    sealed.read_once()

    def test_failed_reader_keeps_claim_and_retry_never_binds(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root, status_path, reservation_path, trusted, result_path = fixture(base)

            class FailedReader:
                def analyze(self, *args, **kwargs):
                    raise RuntimeError("synthetic reader failure")

            with patched(sealed, "TRUSTED", trusted), patched(
                    sealed, "RESULT_PATH", str(result_path)), patched(
                    sealed, "_load_verified_reader", lambda: FailedReader()):
                with self.assertRaisesRegex(RuntimeError, "synthetic reader failure"):
                    sealed.read_once()
            claim_path = Path(str(result_path) + sealed.CLAIM_SUFFIX)
            self.assertTrue(claim_path.is_file())
            self.assertEqual(json.loads(claim_path.read_text())["status"], "claimed")

            class NoBind:
                def bind_inputs(self, *args, **kwargs):
                    raise AssertionError("bind_inputs called on retry")

            with patched(sealed, "TRUSTED", trusted), patched(
                    sealed, "RESULT_PATH", str(result_path)), patched(sealed, "reader_lib", NoBind()):
                with self.assertRaisesRegex(ValueError, "one-shot"):
                    sealed.read_once()

    def test_preexisting_claim_refuses_before_binding(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root, status_path, reservation_path, trusted, result_path = fixture(base)
            claim_path = Path(str(result_path) + sealed.CLAIM_SUFFIX)
            claim_path.write_text("claimed\n")
            class NoBind:
                def bind_inputs(self, *args, **kwargs):
                    raise AssertionError("bind_inputs called with a preexisting claim")

            with patched(sealed, "TRUSTED", trusted), patched(
                    sealed, "RESULT_PATH", str(result_path)), patched(sealed, "reader_lib", NoBind()):
                with self.assertRaisesRegex(ValueError, "one-shot"):
                    sealed.read_once()

    def test_reader_source_pin_loads_real_reader(self):
        module = sealed._load_verified_reader()
        self.assertEqual(module.__name__, "s61dev_sealed_reader")
        self.assertEqual(hashlib.sha256(sealed.READER_PATH.read_bytes()).hexdigest(), sealed.READER_SHA256)

    def test_reader_helper_source_pin_refuses_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            altered = Path(raw).resolve() / "reader_lib.py"
            altered.write_bytes(sealed.READER_LIB_PATH.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "reader_lib source SHA256 mismatch"):
                sealed._load_verified_module(altered, sealed.READER_LIB_SHA256, "reader_lib")


if __name__ == "__main__":
    unittest.main()
