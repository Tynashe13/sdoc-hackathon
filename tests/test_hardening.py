"""Hardening: one bad email, a corrupt cache, a busy database or a hostile request must not take the app down.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import llm

ROOT = Path(__file__).resolve().parent.parent


class Boom(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class TestLlmHardening(unittest.TestCase):
    def test_a_missing_document_text_is_not_sent_to_the_ai_and_does_not_crash(self):
        with mock.patch.object(llm, "enabled", return_value=True), \
                mock.patch.object(llm, "ask_json", side_effect=AssertionError("must not be asked")):
            self.assertEqual(llm.fill_missing(None, ["shipper"]), {})
            self.assertEqual(llm.fill_missing("", ["shipper"]), {})

    def test_a_half_written_cache_file_is_ignored_not_fatal(self):
        class Client:
            calls = 0

            class models:
                @staticmethod
                def generate_content(**kw):
                    Client.calls += 1
                    return mock.Mock(text='{"answer": 1}')

        cache = Path(tempfile.mkdtemp())
        with mock.patch.object(llm, "_get_client", return_value=Client), mock.patch.object(llm, "CACHE", cache), \
                mock.patch.object(llm, "FAILED", []):
            self.assertEqual(llm.ask_json("p"), {"answer": 1})
            (only,) = list(cache.glob("*.json"))
            only.write_text('{"answer": ', encoding="utf-8")            # cut off mid-write
            self.assertEqual(llm.ask_json("p"), {"answer": 1})          # asks again instead of raising
            self.assertEqual(json.loads(only.read_text(encoding="utf-8")), {"answer": 1})
        self.assertEqual(Client.calls, 2)
        self.assertEqual(list(cache.glob("*.tmp")), [])

    def test_one_rejected_request_does_not_switch_ai_off_for_good(self):
        class Client:
            class models:
                @staticmethod
                def generate_content(**kw):
                    raise Boom("invalid argument", code=400)

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "USE_LLM": "1"}), \
                mock.patch.object(llm, "_tried", False), mock.patch.object(llm, "_client", None), \
                mock.patch.object(llm, "_disabled_at", 0.0), mock.patch.object(llm, "FAILED", []), \
                mock.patch.object(llm, "CACHE", Path(tempfile.mkdtemp())), \
                mock.patch("google.genai.Client", return_value=Client) as make:
            self.assertIsNone(llm.ask_json("bad prompt"))
            self.assertFalse(llm.enabled())                             # off for now
            self.assertEqual(make.call_count, 1)
            llm._disabled_at = time.time() - llm.QUOTA_COOLDOWN - 1     # the cool-down has passed
            self.assertTrue(llm.enabled())                              # AI is tried again
            self.assertEqual(make.call_count, 2)


class TestModelFallback(unittest.TestCase):
    def client(self, behaviour):
        calls = []

        class Client:
            class models:
                @staticmethod
                def generate_content(model, **kw):
                    calls.append(model)
                    return behaviour(model)
        return Client, calls

    def patches(self, client, models=("main", "backup")):
        return [mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(llm, "MODEL", models[0]),
                mock.patch.object(llm, "FALLBACK_MODELS", list(models[1:])), mock.patch.object(llm, "ATTEMPTS", 2),
                mock.patch.object(llm, "CACHE", Path(tempfile.mkdtemp())), mock.patch.object(llm, "FAILED", []),
                mock.patch.object(llm, "_quota_hit", False), mock.patch.object(llm, "CALLS", 0),
                mock.patch.object(llm, "MAX_CALLS", None), mock.patch.object(llm, "_client", None),
                mock.patch.object(llm, "_disabled_at", 0.0), mock.patch.object(llm, "_model_quota_at", {}),
                mock.patch.object(llm, "_quota_hit_at", 0.0), mock.patch.object(llm.time, "sleep")]

    def run_with(self, patches, fn):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return fn(), list(llm.FAILED), llm.LAST_MODEL

    def test_a_busy_main_model_falls_back_to_the_next_and_leaves_no_failure(self):
        def behaviour(model):
            if model == "main":
                raise Boom("high demand", code=503)
            return mock.Mock(text='{"ok": true}')
        client, calls = self.client(behaviour)
        out, failed, used = self.run_with(self.patches(client), lambda: llm.ask_json_any("p"))
        self.assertEqual(out, {"ok": True})
        self.assertEqual((failed, used), ([], "backup"))
        self.assertEqual(calls, ["main", "main", "backup"])          # every attempt on the main model first

    def test_when_every_model_is_busy_the_failure_is_recorded(self):
        client, calls = self.client(lambda model: (_ for _ in ()).throw(Boom("high demand", code=503)))
        out, failed, _ = self.run_with(self.patches(client), lambda: llm.ask_json_any("p"))
        self.assertIsNone(out)
        self.assertEqual(failed, ["service unavailable", "service unavailable"])

    def test_a_model_out_of_allowance_falls_back_and_is_skipped_next_time(self):
        def behaviour(model):
            if model == "main":
                raise Boom("You exceeded your current quota", code=429)
            return mock.Mock(text='{"ok": true}')
        client, calls = self.client(behaviour)

        def twice():
            return llm.ask_json_any("one"), llm.ask_json_any("two")
        out, failed, used = self.run_with(self.patches(client), twice)
        self.assertEqual((out, failed, used), (({"ok": True}, {"ok": True}), [], "backup"))
        self.assertEqual(calls.count("main"), 2)               # tried twice on the first question, then skipped

    def test_a_missing_fallback_model_does_not_switch_the_main_one_off(self):
        def behaviour(model):
            if model == "main":
                raise Boom("busy", code=503)
            if model == "gone":
                raise Boom("not found", code=404)
            return mock.Mock(text='{"ok": true}')
        client, calls = self.client(behaviour)
        out, failed, used = self.run_with(self.patches(client, models=("main", "gone", "backup")),
                                          lambda: llm.ask_json_any("p"))
        self.assertEqual((out, failed, used), ({"ok": True}, [], "backup"))

    def test_a_bad_key_does_not_try_other_models(self):
        client, calls = self.client(lambda model: (_ for _ in ()).throw(Boom("API key not valid", code=403)))
        out, failed, _ = self.run_with(self.patches(client), lambda: llm.ask_json_any("p"))
        self.assertIsNone(out)
        self.assertEqual(set(calls), {"main"})

    def test_the_answer_is_cached_per_model(self):
        client, calls = self.client(lambda model: mock.Mock(text='{"m": "%s"}' % model))
        patches = self.patches(client)
        out, _, _ = self.run_with(patches, lambda: (llm.ask_json("p", model="a"), llm.ask_json("p", model="b")))
        self.assertEqual(out, ({"m": "a"}, {"m": "b"}))


SCRIPT = r'''
import csv, io, json
from unittest import mock
import app, pipeline, store
out = {}

c = app.app.test_client()
eid = app.ORDER[0]
bl = next(i for i in app.ORDER if app.STATE["results"][i]["category"] == "BL_COMPARISON")

out["headers"] = {k: c.get("/healthz").headers.get(k) for k in ("X-Content-Type-Options", "X-Frame-Options")}
out["plain_text_post"] = c.post(f"/api/emails/{eid}/resolve", data="{}", content_type="text/plain").status_code
out["list_body"] = c.post(f"/api/emails/{bl}/recheck", json=["x"]).status_code
out["list_values"] = c.post(f"/api/emails/{bl}/recheck", json={"si": [1], "bl": "x"}).status_code
out["too_large"] = c.post(f"/api/emails/{eid}/resolve", data="a" * 70000, content_type="application/json").status_code
out["undo_unknown"] = c.delete("/api/emails/nope/review").status_code
detail0 = c.get(f"/api/emails/{eid}").get_json()
r = c.get("/api/emails/nope"); out["not_found"] = [r.status_code, r.get_json()["error"]]
r = c.put(f"/api/emails/{eid}/resolve", json={}); out["wrong_method"] = [r.status_code, r.get_json()["error"]]
r = c.post(f"/api/emails/{bl}/recheck", json={}); out["fill_in"] = r.get_json()["error"]
with mock.patch.object(app, "detail", side_effect=KeyError("secret internal detail")):
    r = c.get(f"/api/emails/{eid}"); out["crash"] = [r.status_code, r.get_json()["error"]]
with mock.patch.object(app, "read_attachment", side_effect=RuntimeError("odd reader failure")):
    r = c.get(f"/api/emails/{eid}"); out["reader_crash_detail"] = [r.status_code, bool(r.get_json()["files"][0]["error"])]
    name0 = detail0["files"][0]["name"]; r = c.get(f"/api/emails/{eid}/lab/{name0}"); out["reader_crash_lab"] = [r.status_code, r.get_json()["kind"]]
out["note_length"] = len(c.post(f"/api/emails/{eid}/resolve", json={"note": "x" * 5000}).get_json()["review"]["note"])
c.delete(f"/api/emails/{eid}/review")

app.EMAILS[bl]["from"] = "=cmd|' /C calc'!A0"
rows = list(csv.reader(io.StringIO(c.get("/api/report.csv").get_data(as_text=True))))
out["csv_from"] = next(r[1] for r in rows if r[0] == bl)

class Down:
    def all(self):
        raise store.StoreError("timeout")
    def put(self, *a):
        raise store.StoreError("timeout")
    drop = put

app.STORE = Down()
r = c.get("/api/emails")
out["db_down_read"] = [r.status_code, r.get_json()["reviews_available"], len(r.get_json()["emails"]) == len(app.ORDER)]
r = c.post(f"/api/emails/{eid}/resolve", json={})
out["db_down_write"] = [r.status_code, "error" in r.get_json()]

class Broken:
    def all(self):
        return {eid: {"nonsense": True}, bl: "not a dict"}
app.STORE = Broken()
out["malformed_review"] = c.get("/api/emails").status_code

def flaky(inbox, email):
    if email["email_id"] == app.ORDER[0]:
        raise ValueError("boom")
    return {"category": "GENERAL", "decided_by": "rule", "status": "OK", "review_reason": None, "defect_fields": []}
app.STATE.update(results={}, done=0, ready=False)
with mock.patch.object(pipeline, "process_email", side_effect=flaky):
    app._boot()
out["boot"] = [app.STATE["ready"], app.STATE["done"] == len(app.ORDER), app.STATE["results"][app.ORDER[0]]["status"]]
print("RESULT " + json.dumps(out))
'''


class TestAppHardening(unittest.TestCase):
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

    def test_security_headers(self):
        self.assertEqual(self.out["headers"], {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"})

    def test_only_real_json_is_accepted_so_other_sites_cannot_post(self):
        self.assertEqual(self.out["plain_text_post"], 415)

    def test_odd_shapes_are_handled_not_500(self):
        self.assertEqual(self.out["list_body"], 400)          # "fill in every value first"
        self.assertEqual(self.out["list_values"], 400)
        self.assertEqual(self.out["undo_unknown"], 404)

    def test_sizes_are_capped(self):
        self.assertEqual(self.out["too_large"], 413)
        self.assertEqual(self.out["note_length"], 1000)

    def test_every_error_is_a_plain_sentence_with_no_code_or_internals(self):
        import re
        messages = [self.out["not_found"][1], self.out["wrong_method"][1], self.out["crash"][1], self.out["fill_in"]]
        for m in messages:
            self.assertFalse(re.search(r"\b(40\d|50\d|KeyError|Traceback|secret internal)\b", m), m)
            self.assertTrue(m.endswith("."), m)
        self.assertEqual([self.out["not_found"][0], self.out["wrong_method"][0], self.out["crash"][0]], [404, 405, 500])
        self.assertIn("Container count", self.out["fill_in"])        # field names, not database keys
        self.assertNotIn("container_count", self.out["fill_in"])

    def test_the_page_never_shows_a_status_code_or_browser_wording(self):
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("statusText", page)                          # would show "BAD REQUEST" / "SERVICE UNAVAILABLE"
        self.assertIn("Cannot reach the server", page)               # instead of "Failed to fetch"

    def test_an_unexpected_reader_failure_does_not_break_the_email_or_the_lab(self):
        self.assertEqual(self.out["reader_crash_detail"], [200, True])
        self.assertEqual(self.out["reader_crash_lab"], [200, "error"])

    def test_the_page_never_spins_for_ever_and_ignores_late_replies(self):
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for needle in ("Cannot load the inbox", "my !== selSeq", "if(working) return", "lab.tabs.includes(name)", "failed:true"):
            self.assertIn(needle, page)

    def test_a_malformed_supabase_row_is_skipped(self):
        import store
        rows = [{"email_id": "a", "review": {"action": "resolved"}}, {"review": {}}, "junk", {"email_id": "b"}]
        with mock.patch.object(store.SupabaseStore, "_call", return_value=rows):
            self.assertEqual(store.SupabaseStore("https://x.supabase.co", "k").all(), {"a": {"action": "resolved"}})

    def test_the_csv_cannot_carry_a_formula(self):
        self.assertTrue(self.out["csv_from"].startswith("'="))

    def test_a_down_database_still_shows_results_and_refuses_writes_cleanly(self):
        self.assertEqual(self.out["db_down_read"], [200, False, True])
        self.assertEqual(self.out["db_down_write"], [503, True])

    def test_a_malformed_saved_review_does_not_break_the_inbox(self):
        self.assertEqual(self.out["malformed_review"], 200)

    def test_one_bad_email_becomes_a_review_case_and_the_rest_still_load(self):
        self.assertEqual(self.out["boot"], [True, True, "NEEDS_REVIEW"])


if __name__ == "__main__":
    unittest.main()
