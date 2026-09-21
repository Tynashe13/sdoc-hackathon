"""Where reviewer decisions live.

On Vercel every request can land on a different short-lived instance and the disk is read-only,
so decisions cannot sit in a global dict or a file.  If Supabase is configured
(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, which the Vercel Marketplace integration sets) they
go there, in one table.  Otherwise they go to a JSON file (REVIEWS_PATH), which is what running
running on your own machine uses.  Either way the rest of the app only sees all() / put() / drop().
"""
import json
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path


class StoreError(Exception):
    """The reviews database could not be reached or refused the request."""


class FileStore:
    def __init__(self, path):
        self.path, self.lock = Path(path), threading.Lock()
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def _flush(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:                      # read-only disk: keep working from memory
            pass

    def all(self):
        return dict(self.data)

    def put(self, eid, review):
        with self.lock:
            self.data[eid] = review
            self._flush()

    def drop(self, eid):
        with self.lock:
            self.data.pop(eid, None)
            self._flush()


class SupabaseStore:
    """Supabase's REST API (PostgREST) over the `reviews` table in supabase/schema.sql.

    Uses the service-role key, which only ever lives in the server's environment (never in the page);
    the table has row-level security on and no policies, so the public anon key cannot read it.
    """

    def __init__(self, url, key):
        self.base, self.key = url.rstrip("/") + "/rest/v1/reviews", key

    def _call(self, method, query="", body=None, prefer=None):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(self.base + query, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read()
            return json.loads(raw) if raw else None
        except (OSError, ValueError) as exc:          # URLError, HTTPError and timeouts are all OSErrors
            raise StoreError(f"{type(exc).__name__}: {exc}") from exc

    def all(self):
        rows = self._call("GET", "?select=email_id,review") or []
        return {r["email_id"]: r["review"] for r in rows}

    def put(self, eid, review):
        self._call("POST", "?on_conflict=email_id", {"email_id": eid, "review": review},
                   prefer="resolution=merge-duplicates,return=minimal")

    def drop(self, eid):
        self._call("DELETE", "?email_id=eq." + urllib.parse.quote(eid, safe=""))


def open_store():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    default = "/tmp/reviews.json" if os.getenv("VERCEL") else "reviews.json"
    return FileStore(os.getenv("REVIEWS_PATH", default))


def kind(store):
    return "supabase" if isinstance(store, SupabaseStore) else "file"
