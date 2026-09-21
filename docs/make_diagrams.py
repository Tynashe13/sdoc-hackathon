"""Draws docs/architecture.svg and docs/deployment.svg.   python docs/make_diagrams.py"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
INK, MUTED, LINE, BG = "#1c1c1e", "#5b5b61", "#c7c7cc", "#ffffff"
RULE = ("#eaf2ff", "#0a5fd6")
AI = ("#f5eeff", "#7d3cc8")
HUMAN = ("#fff3e0", "#b85c00")
OK, BAD, GRAY = ("#e6f6ec", "#1f8a4c"), ("#fdeaea", "#c62828"), ("#f0f0f3", "#6e6e73")
# the app's own fonts (Inter, from the same Google Fonts link as static/index.html, then the same fallbacks)
FONT = '-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",Inter,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'
FONT_CSS = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');"


def wrap(text, width, size):
    per = max(8, int(width / (size * 0.53)))
    lines, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + (1 if cur else 0) > per:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur] if cur else lines


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def add(self, s):
        self.parts.append(s)

    def rect(self, x, y, w, h, colors, dash=False, r=14, sw=2):
        fill, stroke = colors
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{sw}"{" stroke-dasharray=\'8 6\'" if dash else ""}/>')

    def text(self, x, y, s, size=16, weight=400, fill=INK, anchor="start", width=None, lh=1.32):
        lines = wrap(s, width, size) if width else [s]
        for i, ln in enumerate(lines):
            self.add(f'<text x="{x}" y="{y + i * size * lh:.1f}" font-size="{size}" font-weight="{weight}" '
                     f'fill="{fill}" text-anchor="{anchor}">{escape(ln)}</text>')
        return y + len(lines) * size * lh

    def pill(self, x, y, label, colors, size=12):
        w = len(label) * size * 0.68 + 18
        self.add(f'<rect x="{x - w}" y="{y}" width="{w}" height="{size + 10}" rx="{(size + 10) / 2}" fill="{colors[1]}"/>')
        self.add(f'<text x="{x - w / 2}" y="{y + size + 1}" font-size="{size}" font-weight="700" fill="#fff" '
                 f'text-anchor="middle" letter-spacing="0.6">{escape(label)}</text>')

    def arrow(self, pts, color=INK, dash=False, sw=2.5, head=True):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"'
                 f'{" stroke-dasharray=\'7 6\'" if dash else ""}{f" marker-end=\'url(#h-{color[1:]})\'" if head else ""}/>')

    def save(self, name):
        colors = {INK, AI[1], HUMAN[1], RULE[1], MUTED, GRAY[1]}
        defs = "".join(f'<marker id="h-{c[1:]}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" '
                       f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in colors)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" '
               f'font-family=\'{FONT}\'><title>{escape(name)}</title><style>{escape(FONT_CSS)}</style><defs>{defs}</defs>'
               f'<rect width="{self.w}" height="{self.h}" fill="{BG}"/>' + "".join(self.parts) + "</svg>")
        (OUT / name).write_text(svg, encoding="utf-8")


def architecture():
    s = Svg(1600, 900)
    s.text(40, 62, "SDOC Check: from an email to a verdict", 34, 700)
    s.text(40, 94, "Rules decide. AI only helps where rules cannot, and a person settles anything uncertain.", 18, 400, MUTED)

    # input
    s.rect(40, 150, 160, 196, GRAY)
    s.text(120, 190, "Inbox", 20, 700, anchor="middle")
    s.text(120, 220, "520 emails", 15, 500, anchor="middle")
    s.text(120, 252, "with TXT, PDF, DOCX and XLSX attachments", 14, 400, MUTED, "middle", 130)
    # stages
    stages = [
        (225, "1  Classify", "Keyword rules sort each email: document check, SI request, invoice query, general or spam."),
        (495, "2  Read", "Turns TXT, PDF, DOCX and XLSX into text. A scan or a broken file is never guessed at."),
        (765, "3  Extract", "Label patterns find the 7 fields under any wording. Each value keeps the exact line it came from."),
        (1035, "4  Compare", "Names, ports, containers and weights are normalised, then compared field by field."),
    ]
    for x, title, body in stages:
        s.rect(x, 150, 245, 196, RULE)
        s.text(x + 16, 186, title, 21, 700, RULE[1])
        s.pill(x + 229, 160, "RULES", RULE, 11)
        s.text(x + 16, 216, body, 15, 400, INK, width=215)
    s.text(1035 + 16, 316, "Deterministic: the AI never judges a match.", 13.5, 700, RULE[1], width=215)
    for a, b in ((200, 225), (470, 495), (740, 765), (1010, 1035)):
        s.arrow([(a, 240), (b - 2, 240)], INK)

    # verdicts
    s.text(1310, 138, "Verdict", 16, 700, MUTED)
    pills = [(OK, "OK", "63", "No mismatch detected"),
             (BAD, "MISMATCH", "46", "The differing fields, each with the quoted SI and BL lines"),
             (HUMAN, "NEEDS REVIEW", "20", "Wrong document, missing attachment, unreadable scan or blank value"),
             (GRAY, "AWAITING", "91", "Only the draft BL was requested, so there is nothing to compare")]
    y = 150
    rows = {}
    for col, label, n, desc in pills:
        h = 46 + len(wrap(desc, 226, 13.5)) * 18
        s.rect(1310, y, 250, h, col, r=12)
        s.text(1326, y + 27, label, 16, 700, col[1])
        s.text(1544, y + 27, n, 16, 700, col[1], "end")
        s.text(1326, y + 50, desc, 13.5, 400, INK, width=226)
        rows[label] = (y, h)
        y += h + 10
    s.arrow([(1280, 240), (1308, 240)], INK)
    s.text(1310, y + 10, "Counts: the 220 document checks in the demo inbox.", 12.5, 400, MUTED, width=250)

    # AI
    s.rect(225, 430, 1055, 160, AI, dash=True)
    s.text(245, 458, "Gemini: optional, and off when there is no API key", 17, 700, AI[1])
    cols = [(347, "Only when the rules are unsure, it suggests the kind of email. Otherwise the email is filed as General."),
            (617, "Reads a scanned page and offers a suggestion. A person confirms it; it is never a verdict."),
            (887, "Fills a missing field only if it quotes a line that really is in the document; otherwise it is ignored.")]
    for cx, t in cols:
        s.arrow([(cx, 430), (cx, 350)], AI[1], dash=True)
        s.text(cx - 104, 488, t, 14, 400, INK, width=220)
    s.text(1160, 488, "Every AI answer is either", 14, 700, AI[1], "middle")
    s.text(1160, 508, "checked against the", 14, 700, AI[1], "middle")
    s.text(1160, 528, "document or shown to a", 14, 700, AI[1], "middle")
    s.text(1160, 548, "person as a suggestion.", 14, 700, AI[1], "middle")

    # human loop
    ny, nh = rows["NEEDS REVIEW"]
    s.arrow([(1560, ny + nh / 2), (1585, ny + nh / 2), (1585, 620), (400, 620), (400, 660)], HUMAN[1])
    s.text(1290, 612, "cases the system cannot decide wait here", 13.5, 700, HUMAN[1], "end")
    boxes = [(225, "Review queue", "Each case shows the reason and both documents. Nothing here is auto-approved."),
             (610, "A person decides", "Sees the quoted lines and any AI suggestion. Confirms or corrects the values, or marks the case resolved."),
             (995, "Decision recorded", "The comparison is recomputed from the person's values and saved with a time and a note. Undo any time. It appears in the CSV report.")]
    for x, title, body in boxes:
        s.rect(x, 660, 350, 150, HUMAN)
        s.text(x + 18, 694, title, 19, 700, HUMAN[1])
        s.text(x + 18, 722, body, 14.5, 400, INK, width=314)
    s.arrow([(575, 735), (608, 735)], HUMAN[1])
    s.arrow([(960, 735), (993, 735)], HUMAN[1])

    # legend
    s.rect(40, 858, 20, 20, RULE, r=4)
    s.text(70, 874, "Rules: deterministic and reproducible", 14.5, 500)
    s.rect(400, 858, 20, 20, AI, dash=True, r=4)
    s.text(430, 874, "AI: optional, always checked or confirmed", 14.5, 500)
    s.rect(800, 858, 20, 20, HUMAN, r=4)
    s.text(830, 874, "A person", 14.5, 500)
    s.text(1560, 874, "Every value on screen links back to its source line, file and line number.", 14.5, 500, MUTED, "end")
    s.save("architecture.svg")


def deployment():
    s = Svg(1600, 900)
    s.text(40, 62, "Where it runs", 34, 700)
    s.text(40, 94, "One Python function on Vercel serves the page and the API. Decisions live in Supabase.", 18, 400, MUTED)

    s.rect(40, 170, 240, 110, GRAY)
    s.text(160, 205, "GitHub", 20, 700, anchor="middle")
    s.text(160, 232, "the team's repository", 14.5, 400, MUTED, "middle")
    s.text(160, 254, "main branch", 14.5, 500, anchor="middle")
    s.rect(40, 470, 240, 130, GRAY)
    s.text(160, 505, "Browser", 20, 700, anchor="middle")
    s.text(160, 532, "a judge's phone or laptop", 14.5, 400, MUTED, "middle")
    s.text(160, 556, "the live link, no install", 14.5, 500, anchor="middle")

    s.rect(400, 150, 720, 520, RULE, sw=2.5)
    s.text(424, 188, "Vercel", 24, 700, RULE[1])
    s.text(1100, 188, "Python function, HTTPS", 15, 500, RULE[1], "end")
    inner = [(215, 96, "Web page", "static/index.html: inbox, comparison table with source quotes, review form, CSV export."),
             (327, 116, "Flask API (app.py)", "/api/emails, /api/emails/{id}, recheck, resolve, retry, undo, /api/report.csv and /healthz."),
             (459, 96, "Checking code", "classify, readers, extract, compare, pipeline: the same rules-only code that produced the verdicts."),
             (571, 82, "results.json", "The 520 precomputed verdicts, with a fingerprint of the data and the code.")]
    for y, h, t, b in inner:
        s.rect(424, y, 672, h, ("#ffffff", RULE[1]), r=10, sw=1.5)
        s.text(444, y + 30, t, 17, 700)
        s.text(444, y + 56, b, 14.5, 400, INK, width=632)

    s.rect(1290, 170, 270, 170, HUMAN)
    s.text(1310, 204, "Supabase", 20, 700, HUMAN[1])
    s.text(1310, 232, "Postgres table 'reviews', one row per decision. Row-level security is on; only the server holds the key.", 14, 400, INK, width=232)
    s.rect(1290, 440, 270, 150, AI, dash=True)
    s.text(1310, 474, "Gemini API", 20, 700, AI[1])
    s.text(1310, 502, "Optional. Used only when a key is set in Vercel's environment variables.", 14, 400, INK, width=232)

    s.arrow([(160, 282), (160, 330), (398, 330)], INK)
    s.text(176, 300, "push to main:", 14, 700)
    s.text(176, 319, "build and deploy", 14, 700)
    s.text(176, 358, "other branches get", 13.5, 400, MUTED)
    s.text(176, 376, "a private preview", 13.5, 400, MUTED)
    s.arrow([(282, 535), (398, 535)], INK)
    s.arrow([(398, 555), (282, 555)], INK)
    s.text(340, 588, "HTTPS", 14, 700, anchor="middle")
    s.arrow([(1122, 265), (1288, 265)], HUMAN[1])
    s.arrow([(1288, 290), (1122, 290)], HUMAN[1])
    s.text(1205, 250, "REST", 13.5, 700, HUMAN[1], "middle")
    s.arrow([(1122, 515), (1288, 515)], AI[1], dash=True)
    s.text(1205, 500, "if a key is set", 13.5, 700, AI[1], "middle")

    s.rect(40, 730, 1520, 128, ("#f7f7f9", LINE))
    s.text(60, 762, "Start-up", 17, 700)
    s.text(60, 788, "A fingerprint (SHA-256 of the inbox files and the checking code) is compared with results.json. If it matches, the app is ready in about a second. "
           "If not, the verdicts are recomputed in the background and the page shows progress. A stale snapshot is never used.", 14.5, 400, width=1480)
    s.save("deployment.svg")


if __name__ == "__main__":
    architecture()
    deployment()
    print("wrote docs/architecture.svg and docs/deployment.svg")
