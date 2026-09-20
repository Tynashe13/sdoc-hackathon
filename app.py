"""Web app: an Apple-Mail-style inbox that shows every email's verification result.

Run locally:   python app.py           -> http://localhost:5000
Deploy:        gunicorn app:app --timeout 180
"""
import copy
import csv
import io
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

import llm
import pipeline
import snapshot
from classify import body_core
from compare import field_table
from extract import FIELDS
from loader import Inbox
from readers import NoTextError, ReadError, pdf_page_pngs, read_attachment

DATA_DIR = os.getenv("DATA_DIR", "data")
REVIEWS_FILE = Path(os.getenv("REVIEWS_PATH", "reviews.json"))
RESULTS_FILE = os.getenv("RESULTS_FILE", "results.json")

app = Flask(__name__, static_folder="static", static_url_path="/static")
inbox = Inbox(DATA_DIR)
EMAILS = {e["email_id"]: e for e in inbox}
ORDER = sorted(EMAILS)

STATE = {"ready": False, "done": 0, "total": len(EMAILS), "results": {}, "error": None}
LOCK = threading.Lock()
REVIEWS = json.loads(REVIEWS_FILE.read_text()) if REVIEWS_FILE.exists() else {}


# ---------------------------------------------------------------- processing
def _boot():
    try:
        for eid in ORDER:
            STATE["results"][eid] = pipeline.process_email(inbox, EMAILS[eid])
            STATE["done"] += 1
        STATE["ready"] = True
    except Exception as exc:                       # show it in the UI instead of hanging
        STATE["error"] = f"{type(exc).__name__}: {exc}"


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


def _save_reviews():
    REVIEWS_FILE.write_text(json.dumps(REVIEWS, indent=2))


def effective(eid):
    """Machine result, overlaid with whatever a human reviewer decided."""
    res = copy.deepcopy(STATE["results"][eid])
    rev = REVIEWS.get(eid)
    if rev:
        res["review"] = rev
        res["resolved"] = True
        if rev["action"] == "corrected":
            res.update(status=rev["status"], defect_fields=rev["defect_fields"],
                       has_defect=bool(rev["defect_fields"]), table=rev["table"],
                       mismatches=[r for r in rev["table"] if r["status"] == "mismatch"],
                       human_reviewed=True)
    return res


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


def summary(eid):
    e, r = EMAILS[eid], effective(eid)
    name, initials, hue = sender(e["from"])
    return {"id": eid, "from": e["from"], "name": name, "initials": initials, "hue": hue,
            "subject": e["subject"], "preview": preview(e), "attachments": len(e["attachments"]),
            "category": r["category"], "status": r["status"], "reason": r["review_reason"],
            "mismatches": len(r["defect_fields"]), "resolved": bool(r.get("resolved")),
            "human": bool(r.get("human_reviewed")), "awaiting": bool(r.get("awaiting_documents")),
            "ai": bool(r.get("ai_assisted"))}


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
        out.append(item)
    return out


def detail(eid):
    e, r = EMAILS[eid], effective(eid)
    name, initials, hue = sender(e["from"])
    return {**summary(eid), "body": e["body"], "decided_by": r["decided_by"], "detail": r["detail"] if "detail" in r else "",
            "table": r.get("table"), "form": r.get("form"), "ai_notes": r.get("ai_notes", []),
            "ai_suggestion": r.get("ai_suggestion"), "review": r.get("review"),
            "files": attachment_info(eid), "fields": FIELDS}


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/api/emails")
def api_emails():
    if not STATE["ready"]:
        return jsonify(ready=False, done=STATE["done"], total=STATE["total"], error=STATE["error"])
    return jsonify(ready=True, ai=llm.enabled(), emails=[summary(i) for i in ORDER])


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


@app.post("/api/emails/<eid>/recheck")
def api_recheck(eid):
    """A person supplies/corrects the values; the report is recomputed from them."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    body = request.get_json(force=True) or {}
    si = {f: (str(body.get("si", {}).get(f) or "").strip() or None) for f in FIELDS}
    bl = {f: (str(body.get("bl", {}).get(f) or "").strip() or None) for f in FIELDS}
    table = field_table(si, bl)
    missing = [r["field"] for r in table if r["status"] == "missing"]
    if missing:
        return jsonify(error="Fill in every value first. Still empty or unusable: " + ", ".join(missing)), 400
    defects = [r["field"] for r in table if r["status"] == "mismatch"]
    with LOCK:
        REVIEWS[eid] = {"action": "corrected", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "note": (body.get("note") or "").strip(), "si": si, "bl": bl, "table": table,
                        "status": "MISMATCH" if defects else "OK", "defect_fields": defects}
        _save_reviews()
    return jsonify(detail(eid))


@app.post("/api/emails/<eid>/resolve")
def api_resolve(eid):
    """Close a case that needs no value check (e.g. the sender was asked for the right file)."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    body = request.get_json(force=True) or {}
    with LOCK:
        REVIEWS[eid] = {"action": "resolved", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "note": (body.get("note") or "").strip()}
        _save_reviews()
    return jsonify(detail(eid))


@app.post("/api/emails/<eid>/retry")
def api_retry(eid):
    """Run the whole check again for one email (clears any human decision)."""
    if eid not in EMAILS or not STATE["ready"]:
        abort(404)
    with LOCK:
        REVIEWS.pop(eid, None)
        _save_reviews()
    STATE["results"][eid] = pipeline.process_email(inbox, EMAILS[eid])
    return jsonify(detail(eid))


@app.delete("/api/emails/<eid>/review")
def api_undo(eid):
    with LOCK:
        REVIEWS.pop(eid, None)
        _save_reviews()
    return jsonify(detail(eid))


@app.get("/api/report.csv")
def api_report():
    """Discrepancy report for every document-check request (includes human decisions)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email_id", "from", "subject", "result", "review_reason", "mismatched_fields",
                "details (SI vs BL)", "human_reviewed"])
    for eid in ORDER:
        r = effective(eid)
        if r["category"] != "BL_COMPARISON":
            continue
        e = EMAILS[eid]
        result = {"OK": "No mismatch detected", "MISMATCH": "Mismatch", "NEEDS_REVIEW": "Needs review"}[r["status"]]
        if r.get("awaiting_documents"):
            result = "Awaiting draft BL (nothing to compare yet)"
        bad = [row for row in (r.get("table") or []) if row["status"] == "mismatch"]
        w.writerow([eid, e["from"], e["subject"], result, r["review_reason"] or "",
                    ", ".join(r["defect_fields"]),
                    "; ".join(f"{x['field']}: SI {x['si']} / BL {x['bl']}" for x in bad) or r.get("detail", ""),
                    "yes" if r.get("human_reviewed") or r.get("resolved") else "no"])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="discrepancy_report.csv"'})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False, threaded=True)
