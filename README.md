# SDOC Check: shipping document verification

Reads a shipping inbox, finds the emails that ask for a document check, compares the Shipping Instruction (SI)
against the draft Bill of Lading (BL) on seven fields, and reports mismatches. Anything it cannot decide goes to
a person, with the evidence in front of them. Built for the Averis x Monash Hackathon 2026.

**Live demo: https://sdoc-hackathon.vercel.app** (works on a phone; no login)

![How one email becomes a verdict](docs/architecture.png)

## Try it in two minutes

Open the live demo and use the search box, or add `#email_004` to the address to open an email directly.

| Email | What it shows |
|---|---|
| `email_001` | A clean check: "No mismatch detected" |
| `email_004` | Two mismatches (consignee, notify party), each with the exact SI and BL line it was read from |
| `email_003` | A request for the draft BL: nothing to compare yet, and it says so instead of passing |
| `email_516` | A blank value: the case goes to review. Fill it in, press *Save & re-check*, then *Undo* |
| `email_501` | Wrong document: the "BL" attachment is really an invoice |
| `email_512`, `513`, `514` | Scanned pages: read by Gemini as a *suggestion*, tagged **AI-assisted**, with a disclaimer |
| `email_519`, `520` | Blank values: Gemini was asked and found nothing, so a grey note says so |

## What was measured

| | |
|---|---|
| Emails in the demo inbox | 520 (220 document checks: 63 clean, 46 mismatch, 20 for review, 91 waiting for the draft BL) |
| Field fuzzer | 1,274 formatting-only changes still match, 1,572 real defects caught, 988 blanked values sent to a person |
| Document fuzzer | 890 layout changes keep their verdict; unfamiliar wording is always escalated (267 of 267); 1,948 injected defects found in the right field |
| Organisers' ground truth | 100% on the given data and three freshly generated datasets (synthetic, so this is saturated: the fuzzers are the harder test) |
| A real bug found by the fuzzers | Weights 1 kg apart counted as equal. Fixed and covered by a test |
| Automated tests | 71 |

Details, the method and the limits: [`validation/REPORT.md`](validation/REPORT.md). The team-labelled sample
(60 emails labelled by hand, blind to the system) is built but not yet labelled, and the report says so.

## How it decides

- **Rules decide.** Keyword rules sort the emails, label patterns find the seven fields, and fixed normalisation
  rules compare them. The AI is never asked whether two values match.
- **Every value shows its evidence:** the exact line of the source document, with the file name and line number.
- **Anything uncertain goes to a person:** a blank value, an unreadable scan, the wrong document, wording the
  extractor does not know. It never guesses and never reports a silent pass.
- **Gemini is optional and guarded.** It can classify an email the rules cannot place, fill a missing field only if
  it quotes a line that really is in the document, and read a scanned page as a suggestion. Anything it touches is
  tagged, carries a disclaimer, and needs a person to confirm it.
- **The AI results in this repo come from real calls.** For the three scanned emails (512 to 514) the values in
  `results.json` were produced by Gemini reading the scanned pages, and were then checked against the pages by hand:
  21 of 21 values matched. Nothing is typed in.

## Known limits

- All data is synthetic, and there is no login: reviewer decisions are stored per email, not per user.
- The keyword rules that classify emails were written from this dataset's wording; a real inbox would need them widened.
- On scanned emails only the SI page is read by Gemini; the BL side is left for the reviewer.
- Only cases that need review can be edited in the app.

## Setup

1. Install Python 3.12 or newer
2. In this folder run: `pip install -r requirements.txt`
3. Put the inbox data in `data/` (it must contain `inbox/` and `attachments/`)

## Run

    python pipeline.py data

This writes `submission.json` with one result per email.

## AI layer (Gemini)

Copy `.env.example` to `.env` and add your `GEMINI_API_KEY`. With no key the program still
runs, rules-only. The AI is used only where rules are not enough:

| Situation | What the AI does | Safety net |
|---|---|---|
| Email the keyword rules cannot place | Classifies it from the body | Falls back to GENERAL if the API fails |
| A field label the rules do not recognise | Finds the value in the document | Accepted only if the quoted line really appears in the document |
| Scanned / image-only PDF | Reads the page image | Result is a *suggestion*: the case still goes to a human with the page and the AI reading |

Every email the AI contributed to is tagged **AI-assisted** (in the list, in the sidebar and on the email) and carries a
disclaimer; a value the AI found is marked `AI` in the comparison table. When the AI was asked but found nothing, a
grey note says so, and nothing is tagged. If Gemini is busy or out of quota, that is recorded as a failure, never as
"found nothing".

Every answer is cached in `.cache/`, so re-runs cost no API calls. To rebuild `results.json` with Gemini (about five
requests, capped): `python precompute.py --with-ai`. It refuses to write the file if any call failed.
Test the wiring without any API key: `python -m unittest discover -s tests -t . -v`

## Web app (Apple-Mail-style inbox)

    python app.py          # then open http://localhost:5000

Every email appears as a message. Document-check emails show the seven fields side by side
(SI vs draft BL) with mismatches highlighted. Cases the system cannot decide land in
**Needs review** with the source documents, the reason, and editable values; a person
confirms or corrects them, and the report updates. **Retry** re-runs one email, and
**Export discrepancy report** downloads a CSV.

### Deploy (Vercel + Supabase)

The app runs on Vercel and keeps reviewer decisions in Supabase. Pushing to `main` deploys it; other branches
get a private preview.

1. In Vercel, import the GitHub repo (it detects Flask from `vercel.json`).
2. Add Supabase to the project (Storage tab). This sets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
3. In Supabase, open the SQL Editor and run `supabase/schema.sql` once.
4. Optional: add `GEMINI_API_KEY` (and `GEMINI_MODEL`) in the project's environment variables. Without a
   key the app runs rules-only. Environment changes need a redeploy.
5. Check `/healthz` on the live URL: it should say `"ready":true` and `"reviews":"supabase"`.

Run it on your own machine with `pip install -r requirements.txt` and `python app.py`. Without the Supabase
variables, reviewer decisions are kept in a local `reviews.json` (git-ignored).

**Evidence for every value.** Each value in the comparison table (and in the review form) is shown with
the exact line of the source document it was read from, plus the file name and line number, so a person
can check it at a glance. The tests confirm that every quoted line is verbatim line N of the named file
and contains the displayed value; a value the AI finds is accepted only if it quotes a real line.

**Fast start-up.** `results.json` holds the checked results for every email, so the app is ready
the moment it starts instead of re-reading every attachment (slow on a serverless host). It is
tied to the data and the checking code by a fingerprint: if either changes, the app ignores the
file, says so in its log, and computes live. After changing the data or the rules, run
`python precompute.py` and commit the new `results.json` (`python precompute.py --check` tells
you whether it is up to date; the test suite checks it too). Only do that on a checkout whose
data files are intact: on Windows, Git can rewrite the line endings inside small PDFs and break
them, which is why `.gitattributes` marks attachments as binary.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the diagrams, the design decisions and the known limits.

## Validation lab

`python -m validation.run` writes [`validation/REPORT.md`](validation/REPORT.md) (seeded, rules only, no API calls):

- **Field fuzzer** (`validation/fuzz.py`): real value pairs that agree are rewritten. Formatting changes must
  still match, changes of meaning must be flagged, blanked values must go to a person.
- **Document fuzzer** (`validation/fuzz_docs.py`): real SI/BL text files are re-laid-out, given wording the
  extractor does not know (it must escalate, never report a clean pass), or given a real defect (it must be
  found in the right field).
- **Organisers' ground truth** (`python -m validation.run --organiser DIR`): the organisers' scorer on their
  data and on three fresh datasets. Their files are not in this repository; only the scores are saved.
- **Team-labelled sample**: `validation/label_packet/packet.html` holds 60 emails with no system answers.
  Teammates label them, drop the CSVs into `validation/labels/`, and the report compares them with the system.

The tests in `tests/test_validation.py` run the same fuzzers, so a change to the checking rules that breaks
one fails the suite.

## Score (optional)

    python tools/score_cli.py submission.json --ground-truth path/to/ground_truth.json

## Project layout

| File | Job |
|---|---|
| `classify.py` | Stage 1: what kind of email is it? |
| `readers.py`  | Turn txt / pdf / docx / xlsx attachments into plain text |
| `extract.py`  | Find the 7 fields, whatever the label wording, and keep the source line of each |
| `compare.py`  | Normalise values and compare SI vs BL |
| `llm.py`      | Optional Gemini helpers (cached, retried, capped, never crash the run) |
| `pipeline.py` | Runs everything and produces one result per email |
| `app.py` + `static/index.html` | The web app (API + Apple-Mail-style interface) |
| `store.py`    | Where reviewer decisions live: Supabase, or a local file |
| `snapshot.py`, `precompute.py`, `results.json` | Precomputed results with a fingerprint, so start-up is instant |
| `validation/` | Fuzzers, the labelling packet and the validation report |
| `docs/` | Architecture diagrams and the architecture document |
| `supabase/schema.sql` | The one table the app needs |
| `vercel.json` | Vercel settings |
| `tests/` | 71 automated tests |
