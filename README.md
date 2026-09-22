# SDOC Check: shipping document verification

Reads a shipping inbox, finds the emails that ask for a document check, compares the Shipping Instruction (SI)
against the draft Bill of Lading (BL) on seven fields, and reports mismatches. Anything it cannot decide goes to
a person, with the evidence in front of them. Built for the Averis x Monash Hackathon 2026.

**Live demo: https://sdoc-hackathon.vercel.app** (works on a phone; no login)

**One-page overview (PDF):** [docs/SDOC-Check-Overview.pdf](docs/SDOC-Check-Overview.pdf)

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
| Any quoted line | Click it, or an attachment, to open the **Test lab**: the whole document with the line each value was read from marked green, red or amber |


## What was measured

| | |
|---|---|
| Emails in the demo inbox | 520 (220 document checks: 63 clean, 46 mismatch, 20 for review, 91 waiting for the draft BL) |
| Field fuzzer | 1,274 formatting-only changes still match, 1,572 real defects caught, 988 blanked values sent to a person |
| Document fuzzer | 890 layout changes keep their verdict; unfamiliar wording is always escalated (267 of 267); 1,948 injected defects found in the right field |
| Organisers' ground truth | 100% on the given data and three freshly generated datasets (synthetic, so this is saturated: the fuzzers are the harder test) |
| A real bug found by the fuzzers | Weights 1 kg apart counted as equal. Fixed and covered by a test |
| Automated tests | 120 |

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
- **Gemini writes the plain-language reason** for every mismatch and every case that needs review
  (`python explain.py`, about three requests; all 66 cases in the demo inbox have one in `explanations.json`).
  It is given only the compared values, is never asked to decide, and its sentence is kept only if it mentions the
  values it explains. It is tagged `AI`, appears in the app and in the CSV report, and disappears if a person
  corrects the case. If the main model is busy or out of quota, the step falls back to another Gemini model.
  The sidebar's **AI-assisted** filter lists these 66 emails: every mismatch and review case (46 + 20), which includes
  the three scans Gemini read. Gemini never decides any of them.
- **The Test lab shows the proof in place.** Click a quoted line or an attachment and the whole document opens
  beside the comparison, with every line a value was read from marked. Nothing is decided there: it uses the same
  evidence as the quotes, and the tests check each marked line is exactly the quoted line.
- **Resilience.** Live AI calls are optional: the results and explanations are built offline and saved, so the site
  makes no Gemini calls while people browse it. If Gemini is busy or out of quota, Retry keeps the saved result.
  Adding a second AI provider (with the scan readings re-checked against the pages) is on the roadmap.
- **Hardening.** One bad email becomes a "needs review" case instead of stopping the app; a corrupt AI cache file
  is ignored; a single rejected request no longer switches AI off for good; if the reviews database is unreachable
  the inbox still loads and saves fail with a clear message; posted data must be JSON and is size-capped; the CSV
  export neutralises spreadsheet formulas; every error a person can see is a plain sentence. Each has a test.
- **The AI results in this repo come from real calls.** For the three scanned emails (512 to 514) the values in
  `results.json` were produced by Gemini reading the scanned pages, and were then checked against the pages by hand:
  21 of 21 values matched. Nothing is typed in.

## Known limits

- All data is synthetic, and there is no login: reviewer decisions are stored per email, not per user.
- The keyword rules that classify emails were written from this dataset's wording; a real inbox would need them widened.
- On scanned emails only the SI page is read by Gemini; the BL side is left for the reviewer.
- Only cases that need review can be edited in the app.

## Notes for judges

- The demo database is shared: anyone who saves, resolves or undoes a case changes what the next person sees, so the
  counts may differ from the video. The baseline is 63 no mismatch, 46 mismatches, 20 needing review, 91 awaiting the draft BL.
- **Retry** is a demo action. The precomputed results are the reference; Retry re-checks one email on one server.
- Gemini is optional. Everything works without it, and it never decides a verdict.
- There is no login on purpose, so anyone can try it. Authentication is on the roadmap.

## Setup


 Running  it on your own computer

**You need:** Python 3.9 or newer 

**1. Download the project**

```
git clone https://github.com/Tynashe13/sdoc-hackathon.git
cd sdoc-hackathon
```

**2. Install the libraries**

```
pip install -r requirements.txt
```

If `pip` is not recognized, use `python -m pip install -r requirements.txt`. On Mac or Linux, use `python3` and `pip3` in place of `python` and `pip`.

**3. Add your Gemini API key**

The AI reads scanned PDFs, finds fields the rules miss, and classifies unusual emails, so the app needs a key to use it.

a. Get a free key at https://aistudio.google.com ("Get API key").

b. Copy the example settings file to a new file named `.env`:
- Windows: `copy .env.example .env`
- Mac or Linux: `cp .env.example .env`

c. Open `.env` and fill in these two lines, with no spaces around `=` and no quote marks:

```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.6-flash
```

d. Check that the key works:

```
python check_gemini.py
```

It should print `SUCCESS`. If it says the model is not found, replace `GEMINI_MODEL` with a current Flash model name listed in AI Studio, and run the check again. To see which Flash models your key can use right now, run `python check_gemini.py --models`.

**4. Start the app**

```
python app.py
```

Wait for the line `Running on http://127.0.0.1:5000`. Leave this terminal open.

**5. Open the app**

Go to **http://localhost:5000** in a browser. You will see a "Reading the inbox..." progress bar for about 10 seconds, then the mail interface with 520 emails. Check the bottom-left of the sidebar: it should say **Gemini AI connected**.

### What to try first

1. **See the AI at work.** Click **Needs review**, type `email_512` in the search box, and open it. This one is a scanned PDF with no text. You will see the scanned page, and Gemini's reading of it pre-filled in the boxes and highlighted. A person checks each value, then clicks **Save & re-check**.
2. **See a comparison.** Click **Mismatches** and open any message. The seven fields appear with the SI and BL values side by side, with the mismatched rows highlighted.
3. **Export the results.** Click **Export discrepancy report** in the sidebar to download a CSV.

### Troubleshooting

| Problem | Fix |
|---|---|
| `No module named 'flask'` (or another module) | Step 2 did not finish. Run the install command again. |
| Sidebar says "AI off" | The file must be named exactly `.env` (not `.env.txt`), sit in the same folder as `app.py`, and contain your key. Save it, then restart the app. |
| A 404 error mentioning the model | Set `GEMINI_MODEL` in `.env` to a current Flash model name from AI Studio. |
| `Address already in use` | Something else is using port 5000. Mac or Linux: `PORT=5001 python app.py`. Windows PowerShell: `$env:PORT=5001; python app.py`. Then open http://localhost:5001. |
| The progress bar stays up a long time | Wait up to a minute on the first run; it is reading all 520 emails. |

### Run the tests and scoring tool

```
python -m unittest discover -s tests -t . -v
python pipeline.py data
python tools/score_cli.py submission.json --ground-truth path/to/ground_truth.json
```

The tests use a simulated AI, so they need no key. The scoring tool needs the organizers' `ground_truth.json`, which is not included in this repository.

### Rebuild the saved AI results (optional)

```
python precompute.py --with-ai
python explain.py
```

The first rebuilds `results.json` (Gemini reads the three scanned emails; about five requests, capped) and refuses to write the file if any call failed. The second writes `explanations.json`, the plain-language reasons (about three requests, with a fallback to another model when the main one is busy). Answers are cached in `.cache/`, so re-runs cost no API calls.


## Deploy (Vercel + Supabase)

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

## Technical Architecture

Rules decide. AI only helps where rules cannot, and a person settles anything uncertain.

Inbox (520 emails, TXT/PDF/DOCX/XLSX) → **Classify** (keyword rules; Gemini suggests a kind only when the rules are
unsure) → **Read** (attachments become text; a scan or a broken file is never guessed at) → **Extract** (label patterns
find the 7 fields under any wording, and each value keeps the exact source line) → **Compare** (names, ports,
containers and weights are normalised, then compared field by field — deterministic, the AI never judges a match) →
**Verdict**: OK / Mismatch / Needs review / Awaiting draft BL. Anything the rules cannot decide goes to a **review
queue**: a person sees the reason and both documents, confirms or corrects the values, and the comparison is
recomputed and saved (Undo any time).

The web app runs on **Vercel** as one Python function, deployed from GitHub (push to `main` deploys; other branches
get a private preview). **Supabase** stores reviewer decisions in one table with row-level security on. **Gemini** is
used in four narrow ways, and we are honest about it: every one of the 520 emails is classified by rules; Gemini reads
three scanned emails as suggestions a human confirms (we checked its 21 values by hand against the pages); it fills a
missing value only when it quotes the exact line; and it writes a plain-language reason for all 66 mismatch and review
cases from the compared values only. The verdict always comes from fixed rules. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the diagrams and the full design decisions.

## Implementation Details

Python 3.12 with a Flask API and a single static web page (`static/index.html`). Each value keeps its source line,
and tests check every quote is verbatim against the named file and line number. Results for all 520 emails are
precomputed into `results.json` with a SHA-256 fingerprint of the data and the checking code, so the app is ready in
about a second; if the fingerprint does not match, it recomputes instead of showing stale results. The server is
stateless (serverless instances are short-lived), so reviewer decisions live in Supabase and are read on every
request; running locally without Supabase, a JSON file does the same job. Many failure cases are hardened, each with
its own test: one bad email becomes a review case instead of stopping the app, a corrupt AI cache file is ignored, a
single rejected AI request no longer switches AI off for good, a database outage leaves the inbox readable and makes
saves fail with a clear message, posted data must be JSON and is size-capped, and the CSV export neutralises
spreadsheet formulas.

## Challenges Faced

- **Gemini overload (503) and quota (429).** Back-off retries, a request cap, a cool-down and a fallback to another
  Gemini model. Results and explanations are built offline and saved, so the live site makes no Gemini calls while
  people browse it.
- **Windows text-encoding bug.** Text had to be read and written as UTF-8 everywhere. Git can also rewrite line
  endings inside small PDFs on Windows, so attachments are marked binary in `.gitattributes`.
- **Deploying to Vercel from a repo.** A serverless host has no persistent disk, so reviewer decisions moved to
  Supabase and results are precomputed for a fast start.
- **Keeping the fonts identical to the original design.** A test locks the original font stack and the one Inter
  link; nothing else may be added.
- **Grounding the AI output.** A value found by Gemini counts only if it quotes a real line of the document; a
  plain-language reason is kept only if it mentions the values it explains. Scan readings were checked by hand: 21 of
  21 values matched the pages.

## Future Roadmap

- **In-app document viewer, next step.** The Test lab already opens a document with the differing line marked; the
  next step is two documents side by side, with editing right where the line is marked.
- **Provider resilience.** A second AI provider, with every scan reading re-validated against the pages, because our
  AI evidence so far was gathered on Gemini only.
- **Authentication and reviewer identity.** Sign-in, with every decision recorded against a named reviewer.
- **Real user testing.** Try it with real shipping/forwarding staff and report what they find.
- **Real-time monitoring.** Watch errors, AI failures and usage as they happen.
- **Widen the sorting rules.** Extend the keyword rules beyond this dataset's wording for a real inbox.

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

## Project layout

| File | Job |
|---|---|
| `classify.py` | Stage 1: what kind of email is it? |
| `readers.py`  | Turn txt / pdf / docx / xlsx attachments into plain text |
| `extract.py`  | Find the 7 fields, whatever the label wording, and keep the source line of each |
| `compare.py`  | Normalise values and compare SI vs BL |
| `llm.py`      | Optional Gemini helpers (cached, retried, capped, with a fallback model; never crash the run) |
| `explain.py`  | Gemini-written plain-language reasons for mismatches and review cases (checked, saved, never deciding) |
| `pipeline.py` | Runs everything and produces one result per email |
| `app.py` + `static/index.html` | The web app (API + Apple-Mail-style interface) |
| `store.py`    | Where reviewer decisions live: Supabase, or a local file |
| `snapshot.py`, `precompute.py`, `results.json` | Precomputed results with a fingerprint, so start-up is instant |
| `validation/` | Fuzzers, the labelling packet and the validation report |
| `docs/` | Architecture diagrams and the architecture document |
| `supabase/schema.sql` | The one table the app needs |
| `vercel.json` | Vercel settings |
| `tests/` | 120 automated tests |
