"""Run the whole validation lab and write validation/REPORT.md.

    python -m validation.run                        fuzzers (3 seeds) + saved organiser scores + team labels if present
    python -m validation.run --organiser DIR        also re-score the organisers' datasets from DIR
Team labels: put the CSVs downloaded from the labelling packet in validation/labels/.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from validation import fuzz, fuzz_docs, score_labels

HERE = Path(__file__).parent
SEED = 1
MORE_SEEDS = (2, 3, 4, 5)          # same tests, different random picks: repeated only to look for failures


def repeats(reports):
    """(cases, failures) over the repeat runs; the cases overlap the first run, so they are not added to its counts."""
    n = sum(r["n"] for rep in reports for r in rep["rows"] if r["kind"] != "limit")
    bad = sum(r["n"] - r["ok"] for rep in reports for r in rep["rows"] if r["kind"] != "limit")
    return n, bad


def table(rows, cols=("Change", "Cases", "Handled correctly")):
    out = [f"| {' | '.join(cols)} |", "|" + "---|" * len(cols)]
    for r in rows:
        ok = "**all**" if r["ok"] == r["n"] else f"{r['ok']} of {r['n']}"
        label = f"{r['group']}: {r['name']}" if r.get("group") else r["name"]
        out.append(f"| {label} | {r['n']} | {ok} |")
    return "\n".join(out)


def totals(rows, kind):
    n = sum(r["n"] for r in rows if r["kind"] == kind)
    ok = sum(r["ok"] for r in rows if r["kind"] == kind)
    return n, ok


def main(argv):
    organiser = argv[argv.index("--organiser") + 1] if "--organiser" in argv else None
    saved = HERE / "organiser_scores.json"
    if organiser:
        from validation import organiser as org
        saved.write_text(json.dumps(org.score(organiser), indent=1), encoding="utf-8")
    first_f, first_d = fuzz.run(SEED), fuzz_docs.run(SEED)
    field_rows, doc_rows = first_f["rows"], first_d["rows"]
    docs, pairs = first_d["documents"], first_f["pairs"]
    rf, rd = repeats([fuzz.run(s) for s in MORE_SEEDS]), repeats([fuzz_docs.run(s) for s in MORE_SEEDS])

    L = ["# Validation report", "",
         "How well the checker holds up, measured four ways. Everything here except the team-label study is "
         "reproducible with `python -m validation.run` (seeded, rules-only, no API calls). "
         "We report what was **caught, missed and falsely flagged in each test**. We do not quote a single "
         "\"accuracy\" figure, because none of these samples is a random draw from real traffic.", ""]

    L += ["## 1. Fuzzing the comparison rules", "",
          f"Starting from {pairs} real field pairs that agree in the data, each change below is applied to the "
          f"Bill of Lading value (seed {SEED}; every row is a distinct set of cases). "
          "*Formatting* changes must still match; *meaning* changes must be flagged; blanked values must go to a person.", ""]
    for kind, title in (("benign", "Formatting only: must NOT raise an alarm"), ("defect", "Changes of meaning: must be caught"),
                        ("missing", "Blanked value: must be sent to a person")):
        n, ok = totals(field_rows, kind)
        L += [f"### {title}: {ok} of {n}", "", table([r for r in field_rows if r["kind"] == kind]), ""]
    L += [f"Repeated with seeds {', '.join(map(str, MORE_SEEDS))} (different random picks, overlapping cases): "
          f"{rf[0]} further cases, **{rf[1]} failures**.", ""]
    lim = [r for r in field_rows if r["kind"] == "limit"]
    L += ["### Known limit (by design)", "",
          "The address after ` | ` in a party name is not compared, only the name. Changing or dropping the address "
          f"is therefore not flagged ({lim[0]['ok']} of {lim[0]['n']} and {lim[1]['ok']} of {lim[1]['n']} cases). "
          "This matches how the organisers define a defect (a different party), but a real deployment may want it checked.", ""]

    L += ["## 2. Fuzzing whole documents", "",
          f"Real SI/BL text files ({docs} pairs) are rewritten, then read by the real extractor and comparator. "
          "Only `.txt` attachments are rewritten; PDF, DOCX and XLSX go through the same extractor after text extraction "
          "and are covered by the snapshot tests.", ""]
    for kind, title in (("layout", "Layout changes: the verdict must not change"),
                        ("failsafe", "Wording the extractor does not know: must be escalated, never a silent \"no mismatch\""),
                        ("defect", "A real defect written into the document: found, in the right field, and only that field")):
        n, ok = totals(doc_rows, kind)
        L += [f"### {title}: {ok} of {n}", "", table([r for r in doc_rows if r["kind"] == kind]), ""]
    L += [f"Repeated with seeds {', '.join(map(str, MORE_SEEDS))}: {rd[0]} further cases, **{rd[1]} failures**.", ""]
    esc = sum(r["escalated"] for r in doc_rows if r["kind"] == "failsafe")
    L += [f"With unfamiliar wording the checker could not read the value in {esc} of {totals(doc_rows, 'failsafe')[0]} cases "
          "and said so each time, so a person reviews them. With a Gemini key the AI step can read these; here it is off.", ""]

    L += ["## 3. The organisers' own ground truth", ""]
    if saved.exists():
        sc = json.loads(saved.read_text(encoding="utf-8"))
        L += ["Rules only, scored with the organisers' scorer on their data and on three fresh datasets from their generator. "
              "These datasets are synthetic and this result is saturated, which is why sections 1 and 2 exist.", "",
              "| Dataset | Emails | Kind of email | Defects caught | False alarms (precision) | Field match | Cases sent to review (recall / precision) | Document checks fully right |",
              "|---|---|---|---|---|---|---|---|"]
        for name, s in sc.items():
            L.append(f"| {name} | {s['emails']} | {100 * s['kind_accuracy']:.0f}% | {100 * s['defect_recall']:.0f}% | "
                     f"{100 * s['defect_precision']:.0f}% | {100 * s['field_f1']:.0f}% | "
                     f"{100 * s['review_recall']:.0f}% / {100 * s['review_precision']:.0f}% | {s['end_to_end']} |")
        L.append("")
    else:
        L += ["_Not run in this checkout: it needs the organisers' ground-truth files, which are not in the repository "
              "(`python -m validation.run --organiser DIR`)._", ""]

    L += ["## 4. Team-labelled sample", ""]
    csvs = sorted((HERE / "labels").glob("*.csv"))
    if csvs:
        rep = score_labels.score([str(p) for p in csvs])
        L += ["A stratified sample of 60 emails was labelled by hand from the documents alone, blind to the system "
              "(`validation/label_packet/packet.html`). The sample deliberately over-represents mismatches and cases for review, "
              "so the figures below are agreement on this sample, not rates for the whole inbox.", "", score_labels.markdown(rep), ""]
        if rep["disagreements"]:
            L += ["Disagreements between the team and the system:", ""]
            L += [f"- `{d['email']}`: team {d['team']}, system {d['system']}" for d in rep["disagreements"]]
            L.append("")
    else:
        L += ["_Not done yet: no labels in `validation/labels/`. Send `validation/label_packet/packet.html` to teammates, "
              "put the CSVs they download into `validation/labels/`, and run this again._", ""]

    L += ["## 5. Bugs this found", "",
          "- **Weights 1 kg apart counted as equal** (fuzzer: 0 of 100 caught). The rounding tolerance was applied as "
          "\"at most\" instead of \"less than\", so `131,058 KG` and `131,059 KG` matched. Fixed in `compare.py`; the organisers' "
          "scores did not change, and a regression test now covers it.", "",
          "## 6. What this does not show", "",
          "- The fuzz cases were written by the team that wrote the checker; they are a regression net and a way to find "
          "bugs, not an independent test.",
          "- Section 3 data is synthetic; a clean score there says little about real forwarded threads and messy scans.",
          "- Scanned or unreadable documents are sent to a person by design; the AI reading of scans is a suggestion, not a verdict.",
          "- Only `.txt` documents are rewritten in section 2.",
          "- The keyword rules that sort emails into kinds were written from the wording of this dataset. The fresh datasets "
          "in section 3 come from the same generator, so they share that wording; a real inbox would need the rules widened. "
          "The optional AI fallback for emails the rules cannot place exists for that reason, but it has not been measured here.", ""]
    (HERE / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {HERE / 'REPORT.md'}")
    for kind, rows in (("field", field_rows), ("document", doc_rows)):
        print(kind, {k: totals(rows, k) for k in sorted({r['kind'] for r in rows})})


if __name__ == "__main__":
    main(sys.argv[1:])
