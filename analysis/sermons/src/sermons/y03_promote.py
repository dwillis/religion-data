"""Y03 -- Promote confirmed sermons into the corpus.

After reviewing ``service_review.csv`` (from y02) -- setting ``confirmed=yes`` on
the good ones and optionally adjusting ``sermon_start``/``sermon_end`` -- this
stage re-cuts the sermon text at the (possibly edited) boundaries and writes it
into ``sermons/<congregation_dir>/<YYYYMMDD> <title>.txt``, the exact ingest
contract S00 expects.  From there the new sermon flows through S00-S10 unchanged
(auto-detected ``doc_type=transcribed``; the leading ``YYYYMMDD`` lets S01 parse
``sermon_date`` from the filename).

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/y03_promote.py \
        --congregation grace_bible_text          # promote confirmed rows
    uv run ... y03_promote.py --congregation grace_bible_text --dry-run
"""

from __future__ import annotations

import argparse
import re

import polars as pl

from sermons import common
from sermons.y02_isolate import cut_text

SERVICES_DIR = common.REPO_ROOT / "data" / "youtube_services"
_TRUTHY = {"yes", "y", "true", "1", "x", "ok"}
_BAD_CHARS = re.compile(r'[\\/*?:"<>|]+')


def sanitize_title(title: str) -> str:
    t = _BAD_CHARS.sub("", title).strip()
    t = re.sub(r"\s+", " ", t)
    return t[:120] or "Untitled Sermon"


def main() -> None:
    parser = argparse.ArgumentParser(description="Y03 promote confirmed sermons into sermons/.")
    parser.add_argument("--congregation", required=True)
    parser.add_argument("--dry-run", action="store_true", help="show what would be written")
    args = parser.parse_args()

    base = SERVICES_DIR / args.congregation
    review_path = base / "service_review.csv"
    if not review_path.exists():
        raise SystemExit(f"No review file: {review_path}. Run y02_isolate.py first.")
    review = pl.read_csv(review_path, infer_schema_length=0)  # all-Utf8: tolerant of hand edits

    confirmed = review.filter(
        pl.col("confirmed").cast(pl.Utf8).str.strip_chars().str.to_lowercase().is_in(list(_TRUTHY))
    )
    if confirmed.is_empty():
        raise SystemExit("No rows with confirmed in {yes,y,true,1,x}. Edit service_review.csv first.")

    svc_dir = common.cache("services") / args.congregation
    dest_dir = common.SERMONS_DIR / args.congregation
    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for row in confirmed.iter_rows(named=True):
        sid = row["service_id"]
        seg_path = svc_dir / f"{sid}.segments.parquet"
        if not seg_path.exists():
            print(f"  ! missing segments for {sid}; skipping")
            continue
        segs = pl.read_parquet(seg_path, glob=False)  # service_id may contain [brackets]
        start = float(row["sermon_start"])
        end = float(row["sermon_end"])
        text = cut_text(segs, start, end)
        if len(text.split()) < 200:
            print(f"  ! {sid}: only {len(text.split())} words after cut; skipping (likely bad boundaries)")
            continue

        date = (row.get("upload_date") or "").strip()
        title = sanitize_title(row.get("title") or sid)
        stem = f"{date} {title}" if re.fullmatch(r"\d{8}", date) else title
        dest = dest_dir / f"{stem}.txt"

        if args.dry_run:
            print(f"  would write {dest}  ({len(text.split())} words)")
        else:
            dest.write_text(text, encoding="utf-8")
            print(f"  wrote {common.rel_path(dest)}  ({len(text.split())} words)")
        written += 1

    if args.dry_run:
        print(f"\nDry run: {written} sermon(s) would be promoted to {common.rel_path(dest_dir)}")
    else:
        print(f"\nPromoted {written} sermon(s) -> {common.rel_path(dest_dir)}")
        print("Re-run the pipeline to ingest them: "
              "uv run --group analysis python analysis/sermons/src/sermons/run.py")


if __name__ == "__main__":
    main()
