"""S04 -- Scripture reference extraction & coverage.

Gazetteer-driven extraction of Bible references from ``clean_text`` (and the
title).  Each match resolves to a canonical book + chapter(:verse) and is tagged
with a confidence tier:

  * ``verse``   -- a chapter number followed the book name ("Matthew 5",
                   "Romans 8:28", "Matthew chapter 5"); high confidence.
  * ``mention`` -- bare book name, no chapter.  For books whose names are also
                   common personal names (John, Mark, James, Acts, ...) these are
                   flagged ``ambiguous_name`` so coverage rollups can exclude them.

Outputs:
  * ``scripture_refs.parquet``     -- one row per reference.
  * ``scripture_coverage.parquet`` -- doc x book counts joined to denomination/year.

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s04_scripture.py
"""

from __future__ import annotations

import argparse
import re

import polars as pl
from tqdm import tqdm

from sermons import common

BOOKS_CSV = common.CONFIG_DIR / "bible_books.csv"
# Books whose names are also common English personal names -> bare mentions are unreliable.
AMBIGUOUS = {"John", "Mark", "Luke", "Matthew", "James", "Jude", "Acts", "Job", "Amos", "Joshua", "Ruth", "Esther"}


# Optional "chapter N(:verse(-verse))" tail shared by both matchers.
_CHAP_TAIL = r"(?:\.?\s+(?:chapter\s+|ch\.?\s+)?(?P<chap>\d{1,3})(?::(?P<v1>\d{1,3})(?:\s*[-]\s*(?P<v2>\d{1,3}))?)?)"


def build_matcher():
    """Return (name_re, abbr_re, name_to_canon, abbr_to_canon, testament).

    Book references are proper nouns, so we match *case-sensitively* -- this
    alone removes the catastrophic 'Is'->"is" / 'Re'->"re" false positives.
    Two matchers:
      * name_re : full canonical book names; chapter optional (bare mention OK).
      * abbr_re : abbreviations; chapter REQUIRED (a bare 'Is'/'Am'/'Jn' at a
                  sentence start is never a reference).
    """
    books = pl.read_csv(BOOKS_CSV)
    name_to_canon: dict[str, str] = {}
    abbr_to_canon: dict[str, str] = {}
    testament: dict[str, str] = {}
    for row in books.iter_rows(named=True):
        canon = row["book"]
        testament[canon] = row["testament"]
        name_to_canon[canon] = canon
        if row["aliases"]:
            for a in str(row["aliases"]).split("|"):
                if a:
                    abbr_to_canon[a] = canon
    names_sorted = sorted(name_to_canon, key=len, reverse=True)
    abbrs_sorted = sorted(abbr_to_canon, key=len, reverse=True)
    name_re = re.compile(rf"\b(?P<book>{'|'.join(re.escape(n) for n in names_sorted)})\b{_CHAP_TAIL}?")
    abbr_re = re.compile(rf"\b(?P<book>{'|'.join(re.escape(a) for a in abbrs_sorted)})\b{_CHAP_TAIL}")
    return name_re, abbr_re, name_to_canon, abbr_to_canon, testament


def _ref(canon, testament, m) -> dict:
    chap = m.group("chap")
    return {
        "book": canon,
        "testament": testament[canon],
        "chapter": int(chap) if chap else None,
        "verse_start": int(m.group("v1")) if m.group("v1") else None,
        "verse_end": int(m.group("v2")) if m.group("v2") else None,
        "confidence": "verse" if chap else "mention",
        "ambiguous_name": canon in AMBIGUOUS,
        "span": m.group(0).strip(),
    }


def extract(text: str, name_re, abbr_re, name_to_canon, abbr_to_canon, testament) -> list[dict]:
    refs = [_ref(name_to_canon[m.group("book")], testament, m) for m in name_re.finditer(text)]
    refs += [_ref(abbr_to_canon[m.group("book")], testament, m) for m in abbr_re.finditer(text)]
    return refs


def main() -> None:
    parser = argparse.ArgumentParser(description="S04 scripture reference extraction.")
    common.add_common_args(parser)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet"), args)
    clean = pl.read_parquet(common.cache("clean.parquet")).select(["doc_id", "clean_text"])
    df = corpus.select(["doc_id", "title", "denomination", "tradition_family", "year"]).join(
        clean, on="doc_id", how="inner")

    name_re, abbr_re, name_to_canon, abbr_to_canon, testament = build_matcher()
    ref_rows = []
    for row in tqdm(df.iter_rows(named=True), total=df.height, desc="scripture"):
        text = (row["title"] or "") + ". " + (row["clean_text"] or "")
        for r in extract(text, name_re, abbr_re, name_to_canon, abbr_to_canon, testament):
            r["doc_id"] = row["doc_id"]
            ref_rows.append(r)

    refs_schema = {
        "book": pl.Utf8, "testament": pl.Utf8, "chapter": pl.Int64, "verse_start": pl.Int64,
        "verse_end": pl.Int64, "confidence": pl.Utf8, "ambiguous_name": pl.Boolean,
        "span": pl.Utf8, "doc_id": pl.Utf8,
    }
    refs = pl.DataFrame(ref_rows, schema=refs_schema)
    common.write_parquet(refs, "scripture_refs.parquet")
    print(f"Wrote scripture_refs.parquet: {refs.height} references")

    # High-confidence coverage: drop bare mentions of ambiguous-name books.
    hc = refs.filter(~((pl.col("confidence") == "mention") & pl.col("ambiguous_name")))
    cov = (hc.group_by(["doc_id", "book", "testament"]).len().rename({"len": "n_refs"})
           .join(corpus.select(["doc_id", "denomination", "tradition_family", "year"]), on="doc_id", how="left"))
    common.write_parquet(cov, "scripture_coverage.parquet")
    print(f"Wrote scripture_coverage.parquet: {cov.height} (doc, book) rows")

    top = (hc.group_by("book").len().sort("len", descending=True).head(15))
    print("Top books (high-confidence):")
    print(top)


if __name__ == "__main__":
    main()
