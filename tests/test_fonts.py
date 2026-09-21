"""The app keeps the fonts of the first version Joe gave us (commit 75fbb19): Inter from Google Fonts, the same
system-font stack, and the same monospace stack for raw document text. Nothing else may be added.
Run from the project folder:  python -m unittest discover -s tests -t . -v
"""
import re
import unittest
from pathlib import Path

# copied from static/index.html at commit 75fbb19
JOE_BODY = '-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",Inter,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'
JOE_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
JOE_LINK = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
ALLOWED = {"var(--font)", "inherit", JOE_BODY, JOE_MONO}

PAGE = Path("static/index.html").read_text()
SIZE = re.compile(r"^(?:(?:italic|oblique|bold|normal|\d{3})\s+)*[\d.]+(?:px|em|rem|%)(?:/[\d.]+(?:px|em|rem|%)?)?\s+(.+)$")


def families():
    """Every font family list that the page declares, from `font-family:` and from `font:` shorthands."""
    found = [m.group(1).strip() for m in re.finditer(r"(?<![-\w])font-family\s*:\s*([^;}]+)", PAGE)]
    for m in re.finditer(r"(?<![-\w])font\s*:\s*([^;}]+)", PAGE):
        value = m.group(1).strip()
        sized = SIZE.match(value)
        found.append(sized.group(1).strip() if sized else value)
    return found


class TestFontsAreJoes(unittest.TestCase):
    def test_body_font_stack_is_unchanged(self):
        self.assertIn(f"--font:{JOE_BODY}", PAGE)

    def test_the_only_font_file_is_joes_inter_link(self):
        self.assertEqual(re.findall(r"https://fonts\.googleapis\.com/css[^\"' )]*", PAGE), [JOE_LINK])
        self.assertNotIn("@font-face", PAGE)
        self.assertNotIn("@import", PAGE)

    def test_every_declared_font_family_is_one_of_joes(self):
        stray = [f for f in families() if f not in ALLOWED]
        self.assertEqual(stray, [], "a font that is not in Joe's first version was added")

    def test_monospace_is_only_used_where_joe_used_it(self):
        self.assertEqual(PAGE.count(JOE_MONO), 1)

    def test_side_documents_use_the_same_fonts(self):
        for path in ("validation/label_packet.py", "docs/make_diagrams.py"):
            text = Path(path).read_text()
            self.assertIn(JOE_BODY, text, path)
            self.assertIn(JOE_LINK, text, path)
        for svg in ("docs/architecture.svg", "docs/deployment.svg"):
            self.assertIn(JOE_BODY, Path(svg).read_text(), svg)


if __name__ == "__main__":
    unittest.main()
