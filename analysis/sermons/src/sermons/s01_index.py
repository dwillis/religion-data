"""S01 -- Index, document-type detection, and metadata join.

Builds ``corpus.parquet`` -- the spine every later stage joins against.  One row
per document with identity, provenance, an inferred title, a resolved
``sermon_date`` (+ ``date_source``), basic size stats, a ``content_sha`` for
resumability, and a detected ``doc_type`` in {transcribed, prepared, unknown}.

Metadata (congregation name, location, denomination, tradition family) comes
from the USER-MAINTAINED ``config/congregations.csv``.  The pipeline never
invents this mapping: if the file is missing it writes a seed template and
exits; on every run it reports congregations/documents not covered by metadata.

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s01_index.py
"""

from __future__ import annotations

import argparse
import re
from datetime import date

import polars as pl

from sermons import common

CONGREGATIONS_CSV = common.CONFIG_DIR / "congregations.csv"
DATES_CSV = common.CONFIG_DIR / "sermon_dates.csv"

# --- Filename parsing ------------------------------------------------------

# Leading compact date e.g. "20220220 What is..." or "2022-02-20 ..."
_RE_LEADING_YMD = re.compile(r"^\s*(\d{4})[-_]?(\d{2})[-_]?(\d{2})\b")
# "Dec. 26, 2021" / "December 26, 2021" / "Dec 26 2021"
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
_MONTH_ABBR = {m[:3].lower(): i for m, i in _MONTHS.items()} | {"sept": 9}
_RE_MONTH_DAY_YEAR = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")

# Scripture-ref-ish tokens we strip from titles for a cleaner display title.
_RE_SCRIPTURE_TOKEN = re.compile(
    r"\b(?:[1-3]\s?)?[A-Z][a-z]+\.?\s?\d{1,3}(?::\d{1,3}(?:-\d{1,3})?)?")


def parse_filename_date(stem: str) -> date | None:
    m = _RE_LEADING_YMD.match(stem)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = _RE_MONTH_DAY_YEAR.search(stem)
    if m:
        mon_raw, day_raw, year_raw = m.groups()
        mon = _MONTHS.get(mon_raw.lower()) or _MONTH_ABBR.get(mon_raw[:3].lower())
        if mon:
            try:
                return date(int(year_raw), mon, int(day_raw))
            except ValueError:
                return None
    return None


def clean_title(stem: str) -> str:
    """Human-friendly title from a filename stem: drop leading dates and
    collapse separators.  We keep scripture references in the title (they are
    informative) but remove a leading date token."""
    t = _RE_LEADING_YMD.sub("", stem)
    t = _RE_MONTH_DAY_YEAR.sub("", t)
    t = re.sub(r"\s*[-–—_]\s*", " - ", t).strip(" -")
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t or stem


# --- Document-type detection ----------------------------------------------

_DISFLUENCY_RE = re.compile(r"\b(uh|um|uhh|umm|er|y'?know|gonna|wanna|kinda|sorta)\b", re.I)
# Transcription placeholders / error stubs that should be excluded from analysis.
_PLACEHOLDER_RE = re.compile(
    r"audio you have selected is no longer available|is not available|please try again later", re.I)
MIN_WORDS = 200  # below this a "sermon" is almost certainly a stub/placeholder


def quality_flag(text: str, n_words: int) -> bool:
    """True if the document is usable; False for stubs/placeholders."""
    if n_words < MIN_WORDS:
        return False
    if _PLACEHOLDER_RE.search(text[:600]):
        return False
    return True


def detect_doc_type(text: str, has_native_breaks: bool) -> tuple[str, float]:
    """Heuristic classifier -> (doc_type, disfluency_rate_per_1k_words).

    The single strongest signal is structural: a long document stored as one
    unbroken block (no paragraph breaks) is auto-transcribed speech -- written
    sermons of any length carry paragraph structure.  Disfluency density
    ('uh'/'um') corroborates.  Prepared text has native breaks and ~no
    disfluencies.  ``unknown`` is reserved for genuinely ambiguous short docs.
    """
    n_words = max(len(text.split()), 1)
    disfluency_rate = 1000 * len(_DISFLUENCY_RE.findall(text)) / n_words

    if not has_native_breaks:
        # One giant unbroken block -> transcription, unless it's too short to tell.
        if n_words >= 1000 or disfluency_rate >= 0.5:
            return "transcribed", round(disfluency_rate, 3)
        return "unknown", round(disfluency_rate, 3)
    # Has paragraph structure: prepared prose unless it's visibly disfluent speech.
    if disfluency_rate >= 1.5:
        return "transcribed", round(disfluency_rate, 3)
    return "prepared", round(disfluency_rate, 3)


# --- Metadata --------------------------------------------------------------

def seed_congregations_template(dirs: list[str]) -> None:
    df = pl.DataFrame({
        "congregation_dir": sorted(dirs),
        "congregation": ["" for _ in dirs],
        "denomination": ["" for _ in dirs],
        "tradition_family": ["" for _ in dirs],
        "location": ["" for _ in dirs],
    })
    df.write_csv(CONGREGATIONS_CSV)


def load_supplied_dates() -> pl.DataFrame | None:
    if not DATES_CSV.exists():
        return None
    df = pl.read_csv(DATES_CSV, infer_schema_length=1000)
    # Accept either a 'path' or 'doc_id' join key plus a 'sermon_date' column.
    if "sermon_date" not in df.columns:
        print(f"  ! {DATES_CSV} has no 'sermon_date' column; ignoring.")
        return None
    df = df.with_columns(pl.col("sermon_date").cast(pl.Utf8).str.to_date(strict=False).alias("sermon_date"))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="S01 build corpus index + metadata.")
    common.add_common_args(parser)
    args = parser.parse_args()

    norm_path = common.cache("normalized.parquet")
    if not norm_path.exists():
        raise SystemExit("Run S00 (s00_ingest.py) first to produce cache/normalized.parquet")
    norm_full = pl.read_parquet(norm_path).with_columns(
        pl.col("path").str.split("/").list.get(-2).alias("congregation_dir"))
    all_dirs = norm_full["congregation_dir"].unique().to_list()
    norm = common.apply_filters(norm_full, args)

    print(f"Indexing {norm.height} documents")
    records = []
    for row in norm.iter_rows(named=True):
        path = row["path"]
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        text = row["text"]
        doc_type, disfl = detect_doc_type(text, row["has_native_breaks"])
        fdate = parse_filename_date(stem)
        n_words = len(text.split())
        records.append({
            "doc_id": row["doc_id"],
            "congregation_dir": path.split("/")[-2],
            "path": path,
            "source_format": row["source_format"],
            "title": clean_title(stem),
            "filename_date": fdate,
            "doc_type": doc_type,
            "disfluency_rate": disfl,
            "word_count": n_words,
            "char_count": len(text),
            "usable": quality_flag(text, n_words),
            "content_sha": common.content_hash(text),
        })
    corpus = pl.DataFrame(records)

    # --- Join supplied sermon dates (preferred over filename parse) ---
    supplied = load_supplied_dates()
    if supplied is not None:
        key = "doc_id" if "doc_id" in supplied.columns else ("path" if "path" in supplied.columns else None)
        if key:
            corpus = corpus.join(supplied.select([key, "sermon_date"]).unique(subset=[key]), on=key, how="left")
        else:
            print(f"  ! {DATES_CSV} needs a 'doc_id' or 'path' column; ignoring.")
            corpus = corpus.with_columns(pl.lit(None, dtype=pl.Date).alias("sermon_date"))
    else:
        corpus = corpus.with_columns(pl.lit(None, dtype=pl.Date).alias("sermon_date"))

    corpus = corpus.with_columns(
        pl.when(pl.col("sermon_date").is_not_null()).then(pl.lit("supplied"))
        .when(pl.col("filename_date").is_not_null()).then(pl.lit("filename"))
        .otherwise(pl.lit("none")).alias("date_source"),
        pl.coalesce(["sermon_date", "filename_date"]).alias("sermon_date"),
    ).with_columns(pl.col("sermon_date").dt.year().alias("year"))

    # --- Congregation metadata join ---
    if not CONGREGATIONS_CSV.exists():
        seed_congregations_template(all_dirs)
        raise SystemExit(
            f"No metadata yet. Wrote a seed template to {CONGREGATIONS_CSV}.\n"
            f"Fill in congregation / denomination / tradition_family / location, then re-run S01."
        )
    meta = pl.read_csv(CONGREGATIONS_CSV, infer_schema_length=1000)
    corpus = corpus.join(meta, on="congregation_dir", how="left")

    missing = corpus.filter(
        pl.col("denomination").is_null() | (pl.col("denomination").cast(pl.Utf8).str.strip_chars() == "")
    )["congregation_dir"].unique().to_list()
    if missing:
        print(f"  ⚠ {len(missing)} congregation(s) lack metadata in congregations.csv: {sorted(missing)}")

    common.write_parquet(corpus, "corpus.parquet")
    print(f"Wrote corpus.parquet: {corpus.height} rows")
    print("doc_type distribution:")
    print(corpus.group_by("doc_type").len().sort("len", descending=True))
    dated = corpus.filter(pl.col("sermon_date").is_not_null()).height
    print(f"dated documents: {dated}/{corpus.height} "
          f"({corpus.group_by('date_source').len().sort('len', descending=True).to_dicts()})")


if __name__ == "__main__":
    main()
