"""Inbox -> one result per email (the shape the self-evaluation expects)."""
import json, re, sys
from loader import Inbox
import llm
from classify import classify_by_rules, body_core
from readers import read_attachment, pdf_page_pngs, ReadError, NoTextError
from extract import FIELDS, doc_type, extract_evidence, extract_raw, find_line
from compare import compare, field_table, normalise

EMPTY = {f: None for f in FIELDS}


def review(reason, detail, form=None, **extra):
    return {"status": "NEEDS_REVIEW", "review_reason": reason, "has_defect": False,
            "defect_fields": [], "detail": detail, "mismatches": [], "form": form, **extra}


def make_form(si_raw, bl_raw, si_src, bl_src, si_ev=None, bl_ev=None):
    """What a human reviewer sees and can correct: both sides, plus where each came from."""
    blank = lambda raw: {f: (v if normalise(f, v) is not None else None) for f, v in raw.items()}  # "N/A" -> empty box
    return {"si": blank(si_raw), "bl": blank(bl_raw), "si_source": si_src, "bl_source": bl_src,
            "si_evidence": si_ev or {}, "bl_evidence": bl_ev or {}}


def evidence_for(text, doc, raw):
    """{field: {"doc", "line_no", "line"}} for every value of raw that can be traced to a line of
    the document: the label line it was read from, or the first line that contains it."""
    if not text:
        return {}
    found = extract_evidence(text)
    out = {}
    for f, value in raw.items():
        hit = found[f] if found[f] and found[f]["value"] == value else (value and find_line(text, value))
        if hit:
            out[f] = {"doc": doc, "line_no": hit["line_no"], "line": hit["line"]}
    return out


def with_evidence(table, si_ev, bl_ev):
    """Attach the source line of each value to its row of the comparison table."""
    return [{**row, "si_evidence": si_ev.get(row["field"]), "bl_evidence": bl_ev.get(row["field"])}
            for row in table]


def suggest_from_scan(scans, docs):
    """A scan cannot be trusted blindly, so the vision read is only a SUGGESTION that goes
    to the human reviewer together with what it would have flagged."""
    for name, data in scans.items():
        try:
            fields = llm.read_scan(pdf_page_pngs(data))
        except Exception:
            fields = None
        if not fields:
            continue
        suggestion = {"document": name, "read_by": "gemini-vision", "fields": fields}
        other = "_BL." if "_SI." in name else "_SI."
        other_text = next((t for n, t in docs.items() if other in n), None)
        if other_text:
            si, bl = (fields, extract_raw(other_text)) if "_SI." in name else (extract_raw(other_text), fields)
            mism, missing = compare(si, bl)
            suggestion["would_flag"] = [m["field"] for m in mism]
            suggestion["unreadable_fields"] = [f for _, f in missing]
        return suggestion
    return None


def check_documents(inbox, email):
    """Stage 2 + 3 for one BL_COMPARISON email."""
    atts = email["attachments"]
    text = body_core(email).lower()
    docs, scans, problems = {}, {}, []
    for path in atts:
        name = path.rsplit("/", 1)[-1]
        data = inbox.read_bytes(path)
        try:
            docs[name] = read_attachment(name, data)
        except NoTextError as exc:                 # opens fine, but it is only a picture
            scans[name] = data
            problems.append(f"{name}: {exc}")
        except ReadError as exc:                   # corrupt / unsupported: no AI can help
            problems.append(f"{name}: {exc}")
    si_name, si_text = next(((n, t) for n, t in docs.items() if "_SI." in n), (None, None))
    bl_name, bl_text = next(((n, t) for n, t in docs.items() if "_BL." in n), (None, None))
    wrong = [lab for lab, t in (("SI", si_text), ("BL", bl_text)) if t and doc_type(t) == "OTHER"]
    si_raw = extract_raw(si_text) if si_text and "SI" not in wrong else dict(EMPTY)
    bl_raw = extract_raw(bl_text) if bl_text and "BL" not in wrong else dict(EMPTY)
    src = lambda t, lab: "read from the document" if t and lab not in wrong else "not available"

    if len(atts) < 2:
        # "please send the draft BL" is a request, not a check: nothing to compare yet
        if re.search(r"\battach|compare|missing|dropped", text) and "send the draft" not in text:
            return review("missing_attachment", f"{len(atts)} of 2 attachments received",
                          make_form(si_raw, bl_raw, src(si_text, "SI"), src(bl_text, "BL"),
                                    evidence_for(si_text, si_name, si_raw), evidence_for(bl_text, bl_name, bl_raw)))
        return {"status": "OK", "review_reason": None, "has_defect": False,
                "defect_fields": [], "detail": "draft BL requested; nothing to compare yet",
                "mismatches": [], "awaiting_documents": True}
    if problems:
        suggestion = suggest_from_scan(scans, docs) if scans else None
        si_src, bl_src = src(si_text, "SI"), src(bl_text, "BL")
        if suggestion:                              # pre-fill the scanned side with the AI reading
            if "_SI." in suggestion["document"]:
                si_raw, si_src = dict(suggestion["fields"]), "AI vision reading (unverified)"
            else:
                bl_raw, bl_src = dict(suggestion["fields"]), "AI vision reading (unverified)"
        out = review("unreadable", "; ".join(problems),
                     make_form(si_raw, bl_raw, si_src, bl_src,
                               None if si_src.startswith("AI") else evidence_for(si_text, si_name, si_raw),
                               None if bl_src.startswith("AI") else evidence_for(bl_text, bl_name, bl_raw)))
        if suggestion:
            out.update(ai_assisted=True, ai_suggestion=suggestion,
                       ai_notes=["scan read by vision model; needs human confirmation"])
        return out
    if wrong:
        return review("wrong_doc_type", "; ".join(f"the '{l}' attachment is not a {l}" for l in wrong),
                      make_form(si_raw, bl_raw, src(si_text, "SI"), src(bl_text, "BL"),
                                evidence_for(None if "SI" in wrong else si_text, si_name, si_raw),
                                evidence_for(None if "BL" in wrong else bl_text, bl_name, bl_raw)))
    notes = []
    for label, t, raw in (("SI", si_text, si_raw), ("BL", bl_text, bl_raw)):
        gaps = [f for f in FIELDS if raw[f] is None]
        for f, v in llm.fill_missing(t, gaps).items():      # AI only fills what rules missed
            raw[f] = v
            notes.append(f"{label} {f} found by AI: {v}")
    mismatches, missing = compare(si_raw, bl_raw)
    si_ev, bl_ev = evidence_for(si_text, si_name, si_raw), evidence_for(bl_text, bl_name, bl_raw)
    table = with_evidence(field_table(si_raw, bl_raw), si_ev, bl_ev)
    if missing:
        return review("missing_value", "; ".join(f"{d}: {f}" for d, f in missing),
                      make_form(si_raw, bl_raw, "read from the document", "read from the document", si_ev, bl_ev),
                      table=table, ai_assisted=bool(notes), ai_notes=notes)
    fields = [m["field"] for m in mismatches]
    return {"status": "MISMATCH" if fields else "OK", "review_reason": None,
            "has_defect": bool(fields), "defect_fields": fields,
            "detail": "No mismatch detected" if not fields else "; ".join(
                f"{m['field']}: SI {m['si']} / BL {m['bl']}" for m in mismatches),
            "mismatches": mismatches, "table": table, "ai_assisted": bool(notes), "ai_notes": notes}


def process_email(inbox, email):
    """Everything for ONE email (also used for 'Retry' in the web app)."""
    category = classify_by_rules(email)
    decided_by = "rule"
    ai_notes = []
    if category is None:                      # rules unsure -> ask the AI for a second opinion
        answer = llm.classify_email(email, body_core(email))
        if answer:
            category, decided_by = answer["category"], "llm"
            ai_notes.append(f"classified by AI ({answer.get('confidence')}): {answer.get('reason')}")
        else:
            category, decided_by = "GENERAL", "fallback"
    res = {"category": category, "decided_by": decided_by, "status": "OK", "review_reason": None,
           "has_defect": False, "defect_fields": [], "ai_assisted": bool(ai_notes),
           "ai_notes": ai_notes}
    if category == "BL_COMPARISON":
        res.update(check_documents(inbox, email))
    return res


def run(source):
    inbox = Inbox(source)
    return {email["email_id"]: process_email(inbox, email) for email in inbox}


if __name__ == "__main__":
    results = run(sys.argv[1] if len(sys.argv) > 1 else "data")
    json.dump(results, open("submission.json", "w"), indent=2)
    print(f"wrote submission.json for {len(results)} emails")
