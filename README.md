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

It should print `SUCCESS`. If it says the model is not found, replace `GEMINI_MODEL` with a current Flash model name listed in AI Studio, and run the check again.

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
