"""Web app: an Apple-Mail-style inbox that shows every email's verification result.

Run locally:   python app.py           -> http://localhost:5000
Deploy:        Vercel (vercel --prod); Flask is picked up from this file as-is
"""
import copy
import csv
import io
import json
import os
import re
import sys
import threading
import urllib.parse
from datetime import datetime, timezone

from flask import Flask, Response, abort, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import explain
import llm
import pipeline
import snapshot
import store
from classify import body_core
from compare import field_table, normalise
from extract import FIELDS
from loader import Inbox
from readers import NoTextError, ReadError, pdf_page_pngs, read_attachment

DATA_DIR = os.getenv("DATA_DIR", "data")
RESULTS_FILE = os.getenv("RESULTS_FILE", "results.json")

# A person is waiting on the Retry button, so give up on a busy Gemini quickly (precompute.py keeps the patient defaults)
llm.ATTEMPTS = int(os.getenv("LLM_ATTEMPTS", "2"))
llm.TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "30000"))
llm.QUOTA_WAIT = int(os.getenv("LLM_QUOTA_WAIT", "10"))

FIELD_NAMES, REVIEW_TEXT = explain.FIELD_NAMES, explain.REVIEW_TEXT
EXPLANATIONS = explain.load(os.getenv("EXPLANATIONS_FILE", "explanations.json"))   # AI-written reasons, see explain.py
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024          # a review is a few short values and a note
MAX_VALUE, MAX_NOTE = 500, 1000
inbox = Inbox(DATA_DIR)
EMAILS = {e["email_id"]: e for e in inbox}
ORDER = sorted(EMAILS)

STATE = {"ready": False, "done": 0, "total": len(EMAILS), "results": {}, "error": None}
STORE = store.open_store()


# ---------------------------------------------------------------- processing
def _could_not_process(exc):
    print(f"[app] could not process an email: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    return {"category": "BL_COMPARISON", "decided_by": "fallback", "ai_assisted": False, "ai_notes": [],
            **pipeline.review("unreadable", "This email could not be processed automatically, so a person "
                                            "needs to check it.")}


def _boot():
    for eid in ORDER:                              # one bad email becomes a review case, it never stops the rest
        try:
            STATE["results"][eid] = pipeline.process_email(inbox, EMAILS[eid])
        except Exception as exc:
            STATE["results"][eid] = _could_not_process(exc)
        STATE["done"] += 1
    STATE["ready"] = True


def _start():
    """Use the precomputed results when they match the data and the code; otherwise compute
    them in the background (slow on a small host, which is why results.json is committed)."""
    saved = snapshot.load(RESULTS_FILE, DATA_DIR)
    if saved and set(saved) == set(EMAILS):
        STATE.update(results=saved, done=len(saved), ready=True)
        print(f"[app] ready: {len(saved)} emails loaded from {RESULTS_FILE}", file=sys.stderr, flush=True)
    else:
        print(f"[app] {RESULTS_FILE} missing or out of date: computing {len(EMAILS)} emails in the "
              "background (run python precompute.py to avoid this)", file=sys.stderr, flush=True)
        threading.Thread(target=_boot, daemon=True).start()


_start()


def reviews():
    """Reviewer decisions, read once per request (another instance may have written since)."""
    if "reviews" not in g:
        try:
            g.reviews = STORE.all()
        except store.StoreError as exc:            # reviews are an overlay: show the machine results without them
            print(f"[app] reviews unavailable: {exc}", file=sys.stderr, flush=True)
            g.reviews, g.reviews_down = {}, True
    return g.reviews


def _decide(eid, review=None):
    """Save a reviewer decision, or clear it when review is None."""
    STORE.put(eid, review) if review else STORE.drop(eid)
    g.pop("reviews", None)


def effective(eid):
    """Machine result, overlaid with whatever a human reviewer decided."""
    res = copy.deepcopy(STATE["results"][eid])
    rev = reviews().get(eid)
    if isinstance(rev, dict):
        try:
            if rev["action"] == "corrected":
                res.update(status=rev["status"], defect_fields=rev["defect_fields"],
                           has_defect=bool(rev["defect_fields"]), table=rev["table"],
                           mismatches=[r for r in rev["table"] if r["status"] == "mismatch"],
                           human_reviewed=True)
            res["review"], res["resolved"] = rev, True
        except (KeyError, TypeError):              # one malformed stored decision must not break the inbox
            print(f"[app] ignoring a malformed saved review for {eid}", file=sys.stderr, flush=True)
    return res


def _kept_evidence(eid, si, bl):
    """The source line of every value a person left unchanged, so a correction keeps its quotes.
    A value that was edited has no source line any more, so it gets none."""
    res = STATE["results"][eid]
    orig_si = {r["field"]: r["si"] for r in res.get("table") or []}
    orig_bl = {r["field"]: r["bl"] for r in res.get("table") or []}
    ev_si = {r["field"]: r.get("si_evidence") for r in res.get("table") or []}
    ev_bl = {r["field"]: r.get("bl_evidence") for r in res.get("table") or []}
    form = res.get("form")
    if form:
        orig_si, orig_bl = form["si"], form["bl"]
        ev_si, ev_bl = form.get("si_evidence", {}), form.get("bl_evidence", {})
    keep = lambda now, was, ev: {f: ev[f] for f in ev if ev.get(f) and now.get(f) == was.get(f)}
    return keep(si, orig_si, ev_si), keep(bl, orig_bl, ev_bl)


# ---------------------------------------------------------------- helpers
def sender(addr):
    local = addr.split("@")[0]
    words = [w for w in re.split(r"[._\-\d]+", local) if w]
    name = " ".join(w.capitalize() for w in words) or addr
    initials = "".join(w[0] for w in words[:2]).upper() or "?"
    hue = sum(ord(c) for c in addr) % 360
    return name, initials, hue


def preview(email):
    # skip the "WARNING: This email originated outside of our organisation ..." banner
    clean = dict(email, body=re.sub(r"^\s*WARNING:.*?\n\s*\n", "", email["body"], flags=re.S))
    text = body_core(clean)
    text = re.sub(r"^(hi|hello|dear)\s+[^,]{0,30},\s*", "", text, flags=re.I)
    return text[:140]


def explanation(r, eid):
    """The AI-written reason for this case, only if it was written for exactly these values."""
    saved, f = EXPLANATIONS.get(eid), explain.facts(r)
    return saved["text"] if saved and f and saved.get("basis") == explain.basis(f) else None


def summary(eid):
    e, r = EMAILS[eid], effective(eid)
    name, initials, hue = sender(e["from"])
    return {"id": eid, "from": e["from"], "name": name, "initials": initials, "hue": hue,
            "subject": e["subject"], "preview": preview(e), "attachments": len(e["attachments"]),
            "category": r["category"], "status": r["status"], "reason": r["review_reason"],
            "mismatches": len(r["defect_fields"]), "resolved": bool(r.get("resolved")),
            "human": bool(r.get("human_reviewed")), "awaiting": bool(r.get("awaiting_documents")),
            "ai": bool(r.get("ai_assisted") or explanation(r, eid))}


def attachment_info(eid):
    out = []
    for path in EMAILS[eid]["attachments"]:
        name = path.rsplit("/", 1)[-1]
        item = {"name": name, "ext": name.rsplit(".", 1)[-1].lower(), "text": None,
                "error": None, "scan": False}
        try:
            item["text"] = read_attachment(name, inbox.read_bytes(path))[:4000]
        except NoTextError as exc:
            item.update(error=str(exc), scan=True)
        except ReadError as exc:
            item["error"] = str(exc)
        except Exception:                                       # an unexpected reader failure must not break the whole email
            item["error"] = "This document could not be read. Download it to open it yourself."
        out.append(item)
    return out


def detail(eid):
    e, r = EMAILS[eid], effective(eid)
    name, initials, hue = sender(e["from"])
    return {**summary(eid), "body": e["body"], "decided_by": r["decided_by"], "detail": r["detail"] if "detail" in r else "",
            "table": r.get("table"), "form": r.get("form"), "ai_explanation": explanation(r, eid),
            "ai_notes": r.get("ai_notes", []) + (
                ["wrote the plain-language explanation of the differences; the verdict itself comes from the rules"]
                if explanation(r, eid) else []),
            "ai_suggestion": r.get("ai_suggestion"), "ai_consulted": r.get("ai_consulted", []),
            "review": r.get("review"),
            "files": attachment_info(eid), "fields": FIELDS}


# ---------------------------------------------------------------- routes
@app.after_request
def _headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


# What a person is told when something fails: plain sentences, never a status code or a technical message.
PLAIN_ERRORS = {
    400: "Something in that request was not right. Check the values and try again.",
    404: "That email could not be found. Refresh the page and try again.",
    405: "That action is not available.",
    413: "That is too long. Shorten the note or the values and try again.",
    415: "That request could not be read. Refresh the page and try again.",
    429: "Too many requests at once. Wait a moment and try again.",
    503: "The service is busy right now. Nothing was changed. Try again in a moment.",
}
SOMETHING_WENT_WRONG = "Something went wrong on our side. Nothing was changed. Try again in a moment."


def _plain(code):
    return PLAIN_ERRORS.get(code, SOMETHING_WENT_WRONG)


@app.errorhandler(store.StoreError)
def _store_down(exc):
    print(f"[app] reviews database error: {exc}", file=sys.stderr, flush=True)
    return jsonify(error="Saved decisions cannot be reached right now, so nothing was changed. "
                         "Try again in a moment."), 503


@app.errorhandler(HTTPException)
def _http_error(exc):
    if not request.path.startswith("/api/"):
        return exc
    return jsonify(error=_plain(exc.code)), exc.code


@app.errorhandler(Exception)
def _unexpected(exc):
    print(f"[app] unexpected error on {request.path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    if not request.path.startswith("/api/"):
        return "Something went wrong. Please reload the page.", 500
    return jsonify(error=SOMETHING_WENT_WRONG), 500


def _json_body():
    """The request body as a dict. Only real JSON is accepted, so a web page on another site cannot post here."""
    if not request.is_json:
        abort(415)
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _side(body, key):
    values = body.get(key)
    values = values if isinstance(values, dict) else {}
    return {f: (_text(values.get(f), MAX_VALUE) or None) for f in FIELDS}


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, ready=STATE["ready"], reviews=store.kind(STORE))


@app.get("/api/emails")
def api_emails():
    if not STATE["ready"]:
        return jsonify(ready=False, done=STATE["done"], total=STATE["total"], error=STATE["error"])
    emails = [summary(i) for i in ORDER]
    return jsonify(ready=True, ai=llm.enabled(), reviews_available=not g.get("reviews_down"), emails=emails)


@app.get("/api/emails/<eid>")
def api_email(eid):
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    return jsonify(detail(eid))


@app.get("/api/attachment/<eid>/<name>")
def api_attachment(eid, name):
    path = next((p for p in EMAILS.get(eid, {}).get("attachments", []) if p.endswith("/" + name)), None)
    if not path:
        abort(404)
    data = inbox.read_bytes(path)
    if request.args.get("render") == "png":
        try:
            return Response(pdf_page_pngs(data, max_pages=1, resolution=110)[0], mimetype="image/png")
        except Exception:
            abort(404)
    return Response(data, mimetype="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


LAB_MAX_LINES = 400


def _lab_marks(eid, name):
    """Every value whose source line is in this document, so the Test lab can highlight it."""
    r = effective(eid)
    marks = []
    for row in r.get("table") or []:
        for side in ("si", "bl"):
            ev = row.get(f"{side}_evidence")
            if ev and ev.get("doc") == name:
                marks.append({"field": row["field"], "label": FIELD_NAMES[row["field"]], "side": side.upper(),
                              "line_no": ev["line_no"], "status": row["status"], "ai": bool(row.get(f"{side}_ai"))})
    if not marks:                                   # a case that needs review has no table, only the values read so far
        form = r.get("form") or {}
        for side in ("si", "bl"):
            for field, ev in (form.get(f"{side}_evidence") or {}).items():
                if ev and ev.get("doc") == name and field in FIELD_NAMES:
                    marks.append({"field": field, "label": FIELD_NAMES[field], "side": side.upper(),
                                  "line_no": ev["line_no"], "status": "review", "ai": field in form.get(f"{side}_ai", [])})
    return sorted(marks, key=lambda m: m["line_no"])


@app.get("/api/emails/<eid>/lab/<name>")
def api_lab(eid, name):
    """The Test lab: one attachment's full text with the lines that every compared value was read from marked."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    path = next((p for p in EMAILS[eid]["attachments"] if p.endswith("/" + name)), None)
    if not path:
        abort(404)
    out = {"name": name, "download": f"/api/attachment/{eid}/{urllib.parse.quote(name)}", "kind": "text",
           "lines": [], "marks": [], "truncated": False, "message": None}
    try:
        text = read_attachment(name, inbox.read_bytes(path))
    except NoTextError:                             # a scan: show the page itself, there is no text to mark
        return jsonify({**out, "kind": "scan", "image": out["download"] + "?render=png",
                        "message": "This is a scanned page, so there are no text lines to mark. Compare the values with the page."})
    except Exception:                                # ReadError or anything else the reader raises
        return jsonify({**out, "kind": "error", "message": "This document could not be read. Download it to open it yourself."})
    lines = text.splitlines()
    marks = _lab_marks(eid, name)
    shown = [m for m in marks if m["line_no"] <= LAB_MAX_LINES]
    out.update(lines=lines[:LAB_MAX_LINES], truncated=len(lines) > LAB_MAX_LINES, marks=shown,
               beyond=len(marks) - len(shown))
    return jsonify(out)


@app.post("/api/emails/<eid>/recheck")
def api_recheck(eid):
    """A person supplies/corrects the values; the report is recomputed from them."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    body = _json_body()
    si, bl = _side(body, "si"), _side(body, "bl")
    table = pipeline.with_evidence(field_table(si, bl), *_kept_evidence(eid, si, bl))
    missing = [r["field"] for r in table if r["status"] == "missing"]
    if missing:
        return jsonify(error="Fill in every value first. Still empty or unusable: " + ", ".join(FIELD_NAMES[m] for m in missing) + "."), 400
    defects = [r["field"] for r in table if r["status"] == "mismatch"]
    _decide(eid, {"action": "corrected", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "note": _text(body.get("note"), MAX_NOTE), "si": si, "bl": bl, "table": table,
                  "status": "MISMATCH" if defects else "OK", "defect_fields": defects})
    return jsonify(detail(eid))


@app.post("/api/emails/<eid>/resolve")
def api_resolve(eid):
    """Close a case that needs no value check (e.g. the sender was asked for the right file)."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    body = _json_body()
    _decide(eid, {"action": "resolved", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "note": _text(body.get("note"), MAX_NOTE)})
    return jsonify(detail(eid))


@app.post("/api/emails/<eid>/retry")
def api_retry(eid):
    """Run the whole check again for one email (clears any human decision).
    If Gemini is busy or out of quota and the saved result already used it, keep that result and the
    reviewer's decision instead of replacing them with a weaker one."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    old = STATE["results"][eid]
    failed_before = len(llm.FAILED)
    try:
        new = pipeline.process_email(inbox, EMAILS[eid])
    except Exception as exc:                       # keep the saved result and the reviewer's decision
        print(f"[app] retry failed for {eid}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return jsonify({**detail(eid), "kept": True})
    busy = len(llm.FAILED) > failed_before
    if (busy or not llm.enabled()) and (old.get("ai_assisted") or old.get("ai_consulted")):
        return jsonify({**detail(eid), "kept": True, "busy": busy})     # AI is busy or switched off: keep what it found
    _decide(eid)
    STATE["results"][eid] = new
    return jsonify(detail(eid))


@app.delete("/api/emails/<eid>/review")
def api_undo(eid):
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    _decide(eid)
    return jsonify(detail(eid))


def why_it_differs(row):
    """One plain sentence saying why a field counts as a mismatch."""
    f, name = row["field"], FIELD_NAMES[row["field"]]
    if f in ("shipper", "consignee", "notify_party"):
        return f"{name}: different company or name"
    if f in ("port_of_loading", "port_of_discharge"):
        a, b = normalise(f, row["si"]), normalise(f, row["bl"])
        if a and b and a[0] == b[0]:
            return f"{name}: same port name but a different port code"
        return f"{name}: different port"
    if f == "container_count":
        return f"{name}: the number, size or type of containers differs"
    a, b = normalise(f, row["si"]), normalise(f, row["bl"])
    if a and b:
        diff = abs(a[0] - b[0])
        pct = 100 * diff / max(a[0], b[0])
        amount = f"{diff:,.0f}" if diff >= 10 else f"{diff:,.1f}".rstrip("0").rstrip(".")
        return f"{name}: weights differ by {amount} kg ({pct:.1f}%)"
    return f"{name}: weights differ"


def _csv_safe(value):
    """Text that starts with = + - @ would run as a formula when the CSV is opened in Excel."""
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@app.get("/api/report.csv")
def api_report():
    """Discrepancy report for every document-check request (includes human decisions)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email_id", "from", "subject", "result", "review_reason", "mismatched_fields",
                "details (SI vs BL)", "why (plain language)", "human_reviewed", "ai_assisted"])
    for eid in ORDER:
        r = effective(eid)
        if r["category"] != "BL_COMPARISON":
            continue
        e = EMAILS[eid]
        result = {"OK": "No mismatch detected", "MISMATCH": "Mismatch",
                  "NEEDS_REVIEW": "Needs review"}.get(r["status"], r["status"])
        if r.get("awaiting_documents"):
            result = "Awaiting draft BL (nothing to compare yet)"
        bad = [row for row in (r.get("table") or []) if row["status"] == "mismatch"]
        if r.get("awaiting_documents"):
            why = "Only the draft BL was requested, so there is nothing to compare yet"
        elif r["status"] == "NEEDS_REVIEW":
            why = REVIEW_TEXT.get(r["review_reason"], "A person needs to look at this case")
        else:
            why = "; ".join(why_it_differs(x) for x in bad)
        why = explanation(r, eid) or why
        w.writerow(map(_csv_safe, [
            eid, e["from"], e["subject"], result, r["review_reason"] or "",
            ", ".join(r["defect_fields"]),
            "; ".join(f"{x['field']}: SI {x['si']} / BL {x['bl']}" for x in bad) or r.get("detail", ""),
            why,
            "yes" if r.get("human_reviewed") or r.get("resolved") else "no",
            "yes" if r.get("ai_assisted") or explanation(r, eid) else "no"]))
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="discrepancy_report.csv"'})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False, threaded=True)
