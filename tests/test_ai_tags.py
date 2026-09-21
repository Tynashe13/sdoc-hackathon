"""Anything the AI (Gemini) contributed must be tagged, quoted and flagged, never mixed in silently.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import unittest
from unittest import mock

import llm
import pipeline

SI = """SHIPPING INSTRUCTION
Shipper: ACME PTE LTD
Cnee: BLUE STAR TRADING
Notify: BLUE STAR TRADING
Port of Loading: SINGAPORE (SGSIN)
Port of Discharge: KARACHI, PAKISTAN (PKKHI)
Container Count: 6 x 40'HC
Gross Weight: 12,000 KG
"""
BL = SI.replace("SHIPPING INSTRUCTION", "DRAFT BILL OF LADING").replace("Cnee:", "Consignee:")


class Inbox:
    files = {"attachments/x_SI.txt": SI.encode(), "attachments/x_BL.txt": BL.encode()}

    def read_bytes(self, path):
        return self.files[path]


EMAIL = {"email_id": "x", "subject": "check", "body": "Please compare the SI and draft BL.",
         "attachments": list(Inbox.files)}


def fake_gemini(text, gaps):
    """The AI 'finds' the consignee that the label patterns could not read (the SI says 'Cnee')."""
    return {"consignee": "BLUE STAR TRADING"} if "consignee" in gaps and "Cnee" in text else {}


class TestAiTags(unittest.TestCase):
    def run_check(self, ai):
        with mock.patch.object(llm, "fill_missing", side_effect=fake_gemini if ai else lambda t, g: {}):
            return pipeline.check_documents(Inbox(), EMAIL)

    def test_a_value_found_by_the_ai_is_tagged_and_quoted(self):
        res = self.run_check(ai=True)
        row = next(r for r in res["table"] if r["field"] == "consignee")
        self.assertTrue(row["si_ai"])
        self.assertFalse(row["bl_ai"])
        self.assertEqual(row["si_evidence"]["line"], "Cnee: BLUE STAR TRADING")
        self.assertEqual(row["si_evidence"]["line_no"], 3)

    def test_the_email_is_flagged_and_says_what_the_ai_did(self):
        res = self.run_check(ai=True)
        self.assertTrue(res["ai_assisted"])
        self.assertEqual(res["ai_notes"], ["SI consignee found by AI: BLUE STAR TRADING"])
        self.assertEqual(res["status"], "OK")

    def test_only_the_field_the_ai_found_is_tagged(self):
        res = self.run_check(ai=True)
        self.assertEqual([r["field"] for r in res["table"] if r["si_ai"] or r["bl_ai"]], ["consignee"])

    def test_without_the_ai_nothing_is_tagged_and_it_goes_to_a_person(self):
        res = self.run_check(ai=False)
        self.assertFalse(res.get("ai_assisted"))
        self.assertEqual((res["status"], res["review_reason"]), ("NEEDS_REVIEW", "missing_value"))
        self.assertFalse(any(r.get("si_ai") or r.get("bl_ai") for r in res.get("table") or []))

    def test_every_committed_result_has_the_flags(self):
        import json
        from pathlib import Path
        snap = json.loads(Path("results.json").read_text(encoding="utf-8"))
        rows = [r for res in snap["results"].values() for r in res.get("table") or []]
        self.assertTrue(rows and all("si_ai" in r and "bl_ai" in r for r in rows))
        if not snap["ai"]:                                                # a rules-only run has no AI values
            self.assertFalse(any(r["si_ai"] or r["bl_ai"] for r in rows))


class TestConsultedNote(unittest.TestCase):
    """Emails 519 and 520 have blank SI values. With Gemini connected it is asked about them; when it finds
    nothing, that is recorded as a quiet note, never as an AI tag."""

    @classmethod
    def setUpClass(cls):
        from loader import Inbox
        cls.inbox = Inbox("data")

    def check(self, eid, enabled, answer=None):
        with mock.patch.object(llm, "enabled", return_value=enabled), \
                mock.patch.object(llm, "ask_json", return_value=answer):
            return pipeline.process_email(self.inbox, self.inbox.get(eid))

    def test_519_records_that_gemini_was_asked_and_found_nothing(self):
        res = self.check("email_519", enabled=True, answer={"shipper": {"value": None, "evidence": None}})
        self.assertEqual(res["ai_consulted"], ["SI shipper, container_count"])
        self.assertFalse(res["ai_assisted"])                       # nothing came from the AI: no tag
        self.assertEqual((res["status"], res["review_reason"]), ("NEEDS_REVIEW", "missing_value"))

    def test_520_too(self):
        res = self.check("email_520", enabled=True)
        self.assertTrue(res["ai_consulted"])
        self.assertFalse(res["ai_assisted"])

    def test_nothing_is_recorded_when_the_ai_is_off(self):
        for eid in ("email_519", "email_520"):
            self.assertNotIn("ai_consulted", self.check(eid, enabled=False))

    def test_an_invented_value_is_rejected_and_still_counts_as_found_nothing(self):
        made_up = {"shipper": {"value": "MADE UP LTD", "evidence": "SHIPPER: MADE UP LTD"}}
        res = self.check("email_519", enabled=True, answer=made_up)
        self.assertFalse(res["ai_assisted"])
        self.assertIn("shipper", res["ai_consulted"][0])

    def test_emails_without_blank_or_unknown_values_are_never_consulted(self):
        for eid in ("email_004", "email_516", "email_001"):
            self.assertNotIn("ai_consulted", self.check(eid, enabled=True))

    def test_the_committed_rules_only_run_records_no_consultation(self):
        import json
        from pathlib import Path
        snap = json.loads(Path("results.json").read_text(encoding="utf-8"))
        if snap["ai"]:
            self.skipTest("this snapshot was built with Gemini connected")
        self.assertFalse(any("ai_consulted" in r for r in snap["results"].values()))


class TestGeminiOutage(unittest.TestCase):
    """When Gemini is busy or down (503), that must never look like 'Gemini looked and found nothing',
    and a snapshot must not be built from a run where it failed."""

    def setUp(self):
        from loader import Inbox
        self.inbox = Inbox("data")
        llm.FAILED.clear()
        self.addCleanup(llm.FAILED.clear)

    def failing_ask(self, prompt, images=()):
        llm.FAILED.append("service unavailable")
        return None

    def check(self, eid):
        with mock.patch.object(llm, "enabled", return_value=True), mock.patch.object(llm, "ask_json", self.failing_ask):
            return pipeline.process_email(self.inbox, self.inbox.get(eid))

    def test_blank_values_are_not_reported_as_consulted_when_gemini_was_down(self):
        res = self.check("email_519")
        self.assertNotIn("ai_consulted", res)
        self.assertFalse(res["ai_assisted"])
        self.assertEqual(res["review_reason"], "missing_value")     # still goes to a person

    def test_a_scan_is_not_reported_as_consulted_when_gemini_was_down(self):
        res = self.check("email_512")
        self.assertNotIn("ai_consulted", res)
        self.assertEqual(res["review_reason"], "unreadable")

    def test_a_busy_server_is_retried_patiently_then_recorded_as_a_failure(self):
        import tempfile
        from pathlib import Path

        class Boom(Exception):
            code = 503

        class Client:
            calls = 0

            class models:
                @staticmethod
                def generate_content(**kw):
                    Client.calls += 1
                    raise Boom("This model is currently experiencing high demand")

        with mock.patch.object(llm, "_get_client", return_value=Client), \
                mock.patch.object(llm, "CACHE", Path(tempfile.mkdtemp())), \
                mock.patch.object(llm.time, "sleep") as sleep:
            self.assertIsNone(llm.ask_json("a prompt"))
        self.assertEqual(Client.calls, llm.ATTEMPTS)
        self.assertEqual(sleep.call_count, llm.ATTEMPTS - 1)         # no pointless wait after the last try
        self.assertLessEqual(max(c.args[0] for c in sleep.call_args_list), 30)
        self.assertEqual(llm.FAILED, ["service unavailable"])

    def test_running_out_of_quota_stops_quickly_and_stops_asking(self):
        import tempfile
        from pathlib import Path

        class OutOfQuota(Exception):
            code = 429

        class Client:
            calls = 0

            class models:
                @staticmethod
                def generate_content(**kw):
                    Client.calls += 1
                    raise OutOfQuota("You exceeded your current quota")

        with mock.patch.object(llm, "_get_client", return_value=Client), \
                mock.patch.object(llm, "CACHE", Path(tempfile.mkdtemp())), \
                mock.patch.object(llm, "_quota_hit", False), \
                mock.patch.object(llm.time, "sleep") as sleep:
            self.assertIsNone(llm.ask_json("first"))
            self.assertEqual(Client.calls, 2)                       # one try, one more after a minute, then stop
            sleep.assert_called_once_with(60)
            self.assertIsNone(llm.ask_json("second"))
            self.assertEqual(Client.calls, 2)                       # no further calls once the quota is gone
        self.assertEqual(llm.FAILED, ["quota exceeded (429)", "quota exceeded (429)"])


    def test_precompute_refuses_to_save_an_ai_snapshot_built_during_an_outage(self):
        import precompute
        import snapshot

        def run_with_a_failure(data_dir):
            llm.FAILED.append("service unavailable")
            return {}

        with mock.patch.object(pipeline, "run", side_effect=run_with_a_failure), \
                mock.patch.object(snapshot, "save") as save:
            code = precompute.main(["--with-ai"])
        self.assertEqual(code, 1)
        save.assert_not_called()


class TestGeminiClientSettings(unittest.TestCase):
    def test_a_stuck_call_gives_up_instead_of_hanging(self):
        """Without a time limit a call that never answers looks like a frozen program."""
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "USE_LLM": "1"}), \
                mock.patch.object(llm, "_tried", False), mock.patch.object(llm, "_client", None), \
                mock.patch("google.genai.Client") as client:
            llm._get_client()
        self.assertEqual(client.call_args.kwargs["http_options"].timeout, llm.TIMEOUT_MS)
        self.assertLessEqual(llm.TIMEOUT_MS, 90_000)


if __name__ == "__main__":
    unittest.main()
