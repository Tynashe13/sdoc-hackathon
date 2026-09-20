"""Turn any attachment (txt / pdf / docx / xlsx) into plain text lines.

Every reader returns text where each field sits on its own line, so the
extractor never needs to know what the original file format was.
Raises ReadError when a file cannot be opened (-> NEEDS_REVIEW: unreadable).
"""
import io


class ReadError(Exception):
    pass


class NoTextError(ReadError):
    """The file opens fine but has no text layer (a scan / photo)."""


def read_attachment(name: str, data: bytes) -> str:
    ext = name.rsplit(".", 1)[-1].lower()
    try:
        if ext == "txt":
            text = data.decode("utf-8", errors="replace")
        elif ext == "pdf":
            text = _pdf(data)
        elif ext == "docx":
            text = _docx(data)
        elif ext in ("xlsx", "xlsm"):
            text = _xlsx(data)
        else:
            raise ReadError(f"unsupported file type: .{ext}")
    except ReadError:
        raise
    except Exception as exc:                      # corrupt / not really a PDF, etc.
        raise ReadError(f"{type(exc).__name__}: {exc}") from exc
    if not text.strip():
        raise NoTextError("no text found (scanned / image-only?)")
    return text


def _pdf(data):
    """Labels are bold, values are regular.  A long label can overlap its value, which
    scrambles normal extraction, so read the two fonts separately and re-join per row."""
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            def keep(bold):
                return page.filter(lambda o: o["object_type"] != "char"
                                   or ("Bold" in o.get("fontname", "")) == bold)
            rows = []                                   # [top, label_text, value_text]
            for idx, part in ((1, keep(False)), (2, keep(True))):
                for ln in part.extract_text_lines():
                    row = next((r for r in rows if abs(r[0] - ln["top"]) < 1.5), None)
                    if row is None:
                        row = [ln["top"], "", ""]
                        rows.append(row)
                    row[idx] += ln["text"]
            for _, value, label in sorted(rows):
                out.append((label + " " + value).strip())
    return "\n".join(out)


def _docx(data):
    import docx
    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs]
    for table in d.tables:                        # label | value tables
        for row in table.rows:
            lines.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(lines)


def _xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    lines = []
    for ws in wb:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def pdf_page_pngs(data: bytes, max_pages: int = 2, resolution: int = 150):
    """Render PDF pages to PNG bytes so a vision model can read a scan."""
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:max_pages]:
            buf = io.BytesIO()
            page.to_image(resolution=resolution).original.save(buf, "PNG")
            out.append(buf.getvalue())
    return out
