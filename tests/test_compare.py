"""Comparator regression tests: the four real-world gaps, plus what must NOT change.

Each row is (SI value, BL value, expected verdict).  "match" means the two documents
agree on that field; "mismatch" means a human should be told.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import unittest

from compare import compare, field_table, normalise


def verdict(field, si, bl):
    mismatches, missing = compare({field: si}, {field: bl})
    if any(m["field"] == field for m in mismatches):
        return "mismatch"
    return "missing" if any(f == field for _, f in missing) else "match"


class Table(unittest.TestCase):
    field = None
    rows = ()

    def test_rows(self):
        for si, bl, expected in self.rows:
            with self.subTest(si=si, bl=bl):
                self.assertEqual(verdict(self.field, si, bl), expected)


class TestContainers(Table):
    field = "container_count"
    rows = [
        ("6 x 40'HC", "6 x 40'HC", "match"),
        ("6 x 40'HC", "6 x 40HC", "match"),              # apostrophe / spacing
        ("6 X 40' HC", "6 x 40HQ", "match"),             # HQ is another name for high cube
        ("6 x 40'HC", "6 x 20'GP", "mismatch"),          # size AND type differ (was a false match)
        ("6 x 40'HC", "6 x 20'HC", "mismatch"),          # size only
        ("6 x 40'HC", "6 x 40'GP", "mismatch"),          # type only
        ("6 x 40'HC", "5 x 40'HC", "mismatch"),          # count only
        ("3 x 40'FCL", "3 x 40'HC", "match"),            # FCL is a load type, not a container type
        ("3 x 40'FCL", "3 x 20'FCL", "mismatch"),
        ("6", "6 x 40'HC", "match"),                     # one side gives no size: compare counts
        ("6", "5 x 40'HC", "mismatch"),
        ("3 x 20'GP + 3 x 40'HC", "3 x 40'HC + 3 x 20'GP", "match"),   # order does not matter
        ("3 x 20'GP + 3 x 40'HC", "6 x 40'HC", "mismatch"),            # same total, different boxes
        ("N/A", "6 x 40'HC", "missing"),
    ]


class TestWeights(Table):
    field = "gross_weight_kg"
    rows = [
        ("131,058 KG", "131,058 KG", "match"),
        ("131,058 KG", "131,058.4 KG", "match"),         # rounding noise
        ("131,058 KG", "131.058 MT", "match"),           # metric tonnes (was a false alarm)
        ("131,058 KG", "131,058 KGS", "match"),
        ("1.5 MT", "1,500 KG", "match"),
        ("100,000 KG", "220,462 LBS", "match"),          # pounds convert to kilograms
        ("131,058", "131,058 KG", "match"),              # no unit means kilograms
        ("131,058 KG", "131.058 KG", "match"),           # European thousands separator
        ("131,058 KG", "131,085 KG", "mismatch"),        # transposed digits must still be caught
        ("131,058 KG", "138,000 KG", "mismatch"),
        ("131,058 KG", "13,058 KG", "mismatch"),            # dropped digit
        ("131,058 KG", "289,000 LBS", "mismatch"),       # about 131,089 kg: 31 kg out
        ("131,058 KG", "131,058.7 KG", "mismatch"),      # beyond rounding tolerance
        ("N/A", "131,058 KG", "missing"),
    ]


class TestNames(Table):
    field = "consignee"
    rows = [
        ("EAST BRIGHT FZ-LLC", "EAST BRIGHT FZ LLC", "match"),
        ("ACME PTE. LTD.", "ACME PTE LTD", "match"),
        ("ACME PTE LTD", "ACME PRIVATE LIMITED", "match"),     # was a false alarm
        ("ACME PVT. LTD.", "ACME PTE LTD", "match"),
        ("ACME CO., LTD", "ACME COMPANY LIMITED", "match"),
        ("ACME SDN BHD", "ACME SDN. BERHAD", "match"),
        ("ACME & SONS INC", "ACME AND SONS INCORPORATED", "match"),
        ("ACME CORP", "ACME CORPORATION", "match"),
        ("ACME S.A.", "ACME SA", "match"),
        ("MÜLLER GMBH", "MULLER GMBH", "match"),               # accents
        ("acme pte ltd", "ACME PTE LTD", "match"),
        ("ACME TRADING", "ACME TRADING CO", "mismatch"),       # a reviewer should see this one
        ("ACME LIMITED", "ACME INC", "mismatch"),              # different legal form
        ("EAST BRIGHT FZ-LLC", "UAB NOVAKOPA", "mismatch"),
        ("ACME PTE LTD | 1 MAIN ST", "ACME PTE LTD", "match"),  # address after "|" is ignored
    ]


class TestPorts(Table):
    field = "port_of_loading"
    rows = [
        ("NANTONG, CHINA (CNNTG)", "NANTONG, CHINA (CNNTG)", "match"),
        ("NANTONG, CHINA (CNNTG)", "NANTONG, CHINA (CNSHA)", "mismatch"),   # same name, other code
        ("NANTONG, CHINA (CNNTG)", "NANTONG, CHINA", "match"),              # one side has no code
        ("PORT KLANG (MYPKG), MALAYSIA (MY)", "PORT KLANG, MALAYSIA", "match"),
        ("MOMBASA, KENYA (KEMBA)", "TUTICORIN, INDIA (KEMBA)", "mismatch"), # different port, same code
        ("NHAVA SHEVA (INNSA)", "JAWAHARLAL NEHRU (INNSA)", "mismatch"),    # alias: escalate, do not guess
        ("SHANGHAI, CHINA (CNSHA)", "NINGBO, CHINA (CNNGB)", "mismatch"),
        ("SHANGHAI, CHINA", "NINGBO, CHINA", "mismatch"),
        ("JEBEL ALI (DUBAI)", "JEBEL ALI (DUBAI)", "match"),                # not a port code
        ("JEBEL ALI (DUBAI)", "JEBEL ALI (HAIFA)", "mismatch"),
        ("TBA", "NINGBO, CHINA", "missing"),
    ]


class TestPlumbing(unittest.TestCase):
    def test_missing_values_normalise_to_none(self):
        for field in ("shipper", "port_of_loading", "container_count", "gross_weight_kg"):
            for raw in (None, "", "N/A", "TBC", "____", "-"):
                self.assertIsNone(normalise(field, raw), (field, raw))

    def test_field_table_uses_the_same_rules(self):
        si = {"container_count": "6 x 40'HC", "gross_weight_kg": "131,058 KG"}
        bl = {"container_count": "6 x 20'GP", "gross_weight_kg": "131.058 MT"}
        status = {r["field"]: r["status"] for r in field_table(si, bl)}
        self.assertEqual(status["container_count"], "mismatch")
        self.assertEqual(status["gross_weight_kg"], "match")

    def test_mismatch_reports_the_original_text(self):
        mism, _ = compare({"container_count": "6 x 40'HC"}, {"container_count": "6 x 20'GP"})
        self.assertEqual(mism, [{"field": "container_count", "si": "6 x 40'HC", "bl": "6 x 20'GP"}])


if __name__ == "__main__":
    unittest.main()
