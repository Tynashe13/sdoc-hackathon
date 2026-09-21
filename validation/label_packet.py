"""Blinded labelling packet: a team-labelled sample to compare the system against.

    python -m validation.label_packet [n] [seed]     -> validation/label_packet/packet.html

The packet holds n emails (default 60) with their attachments and NO system verdicts. A teammate reads each one,
picks the category and, for document checks, the verdict and the differing fields, then downloads a CSV.
Score the CSVs with:  python -m validation.score_labels labels_a.csv labels_b.csv ...

The sample is stratified so rare outcomes (mismatches, cases for review) are represented; it is not a random
sample, so the rates it gives are not estimates for the whole inbox.
"""
import base64
import html
import json
import random
import sys
from pathlib import Path

from extract import FIELDS
from loader import Inbox
from readers import NoTextError, ReadError, pdf_page_pngs, read_attachment

OUT = Path(__file__).parent / "label_packet"
CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
VERDICTS = ["OK", "MISMATCH", "NEEDS_REVIEW", "NOTHING_TO_COMPARE"]
REASONS = ["wrong_doc_type", "missing_attachment", "unreadable", "missing_value"]
FIELD_LABEL = {"shipper": "Shipper", "consignee": "Consignee", "notify_party": "Notify party",
               "port_of_loading": "Port of loading", "port_of_discharge": "Port of discharge",
               "container_count": "Container count", "gross_weight_kg": "Gross weight"}


def pick(results, n, seed):
    """Stratified: about a third plain OK checks, a quarter mismatches, a sixth cases for review,
    a few 'send the draft' requests, and the rest other kinds of mail."""
    rng = random.Random(seed)
    buckets = {"ok": [], "mismatch": [], "review": [], "awaiting": [], "other": []}
    for eid, r in sorted(results.items()):
        if r["category"] != "BL_COMPARISON":
            buckets["other"].append(eid)
        elif r.get("awaiting_documents"):
            buckets["awaiting"].append(eid)
        elif r["status"] == "NEEDS_REVIEW":
            buckets["review"].append((r["review_reason"], eid))
        elif r["status"] == "MISMATCH":
            buckets["mismatch"].append(eid)
        else:
            buckets["ok"].append(eid)
    take = {"ok": round(n * .30), "mismatch": round(n * .25), "review": round(n * .17),
            "awaiting": round(n * .08)}
    take["other"] = n - sum(take.values())
    chosen = []
    for name, k in take.items():
        pool = buckets[name]
        if name == "review":                          # spread over the four reasons
            by = {}
            for reason, eid in pool:
                by.setdefault(reason, []).append(eid)
            ids = []
            for i in range(k):
                grp = by[sorted(by)[i % len(by)]]
                ids.append(grp.pop(rng.randrange(len(grp))))
            chosen += ids
        else:
            chosen += rng.sample(pool, min(k, len(pool)))
    rng.shuffle(chosen)                               # so the order gives nothing away
    return chosen


def attachment_html(inbox, path):
    name = path.rsplit("/", 1)[-1]
    data = inbox.read_bytes(path)
    try:
        return f"<details open><summary>{html.escape(name)}</summary><pre>{html.escape(read_attachment(name, data))}</pre></details>"
    except NoTextError:
        try:
            png = base64.b64encode(pdf_page_pngs(data, max_pages=1, resolution=150)[0]).decode()
            return f"<details open><summary>{html.escape(name)} (scanned page)</summary><img alt='scan' src='data:image/png;base64,{png}'></details>"
        except Exception:
            return f"<details open><summary>{html.escape(name)}</summary><p class=bad>scanned image that cannot be shown here</p></details>"
    except ReadError as exc:
        return f"<details open><summary>{html.escape(name)}</summary><p class=bad>the file will not open: {html.escape(str(exc))}</p></details>"


def item_html(i, inbox, eid):
    e = inbox.get(eid)
    opts = lambda name, values: "".join(f"<label><input type=radio name='{name}-{i}' value='{v}'> {v}</label>" for v in values)
    fields = "".join(f"<label><input type=checkbox name='fields-{i}' value='{f}'> {FIELD_LABEL[f]}</label>" for f in FIELDS)
    return f"""<section class=item data-id='{eid}' id='i{i}'>
<h2>{i + 1}. <small>{eid}</small></h2>
<div class=mail><b>From:</b> {html.escape(e['from'])}<br><b>Subject:</b> {html.escape(e['subject'])}<pre>{html.escape(e['body'])}</pre></div>
<div class=docs>{''.join(attachment_html(inbox, p) for p in e['attachments']) or '<p class=none>No attachments.</p>'}</div>
<div class=q><b>What kind of email is this?</b> {opts('cat', CATEGORIES)}</div>
<div class=q><b>If it asks to check an SI against a draft BL, what is the outcome?</b> {opts('verdict', VERDICTS)}
<div class=hint>OK = every field agrees. MISMATCH = at least one field differs. NEEDS_REVIEW = a person must look (wrong or missing attachment, unreadable scan, a blank value).
NOTHING_TO_COMPARE = they only asked us to send the draft BL. Leave blank for other kinds of email.</div></div>
<div class=q><b>Which fields differ?</b> (MISMATCH only) {fields}</div>
<div class=q><b>Why does it need review?</b> (NEEDS_REVIEW only) {opts('reason', REASONS)}</div>
</section>"""


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Labelling packet</title>
<link rel=preconnect href='https://fonts.googleapis.com'><link rel=preconnect href='https://fonts.gstatic.com' crossorigin>
<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' rel=stylesheet>
<style>body{font:15px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",Inter,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:900px;margin:0 auto;padding:16px;color:#1c1c1e}
.item{border:1px solid #d1d1d6;border-radius:12px;padding:14px;margin:16px 0}h2 small{color:#8e8e93;font-weight:400}
pre{white-space:pre-wrap;background:#f2f2f7;padding:8px;border-radius:8px;font-size:13px;overflow-wrap:anywhere}
details{margin:6px 0}summary{cursor:pointer;font-weight:600}img{max-width:100%;border:1px solid #d1d1d6}
.q{margin:10px 0}.q label{display:inline-block;margin:2px 12px 2px 0}.hint{font-size:12.5px;color:#636366}.bad{color:#c62828}
#bar{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #d1d1d6;z-index:2}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid #0a84ff;background:#0a84ff;color:#fff}</style>
<div id=bar>Your name: <input id=who placeholder='e.g. Don'> &nbsp; <span id=count>0</span> of __N__ answered &nbsp;
<button onclick='save()'>Download my answers</button></div>
<h1>Labelling packet</h1>
<p>Read each email and its attachments, then answer from the documents alone. Do not look at the app or its results
while you label. Work on your own, then download your CSV and send it back.</p>
__ITEMS__
<script>
const items=[...document.querySelectorAll('.item')];
const val=(s,n)=>{const e=s.querySelector(`input[name^="${n}-"]:checked`);return e?e.value:''};
function rows(){return items.map(s=>({id:s.dataset.id,cat:val(s,'cat'),verdict:val(s,'verdict'),
 fields:[...s.querySelectorAll('input[name^="fields-"]:checked')].map(x=>x.value).join(';'),reason:val(s,'reason')}))}
document.addEventListener('change',()=>{document.getElementById('count').textContent=rows().filter(r=>r.cat).length});
function save(){const who=document.getElementById('who').value.trim()||'anonymous';
 const csv=['labeller,email_id,category,verdict,fields,reason',...rows().map(r=>[who,r.id,r.cat,r.verdict,r.fields,r.reason].join(','))].join('\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='labels_'+who.toLowerCase().replace(/\\W+/g,'_')+'.csv';a.click()}
</script>"""


def build(n=60, seed=7, results="results.json", data="data"):
    res = json.loads(Path(results).read_text(encoding="utf-8"))["results"]
    inbox = Inbox(data)
    ids = pick(res, n, seed)
    OUT.mkdir(exist_ok=True)
    (OUT / "packet.html").write_text(PAGE.replace("__N__", str(len(ids)))
                                     .replace("__ITEMS__", "\n".join(item_html(i, inbox, eid) for i, eid in enumerate(ids))),
                                     encoding="utf-8")
    (OUT / "sample_ids.json").write_text(json.dumps(ids), encoding="utf-8")
    return ids


if __name__ == "__main__":
    ids = build(int(sys.argv[1]) if len(sys.argv) > 1 else 60, int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    print(f"wrote {OUT / 'packet.html'} with {len(ids)} emails")
