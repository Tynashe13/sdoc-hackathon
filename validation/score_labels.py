"""Compare the system with what teammates labelled by hand (from validation.label_packet).

    python -m validation.score_labels labels_a.csv [labels_b.csv ...] [--results results.json]

With two or more labellers it also reports how well the humans agree with each other (Cohen's kappa), and
lists every email where they disagree so the team can settle it.  The consensus label is the majority
answer; where there is no majority the email is listed as unresolved and left out of the scores.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path


def system_view(res):
    """The system's answer in the same vocabulary as the labelling form."""
    if res["category"] != "BL_COMPARISON":
        return {"category": res["category"], "verdict": "", "fields": "", "reason": ""}
    if res.get("awaiting_documents"):
        verdict = "NOTHING_TO_COMPARE"
    else:
        verdict = res["status"]
    return {"category": "BL_COMPARISON", "verdict": verdict,
            "fields": ";".join(sorted(res.get("defect_fields") or [])),
            "reason": res.get("review_reason") or ""}


def read_labels(paths):
    """{labeller: {email_id: {category, verdict, fields, reason}}}"""
    out = {}
    for p in paths:
        with open(p, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if not row["category"]:
                    continue                              # skipped item
                fields = ";".join(sorted(x for x in row["fields"].split(";") if x))
                out.setdefault(row["labeller"], {})[row["email_id"]] = {
                    "category": row["category"], "verdict": row["verdict"], "fields": fields, "reason": row["reason"]}
    return out


def kappa(a, b):
    """Cohen's kappa between two label lists of equal length (1 = perfect, 0 = chance)."""
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def consensus(labels):
    """Majority answer per email and field of the label; None where the humans split evenly."""
    ids = sorted({e for per in labels.values() for e in per})
    out, unresolved = {}, []
    for eid in ids:
        rows = [per[eid] for per in labels.values() if eid in per]
        merged = {}
        for key in ("category", "verdict", "fields", "reason"):
            votes = Counter(r[key] for r in rows).most_common()
            if len(votes) > 1 and votes[0][1] == votes[1][1]:
                merged[key] = None
            else:
                merged[key] = votes[0][0]
        if any(v is None for v in merged.values()):
            unresolved.append(eid)
        out[eid] = merged
    return out, unresolved


def score(paths, results="results.json"):
    system = {e: system_view(r) for e, r in json.loads(Path(results).read_text())["results"].items()}
    labels = read_labels(paths)
    truth, unresolved = consensus(labels)
    rep = {"labellers": {k: len(v) for k, v in labels.items()}, "emails": len(truth), "unresolved": unresolved}

    def rate(pairs):
        n = len(pairs)
        return {"n": n, "agree": sum(a == b for a, b in pairs), "rate": (sum(a == b for a, b in pairs) / n) if n else None}

    usable = {e: t for e, t in truth.items() if e not in unresolved}
    rep["category"] = rate([(t["category"], system[e]["category"]) for e, t in usable.items()])
    checks = {e: t for e, t in usable.items() if t["category"] == "BL_COMPARISON"}
    rep["verdict"] = rate([(t["verdict"], system[e]["verdict"]) for e, t in checks.items()])
    rep["fields"] = rate([(t["fields"], system[e]["fields"]) for e, t in checks.items() if t["verdict"] == "MISMATCH"])
    rep["reason"] = rate([(t["reason"], system[e]["reason"]) for e, t in checks.items() if t["verdict"] == "NEEDS_REVIEW"])
    conf = Counter((t["verdict"], system[e]["verdict"]) for e, t in checks.items())
    rep["verdict_confusion"] = {f"{h} -> {s}": n for (h, s), n in sorted(conf.items())}
    # defects: the humans' MISMATCH against the system's MISMATCH
    tp = sum(t["verdict"] == "MISMATCH" and system[e]["verdict"] == "MISMATCH" for e, t in checks.items())
    fn = sum(t["verdict"] == "MISMATCH" and system[e]["verdict"] != "MISMATCH" for e, t in checks.items())
    fp = sum(t["verdict"] != "MISMATCH" and system[e]["verdict"] == "MISMATCH" for e, t in checks.items())
    rep["defects"] = {"caught": tp, "missed": fn, "false_alarms": fp}
    rep["disagreements"] = [{"email": e, "team": {k: v for k, v in t.items()}, "system": system[e]}
                            for e, t in usable.items()
                            if any(t[k] != system[e][k] for k in ("category", "verdict", "fields", "reason"))
                            and (t["category"] == "BL_COMPARISON" or t["category"] != system[e]["category"])]
    names = sorted(labels)
    if len(names) >= 2:
        pairs = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                shared = sorted(set(labels[a]) & set(labels[b]))
                pairs.append({"between": f"{a} & {b}", "n": len(shared),
                              "category_kappa": kappa([labels[a][e]["category"] for e in shared], [labels[b][e]["category"] for e in shared]),
                              "verdict_kappa": kappa([labels[a][e]["verdict"] for e in shared], [labels[b][e]["verdict"] for e in shared])})
        rep["human_agreement"] = pairs
        rep["human_disagreements"] = [e for e in truth if any(len({per[e][k] for per in labels.values() if e in per}) > 1
                                                             for k in ("category", "verdict", "fields", "reason"))]
    return rep


def markdown(rep):
    pct = lambda r: "n/a" if r["rate"] is None else f"{r['agree']}/{r['n']} ({100 * r['rate']:.0f}%)"
    out = [f"Labelled by {', '.join(f'{k} ({n})' for k, n in rep['labellers'].items())}; {rep['emails']} emails, "
           f"{len(rep['unresolved'])} unresolved (no majority).", "",
           "| What | System agrees with the team |", "|---|---|",
           f"| Kind of email | {pct(rep['category'])} |", f"| Outcome of document checks | {pct(rep['verdict'])} |",
           f"| Which fields differ (mismatches) | {pct(rep['fields'])} |", f"| Why it needs review | {pct(rep['reason'])} |", "",
           f"Defects: {rep['defects']['caught']} caught, {rep['defects']['missed']} missed, "
           f"{rep['defects']['false_alarms']} false alarms."]
    if "human_agreement" in rep:
        out += ["", "| Between labellers | Emails | Kappa (kind) | Kappa (outcome) |", "|---|---|---|---|"]
        f = lambda k: "n/a" if k is None else f"{k:.2f}"
        out += [f"| {p['between']} | {p['n']} | {f(p['category_kappa'])} | {f(p['verdict_kappa'])} |" for p in rep["human_agreement"]]
    return "\n".join(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    r = score(args)
    print(markdown(r))
    for d in r["disagreements"]:
        print("DISAGREE", d["email"], "team:", d["team"], "system:", d["system"])
    for e in r.get("human_disagreements", []):
        print("LABELLERS SPLIT on", e)
