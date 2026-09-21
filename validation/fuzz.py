"""Field-level fuzzer: how does the comparator behave on inputs the organisers' generator never made?

Starting from the real SI/BL value pairs that agree in the data, each mutation rewrites the BL value:

  benign   a change of formatting only        -> the pair must STILL be a match (no false alarm)
  defect   a change of meaning                -> the pair must be a MISMATCH      (defect caught)
  missing  the value is blanked ("N/A" ...)   -> the pair must be reported MISSING (goes to a person)
  limit    a change the checker ignores on purpose (the address after " | ") -> still a match; listed
           as a known limit, not counted as a pass or a failure

Everything is seeded, so the same seed gives the same cases.
    python -m validation.fuzz [seed]
"""
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from compare import normalise, same
from extract import FIELDS

NAMES = ("shipper", "consignee", "notify_party")
PORTS = ("port_of_loading", "port_of_discharge")
LONG_FORMS = {"LTD": "LIMITED", "CO": "COMPANY", "INC": "INCORPORATED", "CORP": "CORPORATION", "BHD": "BERHAD"}
SHORT_FORMS = {v: k for k, v in LONG_FORMS.items()}
LEGAL = ["LTD", "LLC", "INC", "GMBH", "PTE", "BHD", "LIMITED", "CO", "CORP"]


def verdict(field, si, bl):
    s, b = normalise(field, si), normalise(field, bl)
    if s is None or b is None:
        return "missing"
    return "match" if same(field, s, b) else "mismatch"


def load_pairs(results="results.json"):
    """Real (field, si, bl) triples that the system already judged equal."""
    rows = json.loads(Path(results).read_text(encoding="utf-8"))["results"].values()
    seen, out = set(), []
    for res in rows:
        for r in res.get("table") or []:
            key = (r["field"], r["si"])
            if r["status"] == "match" and r["si"] and r["bl"] and key not in seen:
                seen.add(key)
                out.append((r["field"], r["si"], r["bl"]))
    return out


# ------------------------------------------------------------------ helpers
def _words(v):
    return re.findall(r"[A-Za-z0-9&]+", v)


def _sub_word(v, fn):
    """Apply fn to the first word of 4+ letters; None if there is none."""
    for m in re.finditer(r"[A-Za-z]{4,}", v):
        new = fn(m.group())
        if new and new != m.group():
            return v[:m.start()] + new + v[m.end():]
    return None


_CTX = {"si": None}          # the SI value of the pair being mutated, for mutations that depend on it


def _key(field, v):
    """What decides sameness for a name or a port: the cleaned name (ports: not the code)."""
    n = normalise(field, v)
    return n[0] if field in PORTS and n else n


def _other(rng, pool, avoid):
    cands = [p for p in pool if _key(avoid[0], p) != _key(avoid[0], avoid[1])]
    return rng.choice(cands) if cands else None


def _on_name(fn):
    """Apply a mutation to the name part only (before " | address"), then put the address back."""
    def wrapped(v, r, p):
        head, sep, tail = v.partition(" | ")
        new = fn(head, r, p)
        return None if new is None else new + sep + tail
    return wrapped


def _swap_suffix(v, table):
    return re.sub(r"\b(" + "|".join(table) + r")\b\.?", lambda m: table[m.group(1).upper()], v, count=1, flags=re.I) \
        if re.search(r"\b(" + "|".join(table) + r")\b", v, re.I) else None


# ------------------------------------------------------------------ the mutations
# each: (group, kind, name, fields, fn(value, rng, pool) -> new value | None if it does not apply)
def _wt(v):
    m = re.search(r"(\d[\d,.]*)", v)
    if not m or not re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", m.group(1)):
        return None
    return int(m.group(1).replace(",", ""))


def _fmt_kg(n, unit=" KG"):
    return f"{n:,}{unit}"


def _cont(v):
    m = re.match(r"\s*(\d+)\s*[xX]\s*(\d+)'?\s*([A-Za-z]*)", v)
    return (int(m.group(1)), m.group(2), m.group(3)) if m else None


MUTATIONS = [
    # ---- names: harmless
    ("name", "benign", "lower case", NAMES, lambda v, r, p: v.lower()),
    ("name", "benign", "title case", NAMES, lambda v, r, p: v.title()),
    ("name", "benign", "extra spaces", NAMES, lambda v, r, p: "  " + v.replace(" ", "   ") + " "),
    ("name", "benign", "punctuation removed", NAMES, lambda v, r, p: re.sub(r"[.,]", "", v) if re.search(r"[.,]", v) else None),
    ("name", "benign", "legal form written out", NAMES, lambda v, r, p: _swap_suffix(v, LONG_FORMS)),
    ("name", "benign", "legal form abbreviated", NAMES, lambda v, r, p: _swap_suffix(v, SHORT_FORMS)),
    ("name", "benign", "address appended", NAMES, lambda v, r, p: v + " | 12 HARBOUR ROAD, SINGAPORE 049213"),
    ("name", "benign", "accented letters", NAMES, lambda v, r, p: v.replace("E", "É", 1) if "E" in v else None),
    # ---- names: real defects
    ("name", "defect", "different company", NAMES, lambda v, r, p: _other(r, p["names"], ("consignee", v))),
    ("name", "defect", "one letter changed", NAMES, _on_name(lambda v, r, p: _sub_word(v, lambda w: w[:-2] + ("Z" if w[-2] != "Z" else "Q") + w[-1]))),
    ("name", "defect", "one letter dropped", NAMES, _on_name(lambda v, r, p: _sub_word(v, lambda w: w[:1] + w[2:]))),
    ("name", "defect", "two letters swapped", NAMES, _on_name(lambda v, r, p: _sub_word(v, lambda w: w[:1] + w[2] + w[1] + w[3:] if w[1] != w[2] else None))),
    ("name", "defect", "word added", NAMES, _on_name(lambda v, r, p: v + " TRADING")),
    ("name", "defect", "word dropped", NAMES, _on_name(lambda v, r, p: " ".join(v.split()[:-1]) if len(v.split()) > 2 else None)),
    ("name", "defect", "legal form swapped", NAMES, _on_name(lambda v, r, p: re.sub(r"\bLTD\b", "GMBH", v, count=1) if re.search(r"\bLTD\b", v) else None)),
    ("name", "defect", "digit changed", NAMES, _on_name(lambda v, r, p: re.sub(r"\d", lambda m: str((int(m.group()) + 1) % 10), v, count=1) if re.search(r"\d", v) else None)),
    # ---- names: what is deliberately NOT compared (the address after " | ")
    ("name", "limit", "address text changed", NAMES, lambda v, r, p: v.partition(" | ")[0] + " | 99 OTHER STREET; ELSEWHERE" if " | " in v else None),
    ("name", "limit", "address dropped", NAMES, lambda v, r, p: v.partition(" | ")[0] if " | " in v else None),
    # ---- ports: harmless
    ("port", "benign", "lower case", PORTS, lambda v, r, p: v.lower()),
    ("port", "benign", "UN/LOCODE dropped", PORTS, lambda v, r, p: re.sub(r"\s*\([A-Z]{2}[A-Z0-9]{3}\)", "", v) if re.search(r"\([A-Z]{2}[A-Z0-9]{3}\)", v) else None),
    ("port", "benign", "comma removed", PORTS, lambda v, r, p: v.replace(",", "") if "," in v else None),
    ("port", "benign", "extra spaces", PORTS, lambda v, r, p: v.replace(" ", "   ")),
    # ---- ports: real defects
    ("port", "defect", "different port", PORTS, lambda v, r, p: _other(r, p["ports"], ("port_of_loading", v))),
    ("port", "defect", "one letter changed", PORTS, lambda v, r, p: _sub_word(v, lambda w: w[:-2] + ("Z" if w[-2] != "Z" else "Q") + w[-1])),
    ("port", "defect", "same name, other UN/LOCODE", PORTS, lambda v, r, p: re.sub(r"\(([A-Z]{2})[A-Z0-9]{3}\)", lambda m: f"({m.group(1)}ZZZ)", v) if re.search(r"\([A-Z]{2}[A-Z0-9]{3}\)", v) and re.search(r"\([A-Z]{2}[A-Z0-9]{3}\)", _CTX["si"] or "") else None),
    ("port", "defect", "other country", PORTS, lambda v, r, p: re.sub(r",\s*[A-Za-z ]+", ", ATLANTIS", v, count=1) if "," in v else None),
    # ---- containers: harmless
    ("container", "benign", "no spaces, capital X", ("container_count",), lambda v, r, p: re.sub(r"\s+", "", v).replace("x", "X") if _cont(v) else None),
    ("container", "benign", "foot mark dropped", ("container_count",), lambda v, r, p: v.replace("'", "") if "'" in v else None),
    ("container", "benign", "space before type", ("container_count",), lambda v, r, p: re.sub(r"(\d)([A-Za-z])", r"\1 \2", v.replace("'", "' ")) if _cont(v) else None),
    ("container", "benign", "lower case", ("container_count",), lambda v, r, p: v.lower()),
    # ---- containers: real defects
    ("container", "defect", "count + 1", ("container_count",), lambda v, r, p: (lambda c: f"{c[0] + 1} x {c[1]}'{c[2]}")(_cont(v)) if _cont(v) else None),
    ("container", "defect", "count - 1", ("container_count",), lambda v, r, p: (lambda c: f"{c[0] - 1} x {c[1]}'{c[2]}")(_cont(v)) if _cont(v) and _cont(v)[0] > 1 else None),
    ("container", "defect", "size 40 <-> 20", ("container_count",), lambda v, r, p: (lambda c: f"{c[0]} x {'20' if c[1] == '40' else '40'}'{c[2]}")(_cont(v)) if _cont(v) and _cont(v)[1] in ("20", "40") else None),
    ("container", "defect", "type HC <-> GP", ("container_count",), lambda v, r, p: (lambda c: f"{c[0]} x {c[1]}'{'GP' if c[2].upper() == 'HC' else 'HC'}")(_cont(v)) if _cont(v) and _cont(v)[2].upper() in ("HC", "GP") else None),
    # ---- weights: harmless
    ("weight", "benign", "no thousands separator", ("gross_weight_kg",), lambda v, r, p: str(_wt(v)) if _wt(v) else None),
    ("weight", "benign", "KGS", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(_wt(v), " KGS") if _wt(v) else None),
    ("weight", "benign", "lower-case unit", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(_wt(v), " kg") if _wt(v) else None),
    ("weight", "benign", "trailing .0", ("gross_weight_kg",), lambda v, r, p: f"{_wt(v):,}.0 KG" if _wt(v) else None),
    ("weight", "benign", "written in tonnes", ("gross_weight_kg",), lambda v, r, p: f"{_wt(v) / 1000:.3f} MT" if _wt(v) else None),
    ("weight", "benign", "European thousands dot", ("gross_weight_kg",), lambda v, r, p: f"{_wt(v):,}".replace(",", ".") + " KG" if _wt(v) and _wt(v) >= 1000 else None),
    # ---- weights: real defects
    ("weight", "defect", "+1 kg", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(_wt(v) + 1) if _wt(v) else None),
    ("weight", "defect", "-1 kg", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(_wt(v) - 1) if _wt(v) else None),
    ("weight", "defect", "+10 kg", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(_wt(v) + 10) if _wt(v) else None),
    ("weight", "defect", "+0.1 %", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(round(_wt(v) * 1.001) + (1 if round(_wt(v) * 1.001) == _wt(v) else 0)) if _wt(v) else None),
    ("weight", "defect", "+1 %", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(round(_wt(v) * 1.01)) if _wt(v) else None),
    ("weight", "defect", "-10 %", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(round(_wt(v) * 0.9)) if _wt(v) else None),
    ("weight", "defect", "digits transposed", ("gross_weight_kg",), lambda v, r, p: (lambda s: _fmt_kg(int(s[0] + s[2] + s[1] + s[3:])) if len(s) > 3 and s[1] != s[2] else None)(str(_wt(v))) if _wt(v) else None),
    ("weight", "defect", "tonnes read as kg", ("gross_weight_kg",), lambda v, r, p: f"{_wt(v):,} MT" if _wt(v) else None),
    ("weight", "defect", "a digit lost", ("gross_weight_kg",), lambda v, r, p: _fmt_kg(int(str(_wt(v))[1:])) if _wt(v) and _wt(v) >= 10000 else None),
    # ---- any field: blanked
    ("missing", "missing", "N/A", FIELDS, lambda v, r, p: "N/A"),
    ("missing", "missing", "empty", FIELDS, lambda v, r, p: ""),
    ("missing", "missing", "TBA", FIELDS, lambda v, r, p: "TBA"),
    ("missing", "missing", "underscores", FIELDS, lambda v, r, p: "____"),
]
EXPECT = {"benign": "match", "defect": "mismatch", "missing": "missing", "limit": "match"}


def run(seed=1, results="results.json"):
    """-> {"seed", "cases", "rows": [ {group, kind, name, n, ok, failures[...]} ]}"""
    rng = random.Random(seed)
    pairs = load_pairs(results)
    pool = {"names": sorted({si for f, si, _ in pairs if f in NAMES}),
            "ports": sorted({si for f, si, _ in pairs if f in PORTS})}
    rows = []
    for group, kind, name, fields, fn in MUTATIONS:
        n = ok = 0
        failures = []
        for field, si, bl in pairs:
            if field not in fields:
                continue
            _CTX["si"] = si
            try:
                new = fn(bl, rng, pool)
            except (ValueError, IndexError, TypeError):
                new = None
            if new is None or (kind != "missing" and new == bl):
                continue                                   # the mutation does not apply to this value
            got = verdict(field, si, new)
            n += 1
            if got == EXPECT[kind]:
                ok += 1
            elif len(failures) < 5:
                failures.append({"field": field, "si": si, "bl": new, "got": got})
        rows.append({"group": group, "kind": kind, "name": name, "n": n, "ok": ok, "failures": failures})
    return {"seed": seed, "pairs": len(pairs), "rows": rows}


def summarise(report):
    """Totals per kind: {"benign": (n, ok), ...}"""
    tot = defaultdict(lambda: [0, 0])
    for r in report["rows"]:
        tot[r["kind"]][0] += r["n"]
        tot[r["kind"]][1] += r["ok"]
    return {k: tuple(v) for k, v in tot.items()}


if __name__ == "__main__":
    rep = run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    for r in rep["rows"]:
        flag = "" if r["ok"] == r["n"] else "   <-- FAILS"
        print(f"{r['kind']:8} {r['group']:9} {r['name']:28} {r['ok']:4}/{r['n']:<4}{flag}")
        for f in r["failures"][:2]:
            print(f"           e.g. {f['field']}: SI {f['si']!r} vs BL {f['bl']!r} -> {f['got']}")
    for k, (n, ok) in summarise(rep).items():
        print(f"TOTAL {k}: {ok}/{n}")
