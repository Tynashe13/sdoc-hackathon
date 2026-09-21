"""Document-level fuzzer: rewrite real SI/BL text files, then run the real extractor and comparator.

  layout    the file is laid out differently (line endings, blank lines, label wording, order ...)
            -> the verdict must be exactly what it was for the original file
  failsafe  wording the extractor does NOT know -> it may fail to read a value, but it must then say so
            (missing -> a person reviews it); it must never turn a defect into a clean "no mismatch"
  defect    one field of the BL is given a real defect (a mutation from validation.fuzz)
            -> that field, and only that field, must be reported as a mismatch

Only .txt attachments are rewritten (PDF/DOCX/XLSX are read by the same extractor after conversion
to text, and are covered by the snapshot tests).   python -m validation.fuzz_docs [seed]
"""
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from compare import compare
from extract import FIELDS, extract_evidence, extract_raw
from loader import Inbox
from validation import fuzz

# other wordings of the same label that the extractor is meant to understand (see extract.LABELS)
SYNONYMS = {
    "consignee": ["To the Order of", "Consignee"],
    "notify_party": ["Notify", "Notify Party", "Notify Party/Intermediate Consignee"],
    "port_of_loading": ["Port of Loading", "Load Port", "POL"],
    "port_of_discharge": ["Port of Discharge", "Discharge Port", "POD"],
    "container_count": ["Container Count", "Total Containers", "No. of Containers"],
    "gross_weight_kg": ["Gross Weight", "Total Gross Weight", "Gross Wt"],
    "shipper": ["Shipper", "Shipper/Exporter"],
}


def _lines(text):
    return text.replace("\r\n", "\n").split("\n")


def _relabel(text, rng):
    """Same values, different label wording (only labels the extractor knows)."""
    ev = extract_evidence(text)
    lines = _lines(text)
    for f, e in ev.items():
        if e:
            old = lines[e["line_no"] - 1]
            lines[e["line_no"] - 1] = f"{rng.choice(SYNONYMS[f])}: {e['value']}"
    return "\n".join(lines)


def _shuffle(text, rng):
    lines = _lines(text)
    body = [i for i, l in enumerate(lines) if i > 0 and l.strip() and not l[:1].isspace() and re.match(r"[A-Za-z/ .()]+\s*[:|]", l)]
    vals = [lines[i] for i in body]
    rng.shuffle(vals)
    for i, l in zip(body, vals):
        lines[i] = l
    return "\n".join(lines)


LAYOUT = {
    "windows line endings": lambda t, r: t.replace("\r\n", "\n").replace("\n", "\r\n"),
    "blank lines between rows": lambda t, r: "\n\n".join(_lines(t)),
    "trailing spaces": lambda t, r: "\n".join(l + "   " for l in _lines(t)),
    "labels in capitals": lambda t, r: "\n".join((re.sub(r"^([^:|]+)", lambda m: m.group(1).upper(), l) if not l[:1].isspace() else l) for l in _lines(t)),
    "space before the colon": lambda t, r: "\n".join((re.sub(r"^([^:|]+?)\s*:", r"\1 :", l) if not l[:1].isspace() else l) for l in _lines(t)),
    "bar instead of colon": lambda t, r: "\n".join((re.sub(r"^([A-Za-z/ .()]+?)\s*:\s", r"\1 | ", l) if not l[:1].isspace() else l) for l in _lines(t)),
    "rows in a different order": _shuffle,
    "other label wording": _relabel,
    "page furniture between rows": lambda t, r: "\n".join(l + ("\nPage 1 of 2\nRef: 5APH-99042 / HLCUSIN832856914" if r.random() < .5 else "") for l in _lines(t)),
    "leading/trailing blank lines": lambda t, r: "\n\n\n" + t + "\n\n\n",
}


UNKNOWN = {"shipper": "Exporter Name", "consignee": "Cnee", "notify_party": "Also Notify",
           "port_of_loading": "Origin Port", "port_of_discharge": "Destination Port",
           "container_count": "Equipment", "gross_weight_kg": "Cargo Weight"}


def _unknown_label(text, rng):
    """Every label replaced by wording that is not in extract.LABELS."""
    lines = _lines(text)
    for f, e in extract_evidence(text).items():
        if e:
            lines[e["line_no"] - 1] = f"{UNKNOWN[f]}: {e['value']}"
    return "\n".join(lines)


def _value_below(text, rng):
    """`Label:` alone on a line, its value on the next (indented) line."""
    lines = _lines(text)
    for f, e in extract_evidence(text).items():
        if e:
            i = e["line_no"] - 1
            lines[i] = lines[i][: lines[i].rindex(e["value"])].rstrip() + "\n    " + e["value"]
    return "\n".join(lines)


def _typo_label(text, rng):
    lines = _lines(text)
    for f, e in extract_evidence(text).items():
        if e:
            i = e["line_no"] - 1
            lines[i] = re.sub(r"^(\w)(\w)", r"\2\1", lines[i])          # first two letters swapped
    return "\n".join(lines)


FAILSAFE = {"labels the extractor does not know": _unknown_label,
            "value on the line below its label": _value_below,
            "mistyped labels": _typo_label}


def _replace_value(text, field, new):
    ev = extract_evidence(text)[field]
    if not ev:
        return None
    lines = _lines(text)
    line = lines[ev["line_no"] - 1]
    lines[ev["line_no"] - 1] = line[: line.rindex(ev["value"])] + new
    return "\n".join(lines)


def load_docs(data="data", results="results.json"):
    """[(email_id, si_text, bl_text)] for every checked pair that has plain-text attachments."""
    inbox = Inbox(data)
    res = json.loads(Path(results).read_text())["results"]
    out = []
    for e in inbox:
        r = res.get(e["email_id"], {})
        atts = e["attachments"]
        if r.get("table") and len(atts) == 2 and all(a.endswith(".txt") for a in atts):
            si, bl = sorted(atts, key=lambda a: "_SI." not in a)
            out.append((e["email_id"], inbox.read_bytes(si).decode(), inbox.read_bytes(bl).decode()))
    return out


def outcome(si_text, bl_text):
    mism, missing = compare(extract_raw(si_text), extract_raw(bl_text))
    return sorted(m["field"] for m in mism), sorted(f for _, f in missing)


def run(seed=1, data="data", results="results.json"):
    rng = random.Random(seed)
    docs = load_docs(data, results)
    rows = []
    for name, fn in LAYOUT.items():
        n = ok = 0
        fails = []
        for eid, si, bl in docs:
            want = outcome(si, bl)
            got = outcome(fn(si, rng), fn(bl, rng))
            n += 1
            if got == want:
                ok += 1
            elif len(fails) < 3:
                fails.append({"email": eid, "expected": want, "got": got})
        rows.append({"kind": "layout", "name": name, "n": n, "ok": ok, "failures": fails})
    for name, fn in FAILSAFE.items():
        n = ok = loud = 0
        fails = []
        for eid, si, bl in docs:
            want = outcome(si, bl)
            got = outcome(fn(si, rng), fn(bl, rng))
            n += 1
            if got == want:
                ok += 1                      # read fine anyway
            elif got[1]:
                ok += 1
                loud += 1                    # could not read a value and said so
            elif len(fails) < 3:
                fails.append({"email": eid, "expected": want, "got": got})
        rows.append({"kind": "failsafe", "name": name, "n": n, "ok": ok, "escalated": loud, "failures": fails})
    defects = [m for m in fuzz.MUTATIONS if m[1] == "defect"]
    stats = defaultdict(lambda: {"n": 0, "ok": 0, "failures": []})
    pairs = fuzz.load_pairs(results)
    pool = {"names": sorted({si for f, si, _ in pairs if f in fuzz.NAMES}),
            "ports": sorted({si for f, si, _ in pairs if f in fuzz.PORTS})}
    for eid, si, bl in docs:
        raws = extract_raw(bl)
        for group, kind, name, fields, fn in defects:
            for f in fields:
                if not raws.get(f) or f not in FIELDS:
                    continue
                fuzz._CTX["si"] = extract_raw(si).get(f)
                try:
                    new = fn(raws[f], rng, pool)
                except (ValueError, IndexError, TypeError):
                    new = None
                if new is None or new == raws[f]:
                    continue
                edited = _replace_value(bl, f, new)
                if edited is None or outcome(si, bl) != ([], []):
                    continue                         # only start from pairs that agree
                st = stats[(group, name)]
                st["n"] += 1
                if outcome(si, edited) == ([f], []):
                    st["ok"] += 1
                elif len(st["failures"]) < 3:
                    st["failures"].append({"email": eid, "field": f, "bl": new, "got": outcome(si, edited)})
    for (group, name), st in stats.items():
        rows.append({"kind": "defect", "name": f"{group}: {name}", **st})
    return {"seed": seed, "documents": len(docs), "rows": rows}


def summarise(rep):
    tot = defaultdict(lambda: [0, 0])
    for r in rep["rows"]:
        tot[r["kind"]][0] += r["n"]
        tot[r["kind"]][1] += r["ok"]
    return {k: tuple(v) for k, v in tot.items()}


if __name__ == "__main__":
    rep = run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    print(f"{rep['documents']} text document pairs")
    for r in rep["rows"]:
        flag = "" if r["ok"] == r["n"] else "   <-- FAILS"
        extra = f"  (escalated to a person: {r['escalated']})" if "escalated" in r else ""
        print(f"{r['kind']:8} {r['name']:44} {r['ok']:4}/{r['n']:<4}{flag}{extra}")
        for f in r["failures"][:2]:
            print("        e.g.", f)
    for k, (n, ok) in summarise(rep).items():
        print(f"TOTAL {k}: {ok}/{n}")
