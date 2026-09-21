"""Score the rules-only pipeline against the organisers' own ground truth, with their scorer.

The ground-truth files are NOT part of this repository. Point this at folders that hold the organisers' data
(inbox/, attachments/, ground_truth.json):   python -m validation.run --organiser DIR
Only the resulting numbers are kept (validation/organiser_scores.json).
"""
import json
import os
import sys
from pathlib import Path

DATASETS = {"given data (seed 42)": "data_v2", "fresh data, seed 1": "seed1",
            "fresh data, seed 2": "seed2", "fresh data, seed 3": "seed3"}


def score(root):
    os.environ["USE_LLM"] = "0"                       # rules only, so the numbers are reproducible
    sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
    import pipeline
    import scoring
    out = {}
    for name, folder in DATASETS.items():
        src = Path(root) / folder
        truth = json.loads((src / "ground_truth.json").read_text())
        r = scoring.score_all(truth, json.loads(json.dumps(pipeline.run(str(src)))))
        out[name] = {"emails": r["n_emails"], "kind_accuracy": r["stage1"]["accuracy"],
                     "defect_precision": r["stage3"]["defect_precision"], "defect_recall": r["stage3"]["defect_recall"],
                     "field_f1": r["stage3"]["field_f1"], "review_recall": r["reliability"]["escalation_recall"],
                     "review_precision": r["reliability"]["escalation_precision"],
                     "end_to_end": f"{r['end_to_end']['success']}/{r['end_to_end']['total']}"}
    return out
