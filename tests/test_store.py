import tempfile
import unittest
from pathlib import Path
from unittest import mock

import store


class FileStoreTest(unittest.TestCase):
    def test_round_trip_and_reload(self):
        path = Path(tempfile.mkdtemp()) / "r.json"
        s = store.FileStore(path)
        s.put("email_001", {"action": "resolved"})
        self.assertEqual(store.FileStore(path).all(), {"email_001": {"action": "resolved"}})
        s.drop("email_001")
        self.assertEqual(store.FileStore(path).all(), {})

    def test_read_only_disk_keeps_working_in_memory(self):
        s = store.FileStore("/proc/nope/r.json")
        s.put("a", {"x": 1})
        self.assertEqual(s.all(), {"a": {"x": 1}})


class SupabaseStoreTest(unittest.TestCase):
    def setUp(self):
        self.s = store.SupabaseStore("https://proj.supabase.co/", "k")

    def test_all_folds_rows_into_a_dict(self):
        rows = [{"email_id": "a", "review": {"x": 1}}, {"email_id": "b", "review": {"y": 2}}]
        with mock.patch.object(self.s, "_call", return_value=rows):
            self.assertEqual(self.s.all(), {"a": {"x": 1}, "b": {"y": 2}})

    def test_put_upserts_and_drop_filters_by_id(self):
        with mock.patch.object(self.s, "_call") as call:
            self.s.put("email_001", {"action": "resolved"})
            self.s.drop("email_001")
        self.assertEqual(call.call_args_list[0].args[:2], ("POST", "?on_conflict=email_id"))
        self.assertEqual(call.call_args_list[1].args, ("DELETE", "?email_id=eq.email_001"))

    def test_url_is_the_reviews_table(self):
        self.assertEqual(self.s.base, "https://proj.supabase.co/rest/v1/reviews")

    def test_env_picks_backend(self):
        with mock.patch.dict("os.environ", {"SUPABASE_URL": "https://x", "SUPABASE_SERVICE_ROLE_KEY": "k"}):
            self.assertEqual(store.kind(store.open_store()), "supabase")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(store.kind(store.open_store()), "file")


if __name__ == "__main__":
    unittest.main()
