"""Normalise values, then compare SI vs BL field by field.

normalise() turns a raw string into a comparable value (None = missing).  Names and
plain numbers compare with ==; containers, weights and ports need their own rule, so
every comparison goes through same().
"""
import re
import unicodedata
from collections import Counter
from extract import FIELDS

_MISSING = {"", "N/A", "NA", "NIL", "TBA", "TBC", "-", "--"}

# ---- names -------------------------------------------------------------------------
# Same legal form, different spelling.  Only spellings are merged: "ACME" vs "ACME CO"
# and "LTD" vs "INC" stay different so a reviewer still sees them.
_NAME_WORDS = {"LIMITED": "LTD", "PRIVATE": "PVT", "PTE": "PVT", "COMPANY": "CO",
               "CORPORATION": "CORP", "INCORPORATED": "INC", "BERHAD": "BHD", "AND": "&"}


def _clean_name(v):
    v = re.split(r"\s*(?:\||;)\s*", v)[0]           # keep name, drop "| address"
    v = "".join(c for c in unicodedata.normalize("NFKD", v.upper()) if not unicodedata.combining(c))
    v = re.sub(r"\b(?:[A-Z]\.){2,}", lambda m: m.group().replace(".", ""), v)   # S.A. -> SA
    v = re.sub(r"[^\w\s&/]", " ", v)                 # punctuation: PTE. LTD. == PTE LTD
    return " ".join(_NAME_WORDS.get(w, w) for w in v.split())


# ---- ports -------------------------------------------------------------------------
# A 5-character UN/LOCODE in brackets, e.g. "(CNNTG)".  Its country part must be a real ISO
# country, so that "(DUBAI)" is read as a name, not a code.
_COUNTRIES = set("""AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN
BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC
EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR
HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT
LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP
NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL
SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE
VG VI VN VU WF WS YE YT ZA ZM ZW""".split())


def _is_code(text):
    """A 2-letter country ("MY") or a 5-character UN/LOCODE ("CNNTG")."""
    return text in _COUNTRIES or (re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", text) is not None
                                  and text[:2] in _COUNTRIES)


def _clean_port(v):
    """-> (name, code or None).  Brackets holding a code are dropped; any other bracketed
    text stays, because "(DUBAI)" is part of the name."""
    v = v.upper()
    code = next((t for t in (b.strip() for b in re.findall(r"\(([^)]*)\)", v))
                 if len(t) == 5 and _is_code(t)), None)
    v = re.sub(r"\(([^)]*)\)", lambda m: " " if _is_code(m.group(1).strip()) else f" {m.group(1)} ", v)
    v = re.sub(r"[^\w\s/]", " ", v)
    return re.sub(r"\s+", " ", v).strip(), code


# ---- containers --------------------------------------------------------------------
# "6 x 40'HC" -> (6, 40, "HC").  FCL/LCL say how the box is loaded, not what it is, so
# they count as "no type given".
_BOX = re.compile(r"(\d+)\s*[xX×]\s*(\d{2})(?!\d)\s*['’]?\s*([A-Za-z][A-Za-z ]{0,14})?")
_BOX_TYPES = {"HC": "HC", "HQ": "HC", "HIGHCUBE": "HC", "GP": "GP", "DC": "GP", "ST": "GP",
              "GENERALPURPOSE": "GP", "DRY": "GP", "RF": "RF", "REEFER": "RF", "OT": "OT",
              "FR": "FR", "TK": "TK"}


def _box_type(text):
    words = (text or "").upper().split()
    for cand in ["".join(words)] + words:
        if cand in _BOX_TYPES:
            return _BOX_TYPES[cand]
    return None


def _containers(v):
    groups = [(int(n), int(size), _box_type(t)) for n, size, t in _BOX.findall(v)]
    if groups:
        return tuple(sorted(groups, key=lambda g: (g[1], g[2] or "", g[0])))
    n = re.search(r"\d+", v)
    return ((int(n.group()), None, None),) if n else None


def _same_containers(a, b):
    if any(size is None for _, size, _ in a + b):    # no sizes stated: only the count is comparable
        return sum(n for n, _, _ in a) == sum(n for n, _, _ in b)
    for size in {g[1] for g in a + b}:
        ga, gb = [g for g in a if g[1] == size], [g for g in b if g[1] == size]
        if all(t for _, _, t in ga + gb):            # types stated on both sides: compare per type
            tally = lambda gs: Counter(t for n, _, t in gs for _ in range(n))
            if tally(ga) != tally(gb):
                return False
        elif sum(n for n, _, _ in ga) != sum(n for n, _, _ in gb):
            return False
    return True


# ---- weights -----------------------------------------------------------------------
_KG_PER = {"KG": 1, "KGS": 1, "KILO": 1, "KILOS": 1, "KILOGRAM": 1, "KILOGRAMS": 1,
           "MT": 1000, "MTS": 1000, "T": 1000, "TON": 1000, "TONS": 1000, "TONNE": 1000,
           "TONNES": 1000, "LB": 0.45359237, "LBS": 0.45359237, "POUND": 0.45359237,
           "POUNDS": 0.45359237}


def _weight(v):
    """-> (kilograms, tolerance in kg) or None.  The tolerance is half of the last printed
    digit, so '131,058 KG' and '131,058.4 KG' agree but '131,058.7 KG' does not."""
    m = re.search(r"(\d[\d.,]*)\s*([A-Za-z]+)?", v)
    if not m:
        return None
    num, factor = m.group(1).rstrip(".,"), _KG_PER.get((m.group(2) or "KG").upper(), 1)
    if "," in num and "." in num:                    # the last separator is the decimal point
        dec = "," if num.rfind(",") > num.rfind(".") else "."
        num = num.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in num:
        num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", num) else num.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", num) and factor == 1:   # 131.058 KG = 131,058 KG
        num = num.replace(".", "")
    decimals = len(num.split(".")[1]) if "." in num else 0
    return round(float(num) * factor, 4), 0.5 * 10 ** -decimals * factor


# ---- public API --------------------------------------------------------------------
def normalise(field, raw):
    """Return a comparable value, or None if the value is missing/unusable."""
    if raw is None or raw.strip().strip("_").upper() in _MISSING:
        return None
    if field in ("shipper", "consignee", "notify_party"):
        return _clean_name(raw) or None
    if field in ("port_of_loading", "port_of_discharge"):
        name, code = _clean_port(raw)
        return (name, code) if name or code else None
    if field == "container_count":
        return _containers(raw)
    if field == "gross_weight_kg":
        return _weight(raw)
    return raw.strip().upper()


def same(field, s, b):
    """Do two normalised values (both not None) agree?"""
    if field in ("port_of_loading", "port_of_discharge"):
        if s[0] != b[0]:                             # the name decides: the labelled data counts a
            return False                             # swapped port as a defect even if the code stayed
        return not (s[1] and b[1] and s[1] != b[1])  # same name but two different codes is a conflict
    if field == "container_count":
        return _same_containers(s, b)
    if field == "gross_weight_kg":
        return abs(s[0] - b[0]) <= s[1] + b[1] + 1e-9
    return s == b


def compare(si_raw: dict, bl_raw: dict):
    """-> (mismatches, missing).  mismatches = [{field, si, bl}], missing = [(doc, field)]."""
    mismatches, missing = [], []
    for f in FIELDS:
        s, b = normalise(f, si_raw.get(f)), normalise(f, bl_raw.get(f))
        if s is None:
            missing.append(("SI", f))
        if b is None:
            missing.append(("BL", f))
        if s is not None and b is not None and not same(f, s, b):
            mismatches.append({"field": f, "si": si_raw[f], "bl": bl_raw[f]})
    return mismatches, missing


def field_table(si_raw: dict, bl_raw: dict):
    """One row per field for the report / UI: status is match | mismatch | missing."""
    rows = []
    for f in FIELDS:
        s, b = normalise(f, si_raw.get(f)), normalise(f, bl_raw.get(f))
        status = "missing" if s is None or b is None else ("match" if same(f, s, b) else "mismatch")
        rows.append({"field": f, "si": si_raw.get(f), "bl": bl_raw.get(f), "status": status})
    return rows
