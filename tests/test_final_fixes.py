"""Retry never downgrades a good result, the CSV explains each mismatch, and the awaiting bucket has a name.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import llm


def run_app_script(code):
    """Run a snippet with the web app imported, in its own process, with a throw-away reviews file."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "USE_LLM": "0", "REVIEWS_PATH": str(Path(tmp) / "reviews.json")}
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    if out.returncode:
        raise AssertionError(out.stderr[-1500:])
    return json.loads(out.stdout.strip().splitlines()[-1])


PRELUDE = '''
import json
import app, llm, pipeline
c = app.app.test_client()
ai_result = dict(app.STATE["results"]["email_512"], ai_assisted=True,
                 ai_notes=["scan read by vision model; needs human confirmation"])
app.STATE["results"]["email_512"] = ai_result
weaker = {"category": "BL_COMPARISON", "decided_by": "rule", "status": "NEEDS_REVIEW", "review_reason": "unreadable",
          "has_defect": False, "defect_fields": [], "detail": "x", "mismatches": [], "form": None,
          "ai_assisted": False, "ai_notes": []}
'''


class TestRetryKeepsTheSavedResult(unittest.TestCase):
    def test_a_busy_gemini_does_not_replace_an_ai_result_or_wipe_the_reviewers_decision(self):
        r = run_app_script(PRELUDE + '''
def failing(inbox, email):
    llm.FAILED.append("service unavailable")
    return weaker
pipeline.process_email = failing
c.post("/api/emails/email_512/resolve", json={"note": "reviewer"})
d = c.post("/api/emails/email_512/retry").get_json()
print(json.dumps({"kept": d.get("kept"), "ai": d["ai"], "same": app.STATE["results"]["email_512"] is ai_result,
                  "review": bool(d.get("review"))}))
''')
        self.assertEqual(r, {"kept": True, "ai": True, "same": True, "review": True})

    def test_a_working_retry_still_replaces_the_result(self):
        r = run_app_script(PRELUDE + '''
pipeline.process_email = lambda inbox, email: weaker
d = c.post("/api/emails/email_512/retry").get_json()
print(json.dumps({"kept": d.get("kept"), "ai": d["ai"], "replaced": app.STATE["results"]["email_512"] is weaker}))
''')
        self.assertEqual(r, {"kept": None, "ai": False, "replaced": True})


class TestCsvExplainsEachMismatch(unittest.TestCase):
    def test_every_row_has_a_plain_language_reason(self):
        r = run_app_script('''
import csv, io, json
import app
rows = list(csv.DictReader(io.StringIO(app.app.test_client().get("/api/report.csv").get_data(as_text=True))))
by = {x["email_id"]: x for x in rows}
weights = [x for x in rows if "gross_weight_kg" in x["mismatched_fields"]]
print(json.dumps({"col": "why (plain language)" in rows[0],
  "mismatch": by["email_004"]["why (plain language)"],
  "review": by["email_516"]["why (plain language)"],
  "awaiting": by["email_003"]["why (plain language)"],
  "ok": by["email_001"]["why (plain language)"],
  "weight_rows": len(weights),
  "weight_text": all("weights differ by" in x["why (plain language)"] for x in weights),
  "every_mismatch_explained": all(x["why (plain language)"] for x in rows if x["result"] in ("Mismatch", "Needs review"))}))
''')
        self.assertTrue(r["col"])
        self.assertEqual(r["mismatch"], "Consignee: different company or name; Notify party: different company or name")
        self.assertEqual(r["review"], "A required value is blank or not stated")
        self.assertIn("nothing to compare", r["awaiting"])
        self.assertEqual(r["ok"], "")
        self.assertGreater(r["weight_rows"], 0)
        self.assertTrue(r["weight_text"] and r["every_mismatch_explained"])


class TestQuotaBlockExpires(unittest.TestCase):
    def test_a_long_running_server_tries_gemini_again_after_the_cooldown(self):
        import io
        import time
        quiet = mock.patch.object(sys, "stderr", io.StringIO())
        quiet.start()
        self.addCleanup(quiet.stop)

        class Client:
            calls = 0

            class models:
                @staticmethod
                def generate_content(**kw):
                    Client.calls += 1
                    return type("Reply", (), {"text": '{"ok": true}'})()

        with mock.patch.object(llm, "_get_client", return_value=Client), \
                mock.patch.object(llm, "CACHE", Path(tempfile.mkdtemp())), \
                mock.patch.object(llm, "_quota_hit", True), \
                mock.patch.object(llm, "_quota_hit_at", time.time()):
            self.assertIsNone(llm.ask_json("inside the cooldown"))         # still blocked
            self.assertEqual(Client.calls, 0)
            llm._quota_hit_at = time.time() - llm.QUOTA_COOLDOWN - 1        # the cooldown has passed
            self.assertEqual(llm.ask_json("after the cooldown"), {"ok": True})
            self.assertEqual(Client.calls, 1)


class TestScreen(unittest.TestCase):
    PAGE = Path("static/index.html").read_text(encoding="utf-8")

    def test_the_awaiting_bucket_has_a_name_and_a_one_line_explanation(self):
        self.assertIn("id:'awaiting', label:'Awaiting draft BL'", self.PAGE)
        self.assertIn("nothing to compare yet", self.PAGE)

    def test_a_kept_result_tells_the_user(self):
        self.assertIn("Gemini is busy, so the saved result was kept.", self.PAGE)

    def test_the_readme_links_the_overview_pdf(self):
        self.assertIn("docs/SDOC-Check-Overview.pdf", Path("README.md").read_text(encoding="utf-8"))
        self.assertTrue(Path("docs/SDOC-Check-Overview.pdf").exists())


if __name__ == "__main__":
    unittest.main()
