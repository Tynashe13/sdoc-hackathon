"""Every value the app shows comes with the exact document line it was read from.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import json
import unittest
from pathlib import Path

from extract import extract_evidence, extract_raw, find_line
from loader import Inbox
from readers import read_attachment

DATA = "data"
SAMPLE = """SHIPPING INSTRUCTION
Shipper: ACME PTE LTD
    1 Harbour Road
Consignee (Non-Negotiable): BLUE STAR TRADING
Port of Loading (POL): SINGAPORE (SGSIN)
Gross Weight: 12,000 KG
"""


class TestExtractEvidence(unittest.TestCase):
    def test_value_comes_with_its_line_and_number(self):
        ev = extract_evidence(SAMPLE)
        self.assertEqual(ev["consignee"], {"value": "BLUE STAR TRADING", "line_no": 4,
                                           "line": "Consignee (Non-Negotiable): BLUE STAR TRADING"})
        self.assertEqual(ev["gross_weight_kg"]["line_no"], 6)

    def test_missing_field_has_no_evidence(self):
        self.assertIsNone(extract_evidence(SAMPLE)["notify_party"])

    def test_extract_raw_still_gives_plain_values(self):
        raw = extract_raw(SAMPLE)
        self.assertEqual(raw["shipper"], "ACME PTE LTD")
        self.assertIsNone(raw["container_count"])

    def test_find_line_locates_a_value_anywhere(self):
        self.assertEqual(find_line(SAMPLE, "sgsin")["line_no"], 5)
        self.assertIsNone(find_line(SAMPLE, "not in the document"))


class TestEveryQuoteIsVerbatim(unittest.TestCase):
    """Across all committed results: the quoted line is really line N of the named file,
    and it contains the value that is displayed."""

    @classmethod
    def setUpClass(cls):
        cls.results = json.loads(Path("results.json").read_text())["results"]
        cls.inbox = Inbox(DATA)
        cls.texts = {}

    def text(self, eid, doc):
        if (eid, doc) not in self.texts:
            path = next(p for p in Inbox(DATA).get(eid)["attachments"] if p.endswith("/" + doc))
            self.texts[(eid, doc)] = read_attachment(doc, self.inbox.read_bytes(path))
        return self.texts[(eid, doc)]

    def cells(self):
        for eid, res in self.results.items():
            for row in res.get("table") or []:
                for side in ("si", "bl"):
                    yield eid, row, side, row.get(side + "_evidence")

    def test_every_shown_value_has_a_quote(self):
        missing = [(eid, row["field"], side) for eid, row, side, ev in self.cells()
                   if row[side] is not None and ev is None]
        self.assertEqual(missing, [])

    def test_quotes_are_verbatim_lines_containing_the_value(self):
        checked = 0
        for eid, row, side, ev in self.cells():
            if not ev:
                continue
            lines = self.text(eid, ev["doc"]).splitlines()
            self.assertEqual(lines[ev["line_no"] - 1].strip(), ev["line"], f"{eid} {row['field']} {side}")
            norm = lambda s: " ".join(str(s).split()).lower()
            self.assertIn(norm(row[side]), norm(ev["line"]), f"{eid} {row['field']} {side}")
            checked += 1
        self.assertGreater(checked, 1000)


if __name__ == "__main__":
    unittest.main()
