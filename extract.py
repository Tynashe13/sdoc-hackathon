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


def extract_raw(text: str) -> dict:
    """{field: raw value string or None}.  Continuation/address lines are ignored."""
    out = {f: None for f in FIELDS}
    for line in text.splitlines():
        if line[:1].isspace():                      # indented address line
            continue
        for field, pat in _PATTERNS.items():
            m = pat.match(line)
            if m and out[field] is None:
                value = m.group(1).strip()
                out[field] = value or None
                break
    return out
