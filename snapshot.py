"""Precomputed results, so the server starts instantly instead of re-reading every attachment.

results.json holds one result per email plus a fingerprint of everything those results depend on:
the inbox files and the source of the deterministic stages.  If any of them change, the
fingerprint no longer matches and the snapshot is ignored (the server then computes live).
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
CODE = ["loader.py", "classify.py", "extract.py", "compare.py", "readers.py", "pipeline.py"]
TEXT_SUFFIXES = {".py", ".json", ".txt"}


def _bytes(path):
    """File contents, with Windows line endings folded so the same file hashes the same everywhere."""
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n") if path.suffix in TEXT_SUFFIXES else data


def fingerprint(data_dir):
    h = hashlib.sha256()
    for sub in ("inbox", "attachments"):
        # email_* only (so stray files like Thumbs.db are ignored), sorted by name (not by Path,
        # whose order differs between Windows and Linux)
        for p in sorted((q for q in (Path(data_dir) / sub).glob("email_*") if q.is_file()), key=lambda q: q.name):
            h.update(p.name.encode())
            h.update(_bytes(p))
    for name in CODE:
        h.update(name.encode())
        h.update(_bytes(HERE / name))
    return h.hexdigest()


def save(path, data_dir, results, ai=False):
    snap = {"fingerprint": fingerprint(data_dir), "ai": ai, "results": results}
    Path(path).write_text(json.dumps(snap, sort_keys=True, separators=(",", ":")))


def load(path, data_dir):
    """-> the results dict, or None if there is no snapshot or it no longer matches."""
    try:
        snap = json.loads(Path(path).read_text())
        return snap["results"] if snap["fingerprint"] == fingerprint(data_dir) else None
    except (OSError, ValueError, KeyError):
        return None
