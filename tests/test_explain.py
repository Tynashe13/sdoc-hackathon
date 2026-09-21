"""The AI-written plain-language reasons: grounded, batched, never deciding, and hidden when they go stale.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import explain
import llm

RESULTS = json.loads(Path("results.json").read_text(encoding="utf-8"))["results"]
MISMATCH = {"category": "BL_COMPARISON", "status": "MISMATCH", "table": [
    {"field": "consignee", "si": "EAST BRIGHT FZ-LLC", "bl": "UAB NOVAKOPA", "status": "mismatch"},
    {"field": "shipper", "si": "ACME PTE LTD", "bl": "ACME PTE LTD", "status": "match"}]}


class TestFacts(unittest.TestCase):
    def test_only_mismatches_and_review_cases_have_something_to_explain(self):
        self.assertEqual(explain.facts(MISMATCH), {"kind": "mismatch", "fields": [
            {"field": "consignee", "si": "EAST BRIGHT FZ-LLC", "bl": "UAB NOVAKOPA"}]})
        self.assertEqual(explain.facts({"category": "BL_COMPARISON", "status": "NEEDS_REVIEW",
                                        "review_reason": "missing_value", "detail": "SI: shipper"})["kind"], "review")
        self.assertIsNone(explain.facts({"category": "BL_COMPARISON", "status": "OK"}))
        self.assertIsNone(explain.facts({"category": "BL_COMPARISON", "status": "OK", "awaiting_documents": True}))
        self.assertIsNone(explain.facts({"category": "SPAM", "status": "OK"}))

    def test_the_fingerprint_changes_when_the_values_change(self):
        a = explain.facts(MISMATCH)
        b = explain.facts({**MISMATCH, "table": [{**MISMATCH["table"][0], "bl": "SOMEONE ELSE", "status": "mismatch"}]})
        self.assertEqual(explain.basis(a), explain.basis(dict(a)))
        self.assertNotEqual(explain.basis(a), explain.basis(b))

    def test_the_real_data_has_66_cases_to_explain(self):
        self.assertEqual(sum(1 for r in RESULTS.values() if explain.facts(r)), 66)


class TestGrounding(unittest.TestCase):
    F = explain.facts(MISMATCH)

    def test_a_sentence_that_mentions_the_values_is_kept(self):
        self.assertTrue(explain.grounded("The consignee differs: the SI names East Bright FZ-LLC but the BL says UAB Novakopa.", self.F))

    def test_a_generic_or_invented_sentence_is_rejected(self):
        self.assertFalse(explain.grounded("Something looks different between the two documents here.", self.F))
        self.assertFalse(explain.grounded("The consignee is Blue Star Trading, not the one on the BL.", self.F))

    def test_too_short_too_long_or_not_text_is_rejected(self):
        self.assertFalse(explain.grounded("Novakopa.", self.F))
        self.assertFalse(explain.grounded("UAB Novakopa " * 40, self.F))
        self.assertFalse(explain.grounded(None, self.F))

    def test_container_counts_are_grounded_on_their_numbers(self):
        f = explain.facts({"category": "BL_COMPARISON", "status": "MISMATCH", "table": [
            {"field": "container_count", "si": "6 x 40'HC", "bl": "7 x 40'HC", "status": "mismatch"}]})
        self.assertTrue(explain.grounded("The SI lists 6 containers but the BL lists 7; the size is the same.", f))
        self.assertFalse(explain.grounded("The number of containers on the two documents does not agree.", f))

    def test_weights_are_recognised_whatever_the_formatting(self):
        f = explain.facts({"category": "BL_COMPARISON", "status": "MISMATCH", "table": [
            {"field": "gross_weight_kg", "si": "131,058 KG", "bl": "131,059 KG", "status": "mismatch"}]})
        self.assertTrue(explain.grounded("The weights are 1 kg apart: 131,058 on the SI against 131,059 on the BL.", f))


class TestRun(unittest.TestCase):
    def test_all_cases_are_asked_in_three_requests_and_grounded_answers_are_kept(self):
        calls = []

        def fake(prompt):
            calls.append(prompt)
            ids = [line.split(":")[0] for line in prompt.splitlines() if line.startswith("email_")]
            return {eid: f"Explains {eid}: the values named in {eid} are different." for eid in ids}

        found, cases, dropped = explain.run(RESULTS, fake)
        self.assertEqual((cases, len(calls)), (66, 3))
        self.assertTrue(all(len(c.splitlines()) <= explain.BATCH + 6 for c in calls))
        # the fake mentions no real values, so mismatches are dropped and the review cases are kept
        reviews = sum(1 for r in RESULTS.values() if (explain.facts(r) or {}).get("kind") == "review")
        self.assertEqual(len(found), reviews)
        self.assertEqual(dropped, 66 - reviews)

    def test_the_prompt_forbids_deciding_and_only_contains_the_facts(self):
        text = explain.prompt([("email_004", explain.facts(MISMATCH))])
        self.assertIn("Do not decide", text)
        self.assertIn('the SI says "EAST BRIGHT FZ-LLC" and the BL says "UAB NOVAKOPA"', text)

    def test_a_failed_call_means_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "explanations.json"
            quiet = [mock.patch.object(sys, "stderr", io.StringIO()), mock.patch.object(sys, "stdout", io.StringIO())]
            for q in quiet:
                q.start()
            self.addCleanup(lambda: [q.stop() for q in quiet])

            def failing(prompt):
                llm.FAILED.append("service unavailable")
                return None

            self.addCleanup(llm.FAILED.clear)
            with mock.patch.dict(os.environ, {"EXPLANATIONS_FILE": str(out)}), \
                    mock.patch.object(llm, "enabled", return_value=True), mock.patch.object(llm, "ask_json", failing), \
                    mock.patch.object(llm, "TIMEOUT_MS", llm.TIMEOUT_MS), mock.patch.object(llm, "MAX_CALLS", None):
                code = explain.main()
            self.assertEqual(code, 1)
            self.assertFalse(out.exists())


def run_app(code, explanations):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "explanations.json"
        if explanations is not None:
            path.write_text(json.dumps({"explanations": explanations}), encoding="utf-8")
        env = {**os.environ, "USE_LLM": "0", "REVIEWS_PATH": str(Path(tmp) / "r.json"), "EXPLANATIONS_FILE": str(path)}
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    if out.returncode:
        raise AssertionError(out.stderr[-1500:])
    return json.loads(out.stdout.strip().splitlines()[-1])


CHECK = '''
import csv, io, json
import app
c = app.app.test_client()
d = c.get("/api/emails/email_004").get_json()
listed = next(e for e in c.get("/api/emails").get_json()["emails"] if e["id"] == "email_004")
rows = {x["email_id"]: x for x in csv.DictReader(io.StringIO(c.get("/api/report.csv").get_data(as_text=True)))}
si = {r["field"]: r["si"] for r in d["table"]}
fixed = c.post("/api/emails/email_004/recheck", json={"si": si, "bl": si, "note": "corrected"}).get_json()
print(json.dumps({"text": d["ai_explanation"], "chip": listed["ai"], "note": d["ai_notes"], "csv": rows["email_004"]["why (plain language)"],
                  "csv_ai": rows["email_004"]["ai_assisted"], "after_correction": fixed["ai_explanation"]}))
'''


class TestAppShowsTheExplanation(unittest.TestCase):
    def test_a_matching_explanation_is_shown_tagged_and_used_in_the_csv_then_hidden_after_a_correction(self):
        f = explain.facts(RESULTS["email_004"])
        text = "The consignee and notify party differ: the SI says East Bright FZ-LLC, the BL says UAB Novakopa."
        r = run_app(CHECK, {"email_004": {"text": text, "basis": explain.basis(f)}})
        self.assertEqual(r["text"], text)
        self.assertTrue(r["chip"])
        self.assertTrue(any("wrote the plain-language explanation" in n for n in r["note"]))
        self.assertEqual((r["csv"], r["csv_ai"]), (text, "yes"))
        self.assertIsNone(r["after_correction"])

    def test_an_explanation_written_for_different_values_is_ignored(self):
        r = run_app(CHECK, {"email_004": {"text": "Old sentence about UAB Novakopa here.", "basis": "stale"}})
        self.assertIsNone(r["text"])
        self.assertFalse(r["chip"])
        self.assertIn("Consignee: different company or name", r["csv"])

    def test_the_app_works_without_an_explanations_file(self):
        r = run_app(CHECK, None)
        self.assertIsNone(r["text"])
        self.assertEqual(r["csv_ai"], "no")


if __name__ == "__main__":
    unittest.main()
