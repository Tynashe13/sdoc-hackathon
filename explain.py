"""AI-written plain-language reasons for every mismatch and every case that needs review.

    python explain.py        (needs GEMINI_API_KEY; about 3 requests; writes explanations.json)

Gemini is given only the compared values (or the review reason) and asked for one or two plain sentences saying
what differs or why a person must look. It never decides anything: the verdict comes from the rules. A sentence is
kept only if it mentions the values it is explaining; anything else is dropped and the app falls back to a fixed
sentence. Each explanation stores a fingerprint of the facts it was written for, so if a person corrects the case
the old AI sentence is no longer shown.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

FIELD_NAMES = {"shipper": "Shipper", "consignee": "Consignee", "notify_party": "Notify party",
               "port_of_loading": "Port of loading", "port_of_discharge": "Port of discharge",
               "container_count": "Container count", "gross_weight_kg": "Gross weight"}
REVIEW_TEXT = {"wrong_doc_type": "An attachment is not the expected document (an SI or a draft BL)",
               "missing_attachment": "The SI or the draft BL is missing",
               "unreadable": "A document is a scan or a damaged file that cannot be read reliably",
               "missing_value": "A required value is blank or not stated"}
BATCH = 25
MAX_CHARS = 320


def facts(res):
    """What an explanation is about, or None when there is nothing to explain."""
    if res.get("category") != "BL_COMPARISON" or res.get("awaiting_documents"):
        return None
    if res.get("status") == "MISMATCH":
        rows = [{"field": r["field"], "si": r["si"], "bl": r["bl"]}
                for r in res.get("table") or [] if r["status"] == "mismatch"]
        return {"kind": "mismatch", "fields": rows} if rows else None
    if res.get("status") == "NEEDS_REVIEW":
        return {"kind": "review", "reason": res.get("review_reason"), "detail": res.get("detail") or ""}
    return None


def basis(f):
    return hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:16]


# words that appear in almost any sentence or company name, so mentioning them proves nothing
COMMON = {"the", "and", "for", "are", "not", "was", "but", "its", "with", "this", "that", "from", "one", "two",
          "kg", "kgs", "mts", "ltd", "llc", "pte", "inc", "corp", "gmbh", "bhd", "sdn", "pvt", "fze", "limited",
          "company", "trading", "international", "email", "differ", "differs", "different"}


def _tokens(text):
    words = re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()
    return {t for t in words if len(t) >= 3 and t not in COMMON}


def _numbers(text):
    return set(re.findall(r"\d+", str(text).replace(",", "")))


def grounded(text, f):
    """Is this sentence usable? Plain text of sensible length that mentions the values it explains."""
    if not isinstance(text, str) or not 15 <= len(text.strip()) <= MAX_CHARS:
        return False
    if f["kind"] == "review":
        return True
    said, said_numbers = _tokens(text), _numbers(text)
    for row in f["fields"]:
        for v in (row["si"], row["bl"]):
            if not v:
                continue
            if row["field"] in ("container_count", "gross_weight_kg"):
                if _numbers(v) & said_numbers:                 # counts and weights are grounded on their numbers
                    return True
            elif _tokens(v.split(" | ")[0]) & said:            # names count without the address after " | "
                return True
    return False


def _line(eid, f):
    if f["kind"] == "review":
        return f'{eid}: NEEDS REVIEW. {REVIEW_TEXT.get(f["reason"], "A person must look")}. {f["detail"]}'
    parts = [f'{FIELD_NAMES[r["field"]]}: the SI says "{r["si"]}" and the BL says "{r["bl"]}"' for r in f["fields"]]
    return f"{eid}: MISMATCH. " + "; ".join(parts)


def prompt(cases):
    return (
        "You explain shipping-document checks to a busy operations person. Below are cases where the Shipping "
        "Instruction (SI) and the draft Bill of Lading (BL) were compared by fixed rules, or where the check could "
        "not be finished. For each case write ONE or TWO plain sentences (at most 45 words) saying what differs, "
        "quoting the differing values, or why a person has to look. Use only the facts given. Do not decide "
        "anything, do not give advice, do not add facts.\n"
        'Reply as JSON that maps each case id to its sentence, for example {"email_001": "The consignee differs: ..."}.\n\n'
        + "\n".join(_line(eid, f) for eid, f in cases))


def run(results, ask):
    """-> ({email_id: {"text", "basis"}}, number of cases, number dropped as ungrounded). `ask` is llm.ask_json."""
    cases = sorted((eid, f) for eid, r in results.items() if (f := facts(r)))
    out, dropped = {}, 0
    for i in range(0, len(cases), BATCH):
        chunk = cases[i:i + BATCH]
        reply = ask(prompt(chunk))
        if isinstance(reply, dict) and isinstance(reply.get("explanations"), dict):
            reply = reply["explanations"]
        if not isinstance(reply, dict):
            continue
        for eid, f in chunk:
            text = reply.get(eid)
            if grounded(text, f):
                out[eid] = {"text": text.strip(), "basis": basis(f)}
            else:
                dropped += 1
    return out, len(cases), dropped


def load(path="explanations.json"):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("explanations", {})
    except (OSError, ValueError, AttributeError):
        return {}


def main():
    os.environ.setdefault("USE_LLM", "1")
    import llm
    out_path = os.getenv("EXPLANATIONS_FILE", "explanations.json")
    results = json.loads(Path(os.getenv("RESULTS_FILE", "results.json")).read_text(encoding="utf-8"))["results"]
    if not llm.enabled():
        print("No GEMINI_API_KEY found (put it in .env), so nothing was written.")
        return 1
    llm.TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "180000"))
    llm.MAX_CALLS = int(os.getenv("LLM_MAX_CALLS", "12"))
    used = set()

    def ask(prompt):
        out = llm.ask_json_any(prompt)               # falls back to another model when the main one is busy
        if out is not None and llm.LAST_MODEL:
            used.add(llm.LAST_MODEL)
        return out

    found, cases, dropped = run(results, ask)
    if llm.FAILED:
        print(f"{len(llm.FAILED)} Gemini call(s) failed ({llm.FAILED[0]}), so {out_path} was NOT written. "
              "Try again in a few minutes; answers that did arrive are cached.")
        return 1
    Path(out_path).write_text(json.dumps({"model": sorted(used) or [llm.MODEL], "explanations": found}, indent=1, sort_keys=True,
                                         ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path}: {len(found)} explanations for {cases} cases ({dropped} dropped because they did not "
          f"mention the values); Gemini requests sent: {llm.CALLS}; model(s) used: {', '.join(sorted(used)) or llm.MODEL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
