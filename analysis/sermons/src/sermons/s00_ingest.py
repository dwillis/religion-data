"""S00 -- Ingest / normalize.

Front door that turns every source document (``.txt``/``.md`` today; ``.docx``
and ``.pdf`` when prepared sermons arrive) into plain UTF-8 text, recording the
``source_format`` and whether the original carried native paragraph/line breaks
(which matters for structural segmentation of prepared text).  Existing ``.txt``
files pass through untouched.

Output: ``cache/normalized.parquet`` (doc_id, path, source_format, file_sha,
has_native_breaks, text).  Large -> lives in the gitignored cache.  This is the
single source of document text that S01/S02/S04 read.

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s00_ingest.py
    uv run --group analysis python analysis/sermons/src/sermons/s00_ingest.py --limit 200
"""

from __future__ import annotations

import argparse
import hashlib

import polars as pl
from tqdm import tqdm

from sermons import common

TEXT_EXTS = {".txt", ".md", ".text"}
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
SUPPORTED = TEXT_EXTS | DOCX_EXTS | PDF_EXTS


def _file_sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _read_text(path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_docx(path) -> str:
    import docx  # python-docx, lazy

    doc = docx.Document(str(path))
    # Preserve paragraph breaks -- prepared sermons rely on them for structure.
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_pdf(path) -> str:
    from natural_pdf import PDF  # lazy; already a project dependency

    pdf = PDF(str(path))
    return "\n\n".join(page.extract_text() or "" for page in pdf.pages)


def _has_native_breaks(text: str) -> bool:
    """True if the document carries real paragraph structure.

    The current transcribed corpus is a single unbroken line, so this is False
    for it.  Prepared/written sermons (and most docx/pdf extractions) contain
    blank-line-separated paragraphs.
    """
    blank_line_breaks = text.count("\n\n")
    newlines = text.count("\n")
    return blank_line_breaks >= 3 or (newlines >= 10 and newlines / max(len(text), 1) > 0.002)


def discover() -> list:
    paths = [p for p in common.SERMONS_DIR.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED]
    return sorted(paths)


def normalize_one(path) -> dict | None:
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTS:
            text, fmt = _read_text(path), ext.lstrip(".")
        elif ext in DOCX_EXTS:
            text, fmt = _read_docx(path), "docx"
        elif ext in PDF_EXTS:
            text, fmt = _read_pdf(path), "pdf"
        else:
            return None
    except Exception as exc:  # noqa: BLE001 -- record and skip unreadable files
        print(f"  ! failed to read {path}: {exc}")
        return None
    return {
        "doc_id": common.doc_id_for(path),
        "path": common.rel_path(path),
        "source_format": fmt,
        "file_sha": _file_sha(path),
        "has_native_breaks": _has_native_breaks(text),
        "text": text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="S00 ingest/normalize source documents to text.")
    common.add_common_args(parser)
    args = parser.parse_args()

    paths = discover()
    if args.congregation:
        paths = [p for p in paths if p.parent.name == args.congregation]
    if args.limit:
        paths = paths[: args.limit]
    print(f"Discovered {len(paths)} source documents under {common.SERMONS_DIR}")

    norm_path = common.cache("normalized.parquet")
    prior = None if (args.force or not norm_path.exists()) else pl.read_parquet(norm_path)

    # Resumable: skip files whose bytes are unchanged.
    seen = {}
    if prior is not None and not prior.is_empty():
        seen = dict(zip(prior["doc_id"].to_list(), prior["file_sha"].to_list()))

    rows = []
    pending = []
    for p in paths:
        did = common.doc_id_for(p)
        if not args.force and seen.get(did) == _file_sha(p):
            continue
        pending.append(p)

    print(f"{len(pending)} new/changed documents to normalize ({len(paths) - len(pending)} unchanged).")
    for p in tqdm(pending, desc="normalize"):
        row = normalize_one(p)
        if row is not None:
            rows.append(row)

    fresh = pl.DataFrame(rows) if rows else pl.DataFrame(
        schema={"doc_id": pl.Utf8, "path": pl.Utf8, "source_format": pl.Utf8,
                "file_sha": pl.Utf8, "has_native_breaks": pl.Boolean, "text": pl.Utf8}
    )
    merged = common.merge_incremental(prior, fresh)
    # Drop rows whose source file no longer exists.
    live_ids = {common.doc_id_for(p) for p in paths} if not (args.limit or args.congregation) else set(merged["doc_id"])
    merged = merged.filter(pl.col("doc_id").is_in(list(live_ids)))
    merged.write_parquet(common.cache("normalized.parquet"))
    print(f"Wrote {merged.height} normalized documents -> {common.cache('normalized.parquet')}")


if __name__ == "__main__":
    main()
