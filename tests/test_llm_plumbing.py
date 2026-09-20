"""Checks the AI wiring WITHOUT calling Gemini (the API is faked).
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import unittest
from unittest import mock

import llm
import pipeline
from loader import Inbox

DATA = "data"


class FakeAI:
    """Patch llm.enabled/ask_json so no network or key is needed."""
    def __init__(self, reply):
        self.patches = [mock.patch.object(llm, "enabled", return_value=True),
                        mock.patch.object(llm, "ask_json", side_effect=lambda *a, **k: reply(*a, **k))]

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class TestAI(unittest.TestCase):
    def test_unsure_email_goes_to_ai(self):
        email = {"email_id": "x", "subject": "hello", "body": "Kindly advise on the open item.",
                 "attachments": []}
        reply = lambda prompt, images=(): {"category": "INVOICE_QUERY", "confidence": "high", "reason": "t"}
        with FakeAI(reply):
            self.assertEqual(llm.classify_email(email, email["body"])["category"], "INVOICE_QUERY")

    def test_ai_cannot_invent_a_field(self):
        text = "Shipper: ACME\nConsignee: BOB LTD\n"
        fake = lambda prompt, images=(): {
            "gross_weight_kg": {"value": "99,999 KG", "evidence": "Gross Weight: 99,999 KG"},  # not in doc
            "consignee": {"value": "BOB LTD", "evidence": "Consignee: BOB LTD"}}                # is in doc
        with FakeAI(fake):
            got = llm.fill_missing(text, ["gross_weight_kg", "consignee"])
        self.assertEqual(got, {"consignee": "BOB LTD"})

    def test_scan_goes_to_human_with_ai_suggestion(self):
        fields = {"shipper": "APRIL FAR EAST (M) SDN BHD", "consignee": "AL GURG STATIONERY LLC",
                  "notify_party": "AL GURG STATIONERY LLC", "port_of_loading": "NHAVA SHEVA",
                  "port_of_discharge": "TUTICORIN", "container_count": "3 x 40HC", "gross_weight_kg": "128,544 KG"}
        inbox = Inbox(DATA)
        email = next(e for e in inbox if e["email_id"] == "email_512")
        with FakeAI(lambda prompt, images=(): fields):
            res = pipeline.check_documents(inbox, email)
        self.assertEqual((res["status"], res["review_reason"]), ("NEEDS_REVIEW", "unreadable"))
        self.assertTrue(res["ai_assisted"])
        self.assertEqual(res["ai_suggestion"]["fields"]["port_of_discharge"], "TUTICORIN")

    def test_api_failure_changes_nothing(self):
        inbox = Inbox(DATA)
        email = next(e for e in inbox if e["email_id"] == "email_512")
        with FakeAI(lambda prompt, images=(): None):        # Gemini down / rate-limited
            res = pipeline.check_documents(inbox, email)
        self.assertEqual((res["status"], res["review_reason"]), ("NEEDS_REVIEW", "unreadable"))
        self.assertNotIn("ai_suggestion", res)


if __name__ == "__main__":
    unittest.main()
