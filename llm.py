"""Gemini helpers.

Everything here is OPTIONAL.  No API key, no library, or any API error means the
functions return None / {} and the pipeline carries on with rules + human review.
Every answer is cached on disk (.cache/llm) so re-runs cost nothing.
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from extract import FIELDS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")   # change in .env if AI Studio lists another
CACHE = Path("/tmp/llm-cache" if os.getenv("VERCEL") else ".cache/llm")   # Vercel's disk is read-only except /tmp
_client, _tried = None, False
CALLS = 0            # real requests sent to Gemini so far in this run
MAX_CALLS = None     # optional cap on those requests: a bad night of retries must not eat the whole daily allowance
_quota_hit_at = 0.0
QUOTA_COOLDOWN = 600  # seconds: a long-running server tries Gemini again after this, in case the allowance has reset
_quota_hit = False   # the key has used up its Gemini allowance: stop asking, every further call would fail too
FAILED = []          # one entry per call that gave up (busy or broken service), so callers can tell "found nothing" from "unavailable"
ATTEMPTS = 5        # a busy server (503) usually recovers within a minute
TIMEOUT_MS = 60_000  # one attempt may not wait longer than this: without it a stuck call looks like a frozen program

CATEGORIES = {
    "BL_COMPARISON": "asks us to check/compare a Shipping Instruction against a draft Bill of Lading, "
                     "or asks for the draft BL to be sent so it can be checked",
    "SI_REQUEST":    "sends shipment details asking us to prepare a NEW Shipping Instruction",
    "INVOICE_QUERY": "a question or dispute about an invoice, charges, billing or payment",
    "GENERAL":       "legitimate operational updates, notifications, reports, greetings - anything else",
    "SPAM":          "unsolicited, phishing, scam or advertising",
}


def _get_client():
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    key = os.getenv("GEMINI_API_KEY")
    if os.getenv("USE_LLM", "1") == "0" or not key:
        return None
    try:
        from google import genai
        from google.genai import types
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    except Exception:
        _client = None
    return _client


def enabled() -> bool:
    return _get_client() is not None


def ask_json(prompt, images=()):
    """One Gemini call that must return JSON.  Cached, retried, never raises."""
    global CALLS, _quota_hit
    client = _get_client()
    if client is None:
        return None
    digest = hashlib.sha256(MODEL.encode() + prompt.encode() + b"".join(images)).hexdigest()
    cache_file = CACHE / f"{digest}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    if _quota_hit and time.time() - _quota_hit_at > QUOTA_COOLDOWN:
        _quota_hit = False
    if _quota_hit:
        FAILED.append("quota exceeded (429)")
        return None
    from google.genai import types
    parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images] + [prompt]
    config = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json",
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    what = "reading a scanned page" if images else "checking an email"
    for attempt in range(ATTEMPTS):
        if MAX_CALLS is not None and CALLS >= MAX_CALLS:
            FAILED.append("request cap reached")
            print(f"[llm] request cap reached ({MAX_CALLS} requests sent): stopping so the allowance is not used up",
                  file=sys.stderr, flush=True)
            return None
        CALLS += 1
        print(f"[llm] asking Gemini ({what}), try {attempt + 1}/{ATTEMPTS}; it can take up to a minute ...",
              file=sys.stderr, flush=True)
        try:
            reply = client.models.generate_content(model=MODEL, contents=parts, config=config)
            data = json.loads(reply.text)
            print("[llm] Gemini answered", file=sys.stderr, flush=True)
            try:
                CACHE.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data))
            except OSError:
                pass                                # no cache is fine, just slower next time
            return data
        except Exception as exc:
            code = getattr(exc, "code", None)
            print(f"[llm] Gemini call failed (try {attempt + 1}/{ATTEMPTS}): {type(exc).__name__}: "
                  f"{str(exc)[:300]}", file=sys.stderr)
            if code == 429:                        # quota: hammering it every few seconds only makes it worse
                if attempt == 0:
                    print("[llm] quota exceeded (429): waiting 60 seconds and trying once more", file=sys.stderr, flush=True)
                    time.sleep(60)
                    continue
                _give_up_on_quota()
                return None
            if code in (400, 401, 403, 404):      # bad key / bad model name: retrying is pointless
                FAILED.append(f"HTTP {code}")
                _disable(f"stopping AI calls for this run - fix the problem above (HTTP {code})")
                return None
            if attempt < ATTEMPTS - 1:
                time.sleep(min(2 ** (attempt + 1), 30))   # rate limit (429) / server error: back off
    FAILED.append("service unavailable")
    return None


def _give_up_on_quota():
    global _quota_hit, _quota_hit_at
    _quota_hit = True
    _quota_hit_at = time.time()
    FAILED.append("quota exceeded (429)")
    print("[llm] Gemini quota exceeded: this key has used up its allowance (per minute or per day). No more calls "
          "will be made in this run. Check https://ai.dev/rate-limit, wait for it to reset, or use another key/model.",
          file=sys.stderr, flush=True)


def _disable(why):
    global _client
    print(f"[llm] {why}", file=sys.stderr)
    _client = None


def classify_email(email, body):
    """Second opinion for emails the keyword rules could not place."""
    if not enabled():
        return None
    menu = "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
    prompt = (
        "You triage a shipping operations inbox.  Classify the email by what its BODY asks for; "
        "the subject line may be misleading.\n"
        f"Categories:\n{menu}\n\n"
        f"Subject: {email['subject']}\nAttachments: {len(email['attachments'])}\nBody:\n{body[:1500]}\n\n"
        'Reply as JSON: {"category": "<one category>", "confidence": "high|medium|low", "reason": "<short>"}')
    out = ask_json(prompt)
    return out if isinstance(out, dict) and out.get("category") in CATEGORIES else None


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).lower()


def fill_missing(text, fields):
    """Ask Gemini only for fields the rules could not find.  A value is accepted only when
    the line it quotes really appears in the document - this blocks made-up answers."""
    if not enabled() or not fields:
        return {}
    prompt = (
        "Below is a shipping document.  Find these fields, wording may differ from the names "
        f"given: {fields}.\nReturn JSON mapping each field to "
        '{"value": "<as printed>", "evidence": "<the exact line of the document containing it>"}, '
        "or {\"value\": null, \"evidence\": null} when the document does not state it.  Never guess.\n\n"
        f"DOCUMENT:\n{text[:6000]}")
    out = ask_json(prompt) or {}
    found = {}
    for f in fields:
        item = out.get(f) if isinstance(out, dict) else None
        item = item if isinstance(item, dict) else {}
        value, evidence = item.get("value"), item.get("evidence")
        if value and evidence and _norm(evidence) in _norm(text) and _norm(value) in _norm(evidence):
            found[f] = str(value)
    return found


def read_scan(images):
    """Vision read of a scanned page.  -> {field: value or None} or None if unavailable.
    The caller treats this as a SUGGESTION for a human to confirm, never as final."""
    if not enabled() or not images:
        return None
    prompt = (
        "This is a scanned shipping document.  Read it and return JSON with exactly these keys: "
        f"{FIELDS}.  Use the text as printed (container_count like '6 x 40HC', weight with unit).  "
        "Use null for anything you cannot read with confidence.  Never guess.")
    out = ask_json(prompt, images=images)
    if not isinstance(out, dict):
        return None
    return {f: (str(out[f]) if out.get(f) else None) for f in FIELDS}
