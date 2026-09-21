# Validation report

How well the checker holds up, measured four ways. Everything here except the team-label study is reproducible with `python -m validation.run` (seeded, rules-only, no API calls). We report what was **caught, missed and falsely flagged in each test**. We do not quote a single "accuracy" figure, because none of these samples is a random draw from real traffic.

## 1. Fuzzing the comparison rules

Starting from 247 real field pairs that agree in the data, each change below is applied to the Bill of Lading value (seed 1; every row is a distinct set of cases). *Formatting* changes must still match; *meaning* changes must be flagged; blanked values must go to a person.

### Formatting only: must NOT raise an alarm: 1274 of 1274

| Change | Cases | Handled correctly |
|---|---|---|
| name: lower case | 67 | **all** |
| name: title case | 67 | **all** |
| name: extra spaces | 67 | **all** |
| name: punctuation removed | 20 | **all** |
| name: legal form written out | 29 | **all** |
| name: legal form abbreviated | 9 | **all** |
| name: address appended | 67 | **all** |
| name: accented letters | 60 | **all** |
| port: lower case | 53 | **all** |
| port: UN/LOCODE dropped | 31 | **all** |
| port: comma removed | 51 | **all** |
| port: extra spaces | 52 | **all** |
| container: no spaces, capital X | 27 | **all** |
| container: foot mark dropped | 27 | **all** |
| container: space before type | 27 | **all** |
| container: lower case | 27 | **all** |
| weight: no thousands separator | 93 | **all** |
| weight: KGS | 100 | **all** |
| weight: lower-case unit | 100 | **all** |
| weight: trailing .0 | 100 | **all** |
| weight: written in tonnes | 100 | **all** |
| weight: European thousands dot | 100 | **all** |

### Changes of meaning: must be caught: 1572 of 1572

| Change | Cases | Handled correctly |
|---|---|---|
| name: different company | 67 | **all** |
| name: one letter changed | 64 | **all** |
| name: one letter dropped | 64 | **all** |
| name: two letters swapped | 62 | **all** |
| name: word added | 67 | **all** |
| name: word dropped | 56 | **all** |
| name: legal form swapped | 15 | **all** |
| name: digit changed | 4 | **all** |
| port: different port | 53 | **all** |
| port: one letter changed | 53 | **all** |
| port: same name, other UN/LOCODE | 30 | **all** |
| port: other country | 51 | **all** |
| container: count + 1 | 27 | **all** |
| container: count - 1 | 24 | **all** |
| container: size 40 <-> 20 | 27 | **all** |
| container: type HC <-> GP | 18 | **all** |
| weight: +1 kg | 100 | **all** |
| weight: -1 kg | 100 | **all** |
| weight: +10 kg | 100 | **all** |
| weight: +0.1 % | 100 | **all** |
| weight: +1 % | 100 | **all** |
| weight: -10 % | 100 | **all** |
| weight: digits transposed | 90 | **all** |
| weight: tonnes read as kg | 100 | **all** |
| weight: a digit lost | 100 | **all** |

### Blanked value: must be sent to a person: 988 of 988

| Change | Cases | Handled correctly |
|---|---|---|
| missing: N/A | 247 | **all** |
| missing: empty | 247 | **all** |
| missing: TBA | 247 | **all** |
| missing: underscores | 247 | **all** |

Repeated with seeds 2, 3, 4, 5 (different random picks, overlapping cases): 15336 further cases, **0 failures**.

### Known limit (by design)

The address after ` | ` in a party name is not compared, only the name. Changing or dropping the address is therefore not flagged (11 of 11 and 11 of 11 cases). This matches how the organisers define a defect (a different party), but a real deployment may want it checked.

## 2. Fuzzing whole documents

Real SI/BL text files (89 pairs) are rewritten, then read by the real extractor and comparator. Only `.txt` attachments are rewritten; PDF, DOCX and XLSX go through the same extractor after text extraction and are covered by the snapshot tests.

### Layout changes: the verdict must not change: 890 of 890

| Change | Cases | Handled correctly |
|---|---|---|
| windows line endings | 89 | **all** |
| blank lines between rows | 89 | **all** |
| trailing spaces | 89 | **all** |
| labels in capitals | 89 | **all** |
| space before the colon | 89 | **all** |
| bar instead of colon | 89 | **all** |
| rows in a different order | 89 | **all** |
| other label wording | 89 | **all** |
| page furniture between rows | 89 | **all** |
| leading/trailing blank lines | 89 | **all** |

### Wording the extractor does not know: must be escalated, never a silent "no mismatch": 267 of 267

| Change | Cases | Handled correctly |
|---|---|---|
| labels the extractor does not know | 89 | **all** |
| value on the line below its label | 89 | **all** |
| mistyped labels | 89 | **all** |

### A real defect written into the document: found, in the right field, and only that field: 1948 of 1948

| Change | Cases | Handled correctly |
|---|---|---|
| name: different company | 153 | **all** |
| name: one letter changed | 150 | **all** |
| name: one letter dropped | 150 | **all** |
| name: two letters swapped | 145 | **all** |
| name: word added | 153 | **all** |
| name: word dropped | 127 | **all** |
| name: legal form swapped | 31 | **all** |
| port: different port | 102 | **all** |
| port: one letter changed | 102 | **all** |
| port: same name, other UN/LOCODE | 102 | **all** |
| port: other country | 96 | **all** |
| container: count + 1 | 51 | **all** |
| container: size 40 <-> 20 | 51 | **all** |
| container: type HC <-> GP | 37 | **all** |
| weight: +1 kg | 51 | **all** |
| weight: -1 kg | 51 | **all** |
| weight: +10 kg | 51 | **all** |
| weight: +0.1 % | 51 | **all** |
| weight: +1 % | 51 | **all** |
| weight: -10 % | 51 | **all** |
| weight: digits transposed | 46 | **all** |
| weight: tonnes read as kg | 51 | **all** |
| weight: a digit lost | 51 | **all** |
| container: count - 1 | 40 | **all** |
| name: digit changed | 4 | **all** |

Repeated with seeds 2, 3, 4, 5: 12420 further cases, **0 failures**.

With unfamiliar wording the checker could not read the value in 267 of 267 cases and said so each time, so a person reviews them. With a Gemini key the AI step can read these; here it is off.

## 3. The organisers' own ground truth

Rules only, scored with the organisers' scorer on their data and on three fresh datasets from their generator. These datasets are synthetic and this result is saturated, which is why sections 1 and 2 exist.

| Dataset | Emails | Kind of email | Defects caught | False alarms (precision) | Field match | Cases sent to review (recall / precision) | Document checks fully right |
|---|---|---|---|---|---|---|---|
| given data (seed 42) | 520 | 100% | 100% | 100% | 100% | 100% / 100% | 46/46 |
| fresh data, seed 1 | 520 | 100% | 100% | 100% | 100% | 100% / 100% | 61/61 |
| fresh data, seed 2 | 520 | 100% | 100% | 100% | 100% | 100% / 100% | 55/55 |
| fresh data, seed 3 | 520 | 100% | 100% | 100% | 100% | 100% / 100% | 61/61 |

## 4. Team-labelled sample

_Not done yet: no labels in `validation/labels/`. Send `validation/label_packet/packet.html` to teammates, put the CSVs they download into `validation/labels/`, and run this again._

## 5. Bugs this found

- **Weights 1 kg apart counted as equal** (fuzzer: 0 of 100 caught). The rounding tolerance was applied as "at most" instead of "less than", so `131,058 KG` and `131,059 KG` matched. Fixed in `compare.py`; the organisers' scores did not change, and a regression test now covers it.

## 6. What this does not show

- The fuzz cases were written by the team that wrote the checker; they are a regression net and a way to find bugs, not an independent test.
- Section 3 data is synthetic; a clean score there says little about real forwarded threads and messy scans.
- Scanned or unreadable documents are sent to a person by design; the AI reading of scans is a suggestion, not a verdict.
- Only `.txt` documents are rewritten in section 2.
- The keyword rules that sort emails into kinds were written from the wording of this dataset. The fresh datasets in section 3 come from the same generator, so they share that wording; a real inbox would need the rules widened. The optional AI fallback for emails the rules cannot place exists for that reason, but it has not been measured here.
