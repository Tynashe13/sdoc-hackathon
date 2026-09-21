"""The validation lab as regression tests: seeded fuzzing of the checker and the labelling tools.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from compare import compare
from validation import fuzz, fuzz_docs, label_packet, score_labels

RESULTS = json.loads(Path("results.json").read_text())["results"]


class TestWeightBoundary(unittest.TestCase):
    """The bug the fuzzer found: weights 1 kg apart were treated as the same."""

    def check(self, si, bl):
        return fuzz.verdict("gross_weight_kg", si, bl)

    def test_one_kilo_apart_is_a_mismatch(self):
        self.assertEqual(self.check("131,058 KG", "131,059 KG"), "mismatch")
        self.assertEqual(self.check("131,058 KG", "131,057 KG"), "mismatch")

    def test_rounding_of_the_same_weight_still_matches(self):
        self.assertEqual(self.check("131,058 KG", "131,058.4 KG"), "match")
        self.assertEqual(self.check("131,058 KG", "131.058 MT"), "match")
        self.assertEqual(self.check("131,058 KG", "131058"), "match")


class TestFieldFuzz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = fuzz.run(seed=7)
        cls.tot = fuzz.summarise(cls.rep)

    def test_no_false_alarm_on_formatting_changes(self):
        n, ok = self.tot["benign"]
        self.assertGreater(n, 1000)
        self.assertEqual(ok, n, [r for r in self.rep["rows"] if r["kind"] == "benign" and r["ok"] != r["n"]])

    def test_every_real_defect_is_caught(self):
        n, ok = self.tot["defect"]
        self.assertGreater(n, 1000)
        self.assertEqual(ok, n, [r for r in self.rep["rows"] if r["kind"] == "defect" and r["ok"] != r["n"]])

    def test_blanked_values_go_to_a_person(self):
        n, ok = self.tot["missing"]
        self.assertGreater(n, 500)
        self.assertEqual(ok, n)

    def test_same_seed_same_cases(self):
        self.assertEqual(fuzz.run(seed=7)["rows"], self.rep["rows"])


class TestDocumentFuzz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = fuzz_docs.run(seed=7)
        cls.tot = fuzz_docs.summarise(cls.rep)

    def test_layout_changes_do_not_change_the_verdict(self):
        n, ok = self.tot["layout"]
        self.assertGreater(n, 500)
        self.assertEqual(ok, n)

    def test_unknown_wording_is_escalated_never_silently_ok(self):
        n, ok = self.tot["failsafe"]
        self.assertGreater(n, 200)
        self.assertEqual(ok, n)

    def test_injected_defects_are_found_in_the_right_field(self):
        n, ok = self.tot["defect"]
        self.assertGreater(n, 1000)
        self.assertEqual(ok, n, [r for r in self.rep["rows"] if r["kind"] == "defect" and r["ok"] != r["n"]])


class TestLabelPacket(unittest.TestCase):
    def test_sample_is_stratified_and_repeatable(self):
        ids = label_packet.pick(RESULTS, 60, seed=7)
        self.assertEqual(len(ids), 60)
        self.assertEqual(len(set(ids)), 60)
        self.assertEqual(ids, label_packet.pick(RESULTS, 60, seed=7))
        kinds = {RESULTS[i]["status"] for i in ids if RESULTS[i]["category"] == "BL_COMPARISON"}
        self.assertEqual(kinds, {"OK", "MISMATCH", "NEEDS_REVIEW"})
        reasons = {RESULTS[i]["review_reason"] for i in ids if RESULTS[i]["status"] == "NEEDS_REVIEW"}
        self.assertEqual(reasons, set(label_packet.REASONS))

    def test_packet_does_not_show_the_systems_answers(self):
        from loader import Inbox
        page = label_packet.item_html(0, Inbox("data"), "email_004")
        for leaked in ("MISMATCH detected", "defect_fields", "No mismatch detected", "mismatches found"):
            self.assertNotIn(leaked, page)


class TestScoreLabels(unittest.TestCase):
    def write(self, name, rows):
        path = Path(self.tmp.name) / name
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["labeller", "email_id", "category", "verdict", "fields", "reason"])
            w.writerows(rows)
        return str(path)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ids = label_packet.pick(RESULTS, 60, seed=7)

    def perfect(self, who):
        rows = []
        for e in self.ids:
            s = score_labels.system_view(RESULTS[e])
            rows.append([who, e, s["category"], s["verdict"], s["fields"], s["reason"]])
        return rows

    def test_a_labeller_who_matches_the_system_scores_100_percent(self):
        rep = score_labels.score([self.write("a.csv", self.perfect("a"))])
        for key in ("category", "verdict", "fields", "reason"):
            self.assertEqual(rep[key]["agree"], rep[key]["n"], key)
        self.assertEqual(rep["defects"]["missed"] + rep["defects"]["false_alarms"], 0)
        self.assertEqual(rep["disagreements"], [])

    def test_a_disagreement_is_reported(self):
        rows = self.perfect("a")
        i = next(i for i, r in enumerate(rows) if r[3] == "MISMATCH")
        rows[i][3], rows[i][4] = "OK", ""                        # the human says OK where the system says MISMATCH
        rep = score_labels.score([self.write("a.csv", rows)])
        self.assertEqual(rep["defects"]["false_alarms"], 1)
        self.assertEqual([d["email"] for d in rep["disagreements"]], [rows[i][1]])

    def test_kappa_and_split_labellers(self):
        a, b = self.perfect("a"), self.perfect("b")
        b[0][2] = "SPAM" if b[0][2] != "SPAM" else "GENERAL"     # b disagrees with a on one email's category
        rep = score_labels.score([self.write("a.csv", a), self.write("b.csv", b)])
        self.assertIn(a[0][1], rep["human_disagreements"])
        self.assertIn(a[0][1], rep["unresolved"])                # 1 vs 1: no majority, left out of the scores
        self.assertLess(rep["human_agreement"][0]["category_kappa"], 1.0)
        self.assertEqual(score_labels.kappa(["x", "y", "x", "y"], ["x", "y", "x", "y"]), 1.0)
        self.assertAlmostEqual(score_labels.kappa(["x", "x", "y", "y"], ["x", "y", "x", "y"]), 0.0)


if __name__ == "__main__":
    unittest.main()
