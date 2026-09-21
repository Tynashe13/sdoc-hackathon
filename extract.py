"""Find the 7 shipment fields in a document, whatever the label wording."""
import re

# Same field, different wording -> one canonical name.  Aligned by meaning.
_TAIL = r"(?:\s*(?:\([^)]*\)|[\u4e00-\u9fff\uff08\uff09（）]+))*"   # "(POL)", "毛重(KGS)"
LABELS = {
    "shipper":          r"shipper(?:/exporter)?",
    "consignee":        r"consignee|to the order of",
    "notify_party":     r"notify(?:\s+party(?:/intermediate consignee)?)?",
    "port_of_loading":  r"port of loading|load port|pol\b",
    "port_of_discharge": r"port of discharge|discharge port|pod\b",
    "container_count":  r"container count|no\. of containers(?: or packages)?|total containers",
    "gross_weight_kg":  r"(?:total\s+)?gross (?:weight|wt)",
}
_PATTERNS = {f: re.compile(rf"^\s*(?:{p}){_TAIL}\s*[:|]?\s*(.*)$", re.I)
             for f, p in LABELS.items()}
FIELDS = list(LABELS)


def doc_type(text: str) -> str:
    """SI, BL, or OTHER (invoice, packing list, certificate of origin ...)."""
    head = text[:400].upper()
    if any(x in head for x in ("COMMERCIAL INVOICE", "PACKING LIST", "CERTIFICATE OF ORIGIN")):
        return "OTHER"
    if "DRAFT" in head and "BILL OF LADING" in head:
        return "BL"
    if "INSTRUCTION" in head:                       # "SHIPPING INSTRUCTION", "BL INSTRUCTION"
        return "SI"
    return "UNKNOWN"


def extract_evidence(text: str) -> dict:
    """{field: {"value", "line", "line_no"} or None}: each value together with the exact document
    line it was read from (line_no counts from 1).  Continuation/address lines are ignored."""
    out = {f: None for f in FIELDS}
    for line_no, line in enumerate(text.splitlines(), 1):
        if line[:1].isspace():                      # indented address line
            continue
        for field, pat in _PATTERNS.items():
            m = pat.match(line)
            if m and out[field] is None:
                value = m.group(1).strip()
                if value:
                    out[field] = {"value": value, "line": line.strip(), "line_no": line_no}
                break
    return out


def extract_raw(text: str) -> dict:
    """{field: raw value string or None}."""
    return {f: (e["value"] if e else None) for f, e in extract_evidence(text).items()}


def find_line(text: str, value: str):
    """Where a value that did not come from a label (e.g. found by the AI) appears in the document:
    {"line", "line_no"} for the first line containing it, or None."""
    want = re.sub(r"\s+", " ", str(value)).strip().lower()
    for line_no, line in enumerate(text.splitlines(), 1):
        if want and want in re.sub(r"\s+", " ", line).lower():
            return {"line": line.strip(), "line_no": line_no}
    return None
