"""Normalise values, then compare SI vs BL field by field."""
import re
from extract import FIELDS

_MISSING = {"", "N/A", "NA", "NIL", "TBA", "TBC", "-", "--"}


def _clean_name(v):
    v = re.split(r"\s*(?:\||;)\s*", v)[0]           # keep name, drop "| address"
    v = re.sub(r"[^\w\s&/]", " ", v.upper())         # punctuation: PTE. LTD. == PTE LTD
    return re.sub(r"\s+", " ", v).strip()


def _clean_port(v):
    v = re.sub(r"\([^)]*\)", " ", v)                 # drop "(CNNTG)" style codes
    v = re.sub(r"[^\w\s/]", " ", v.upper())
    return re.sub(r"\s+", " ", v).strip()


def _num(v):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", v)
    return float(m.group().replace(",", "")) if m else None


def normalise(field, raw):
    """Return a comparable value, or None if the value is missing/unusable."""
    if raw is None or raw.strip().strip("_").upper() in _MISSING:
        return None
    if field in ("shipper", "consignee", "notify_party"):
        return _clean_name(raw) or None
    if field in ("port_of_loading", "port_of_discharge"):
        return _clean_port(raw) or None
    if field in ("container_count", "gross_weight_kg"):
        n = _num(raw)
        return None if n is None else int(round(n))
    return raw.strip().upper()


def compare(si_raw: dict, bl_raw: dict):
    """-> (mismatches, missing).  mismatches = [{field, si, bl}], missing = [(doc, field)]."""
    mismatches, missing = [], []
    for f in FIELDS:
        s, b = normalise(f, si_raw.get(f)), normalise(f, bl_raw.get(f))
        if s is None:
            missing.append(("SI", f))
        if b is None:
            missing.append(("BL", f))
        if s is not None and b is not None and s != b:
            mismatches.append({"field": f, "si": si_raw[f], "bl": bl_raw[f]})
    return mismatches, missing


def field_table(si_raw: dict, bl_raw: dict):
    """One row per field for the report / UI: status is match | mismatch | missing."""
    rows = []
    for f in FIELDS:
        s, b = normalise(f, si_raw.get(f)), normalise(f, bl_raw.get(f))
        status = "missing" if s is None or b is None else ("match" if s == b else "mismatch")
        rows.append({"field": f, "si": si_raw.get(f), "bl": bl_raw.get(f), "status": status})
    return rows
