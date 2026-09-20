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

### Deploy (Render, free tier)

1. Push this folder to GitHub (`.env` is git-ignored, so your key is not uploaded).
2. On render.com: New -> Web Service -> pick the repo.
3. Build command: `pip install -r requirements.txt`  Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 180`
4. Environment: add `GEMINI_API_KEY` and `GEMINI_MODEL` as secrets.
5. Keep it to ONE worker: results are held in memory.

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
