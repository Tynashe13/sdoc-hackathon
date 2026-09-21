"""The Test lab: a document opened with the lines every compared value was read from marked.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json
import app

c = app.app.test_client()
out = {}
eid = next(i for i, r in app.STATE["results"].items() if r.get("status") == "MISMATCH" and r.get("table"))
detail = c.get(f"/api/emails/{eid}").get_json()
out["eid"] = eid
checks = []
for f in detail["files"]:
    lab = c.get(f"/api/emails/{eid}/lab/{f['name']}").get_json()
    for m in lab["marks"]:
        row = next(r for r in detail["table"] if r["field"] == m["field"])
        ev = row["si_evidence" if m["side"] == "SI" else "bl_evidence"]
        checks.append([lab["lines"][m["line_no"] - 1].strip() == ev["line"], m["status"] == row["status"]])
    out.setdefault("kinds", []).append([lab["kind"], len(lab["lines"]), len(lab["marks"])])
out["marks_match_the_quoted_lines"] = checks
lab = None
for i, r in app.STATE["results"].items():
    if r.get("review_reason") == "unreadable":
        for path in app.EMAILS[i]["attachments"]:
            got = c.get(f"/api/emails/{i}/lab/{path.rsplit('/', 1)[-1]}").get_json()
            if got["kind"] == "scan":
                lab = got
                break
    if lab:
        break
out["scan"] = [lab["kind"], lab["image"].endswith("?render=png"), bool(lab["message"])] if lab else None
out["wrong_name"] = c.get(f"/api/emails/{eid}/lab/nothing.txt").status_code
out["wrong_email"] = c.get("/api/emails/nope/lab/x.txt").status_code
print("RESULT " + json.dumps(out))
'''


class TestTestLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, "USE_LLM": "0", "REVIEWS_PATH": os.path.join(tempfile.mkdtemp(), "r.json"),
               "PYTHONIOENCODING": "utf-8"}
        env.pop("SUPABASE_URL", None)
        proc = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, cwd=ROOT, env=env,
                              encoding="utf-8")
        line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
        assert line, proc.stderr[-2000:]
        cls.out = json.loads(line[len("RESULT "):])

    def test_a_document_opens_with_its_full_text_and_marked_lines(self):
        for kind, lines, marks in self.out["kinds"]:
            self.assertEqual(kind, "text")
            self.assertGreater(lines, 0)
        self.assertGreater(sum(m for _, _, m in self.out["kinds"]), 0)

    def test_every_mark_sits_on_the_exact_line_that_was_quoted_and_has_the_rows_status(self):
        self.assertTrue(self.out["marks_match_the_quoted_lines"])
        self.assertTrue(all(all(pair) for pair in self.out["marks_match_the_quoted_lines"]))

    def test_a_scan_shows_the_page_and_says_why_there_are_no_marks(self):
        self.assertEqual(self.out["scan"], ["scan", True, True])

    def test_unknown_documents_and_emails_are_not_found(self):
        self.assertEqual((self.out["wrong_name"], self.out["wrong_email"]), (404, 404))

    def test_the_page_has_the_button_the_panel_and_a_neutral_icon(self):
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ('id="labBtn"', 'id="lab"', "Test lab", 'id="i-lab"', "labReset()"):
            self.assertIn(needle, page)
        self.assertNotIn("cla" + "ude", page.lower())          # the icon is a neutral flask, not another company's logo


if __name__ == "__main__":
    unittest.main()
