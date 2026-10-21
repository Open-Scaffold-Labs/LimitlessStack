"""Implementation scenarios for main-agent execution; no network operations."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("log_exports", Path(__file__).with_name("notebooklm_log_exports.py"))
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def log_entry(index, words=6):
    return (f"## [2026-10-{index:02d}] build | entry {index}\n" + "body " * words + "\n").encode()


class LogExports(unittest.TestCase):
    def setUp(self):
        self.data = b"# Log\n\n" + b"".join(log_entry(i) for i in range(1, 7))
        self.limit = 34

    def test_lossless_complete_entries(self):
        p = module.plan(self.data, max_words=self.limit)
        self.assertEqual(b"".join(p.files.values()), self.data)
        self.assertGreater(len(p.files), 1)
        self.assertTrue(all(len(v.decode().split()) <= self.limit for v in p.files.values()))
        self.assertTrue(all(v.startswith(b"## [") for v in list(p.files.values())[1:]))

    def test_append_only_updates_recent(self):
        p = module.plan(self.data, max_words=self.limit)
        q = module.plan(self.data + log_entry(7), p.metadata, self.limit)
        for archive in p.metadata["archives"]:
            self.assertEqual(q.files[archive["name"]], p.files[archive["name"]])
        self.assertEqual(b"".join(q.files.values()), self.data + log_entry(7))
        self.assertEqual(q.metadata["archives"][:len(p.metadata["archives"])], p.metadata["archives"])

    def test_older_change_is_rejected(self):
        p = module.plan(self.data, max_words=self.limit)
        with self.assertRaisesRegex(module.LogExportError, "sealed history changed"):
            module.plan(self.data.replace(b"body", b"edit", 1), p.metadata, self.limit)

    def test_recent_can_be_corrected(self):
        p = module.plan(self.data, max_words=self.limit)
        recent_start = p.metadata["recent"]["start"]
        edited = self.data[:recent_start] + self.data[recent_start:].replace(b"body", b"edit", 1)
        q = module.plan(edited, p.metadata, self.limit)
        self.assertEqual(b"".join(q.files.values()), edited)
        self.assertEqual(q.metadata["archives"], p.metadata["archives"])

    def test_rollover_seals_another_archive(self):
        p = module.plan(self.data, max_words=self.limit)
        expanded = self.data + b"".join(log_entry(i) for i in range(7, 14))
        q = module.plan(expanded, p.metadata, self.limit)
        self.assertGreater(len(q.metadata["archives"]), len(p.metadata["archives"]))
        self.assertEqual(b"".join(q.files.values()), expanded)

    def test_oversized_entry_is_rejected(self):
        with self.assertRaisesRegex(module.LogExportError, "entry.*was not split"):
            module.plan(log_entry(1, 100), max_words=self.limit)

    def test_invalid_utf8_is_rejected(self):
        with self.assertRaisesRegex(module.LogExportError, "UTF-8"):
            module.plan(b"\xff")

    def test_no_headings_under_limit(self):
        p = module.plan(b"tiny log", max_words=10)
        self.assertEqual(p.files, {"log-recent.md": b"tiny log"})

    def test_no_headings_over_limit(self):
        with self.assertRaises(module.LogExportError):
            module.plan(b"one two three", max_words=2)

    def test_fenced_heading_is_not_a_boundary(self):
        data = log_entry(1) + b"```md\n## [2026-10-02] fake\n```\n" + log_entry(3)
        p = module.plan(data, max_words=30)
        self.assertEqual(b"".join(p.files.values()), data)
        self.assertFalse(any(v.startswith(b"## [2026-10-02]") for v in p.files.values()))

    def test_unicode_and_crlf_are_byte_preserved(self):
        data = self.data.replace(b"\n", b"\r\n").replace(b"body", "café".encode())
        p = module.plan(data, max_words=self.limit)
        self.assertEqual(b"".join(p.files.values()), data)

    def test_changed_limit_rejected(self):
        p = module.plan(self.data, max_words=self.limit)
        with self.assertRaisesRegex(module.LogExportError, "max_words changed"):
            module.plan(self.data, p.metadata, 35)

    def test_publish_idempotent_mtimes_and_metadata(self):
        p = module.plan(self.data, max_words=self.limit)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); metadata = root / "manifest.json"
            paths = module.publish(root / "exports", metadata, p)
            before = {k: v.stat().st_mtime_ns for k, v in paths.items()}
            meta_before = metadata.stat().st_mtime_ns
            module.publish(root / "exports", metadata, p)
            self.assertEqual(before, {k: v.stat().st_mtime_ns for k, v in paths.items()})
            self.assertEqual(meta_before, metadata.stat().st_mtime_ns)
            self.assertEqual(json.loads(metadata.read_text()), p.metadata)

    def test_interrupted_publish_recovers_from_prior_metadata(self):
        p = module.plan(self.data, max_words=self.limit)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); metadata = root / "manifest.json"; out = root / "exports"
            module.publish(out, metadata, p)
            expanded = self.data + b"".join(log_entry(i) for i in range(7, 11))
            q = module.plan(expanded, p.metadata, self.limit)
            original = module._atomic_write_if_changed
            def fail_metadata(path, data):
                if path == metadata:
                    raise OSError("simulated interruption")
                return original(path, data)
            with mock.patch.object(module, "_atomic_write_if_changed", side_effect=fail_metadata):
                with self.assertRaisesRegex(OSError, "simulated interruption"):
                    module.publish(out, metadata, q)
            self.assertEqual(json.loads(metadata.read_text()), p.metadata)
            retry = module.plan(expanded, json.loads(metadata.read_text()), self.limit)
            module.publish(out, metadata, retry)
            self.assertEqual(b"".join((out / name).read_bytes() for name in retry.files), expanded)

    def test_tampered_metadata_rejected(self):
        p = module.plan(self.data, max_words=self.limit)
        p.metadata["archives"][0]["end"] += 1
        with self.assertRaises(module.LogExportError):
            module.plan(self.data, p.metadata, self.limit)

    def test_empty_log(self):
        p = module.plan(b"", max_words=10)
        self.assertEqual(p.files, {"log-recent.md": b""})


if __name__ == "__main__":
    unittest.main(verbosity=2)
