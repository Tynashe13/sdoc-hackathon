"""results.json must match what the code produces, and must go stale when the data changes.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import llm
import pipeline
import snapshot

DATA = "data"
RESULTS = "results.json"


class TestCommittedSnapshot(unittest.TestCase):
    def test_snapshot_is_current(self):
        self.assertIsNotNone(
            snapshot.load(RESULTS, DATA),
            "results.json does not match this checkout. If you did not change the data or the checking "
            "code, a data file was probably damaged by line-ending conversion (see .gitattributes): "
            "restore data/attachments from Git. Only if you changed them on purpose, run python precompute.py")

    def test_snapshot_equals_a_live_run(self):
        snap = json.loads(Path(RESULTS).read_text())
        if snap["ai"]:
            self.skipTest("this snapshot includes Gemini output, which is not reproducible")
        with mock.patch.object(llm, "enabled", return_value=False):
            live = json.loads(json.dumps(pipeline.run(DATA)))
        self.assertEqual(live, snap["results"])


class TestFingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        (self.data / "inbox").mkdir(parents=True)
        (self.data / "attachments").mkdir()
        (self.data / "inbox" / "email_001.json").write_text('{"email_id": "email_001"}\n')
        (self.data / "attachments" / "email_001_SI.txt").write_text("Shipper: ACME\n")
        self.out = Path(self.tmp.name) / "results.json"
        snapshot.save(self.out, self.data, {"email_001": {"status": "OK"}})

    def test_matching_snapshot_loads(self):
        self.assertEqual(snapshot.load(self.out, self.data), {"email_001": {"status": "OK"}})

    def test_changed_inbox_makes_it_stale(self):
        (self.data / "inbox" / "email_001.json").write_text('{"email_id": "email_001", "x": 1}\n')
        self.assertIsNone(snapshot.load(self.out, self.data))

    def test_changed_attachment_makes_it_stale(self):
        (self.data / "attachments" / "email_001_SI.txt").write_text("Shipper: OTHER\n")
        self.assertIsNone(snapshot.load(self.out, self.data))

    def test_added_attachment_makes_it_stale(self):
        (self.data / "attachments" / "email_001_BL.txt").write_text("Shipper: ACME\n")
        self.assertIsNone(snapshot.load(self.out, self.data))

    def test_windows_line_endings_do_not_matter(self):
        (self.data / "attachments" / "email_001_SI.txt").write_bytes(b"Shipper: ACME\r\n")
        self.assertIsNotNone(snapshot.load(self.out, self.data))

    def test_missing_or_corrupt_file_is_ignored(self):
        self.assertIsNone(snapshot.load(Path(self.tmp.name) / "nope.json", self.data))
        self.out.write_text("{not json")
        self.assertIsNone(snapshot.load(self.out, self.data))


if __name__ == "__main__":
    unittest.main()
