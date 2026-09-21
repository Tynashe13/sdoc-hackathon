# Shipping Document Verification

Reads a shipping inbox, finds document-check requests, compares the Shipping
Instruction (SI) against the draft Bill of Lading (BL) on seven fields, and
reports mismatches. Anything it cannot decide is sent to a person for review.

## Setup

1. Install Python 3.9+
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

Every answer is cached in `.cache/`, so re-runs cost no API calls.
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
| `classify.py` | Stage 1 - what kind of email is it? |
| `readers.py`  | Turn txt / pdf / docx / xlsx attachments into plain text |
| `extract.py`  | Find the 7 fields, whatever the label wording |
| `compare.py`  | Normalise values and compare SI vs BL |
| `llm.py`      | Optional Gemini helpers (cached, retried, never crash the run) |
| `pipeline.py` | Runs everything, writes `submission.json` |
| `app.py` + `static/index.html` | The web app (API + Apple-Mail-style interface) |
