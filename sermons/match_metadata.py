#!/usr/bin/env python3
"""
match_metadata.py

Join the plain-text sermon transcripts in sermons/*_text/ to rows in
sermonaudio_MD_metadata.csv, then emit one self-contained JSON per sermon
(metadata + transcript text) and rename folders to their broadcaster_id.

Matching strategy (see plan):
  1. Auto-detect each folder's broadcaster_id by which broadcaster's sermon
     titles best match the folder's filenames (normalized title compare).
  2. Match each .txt file to a sermon row by exact normalized title, with
     date tie-breaking for duplicate titles, then a difflib fuzzy fallback.

Usage:
    python sermons/match_metadata.py --dry-run     # reports only, no writes
    python sermons/match_metadata.py --apply       # write JSON + rename folders
"""

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import sys
from collections import defaultdict

csv.field_size_limit(10_000_000)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "sermonaudio_MD_metadata.csv")
MAP_PATH = os.path.join(HERE, "folder_broadcaster_map.csv")
REPORT_PATH = os.path.join(HERE, "match_report.csv")

# A folder is linked to a broadcaster only if it clears BOTH an absolute floor
# and a match-rate floor. Genuine links match >=0.93 of their files; folders not
# on SermonAudio match <0.02 (a few coincidental title collisions), so 0.30
# cleanly separates them and avoids false links.
MIN_MATCHES = 3
MIN_RATE = 0.30


def norm(s: str) -> str:
    """Normalize a title or filename for comparison."""
    s = s.lower()
    s = re.sub(r"\.txt$", "", s)
    s = re.sub(r"^\d{4}-\d{2}-\d{2}\s*", "", s)  # strip leading ISO date
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def parse_date_from_name(name: str) -> str:
    """Best-effort extract an ISO date (YYYY-MM-DD) from a filename, or ''."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # M-D-YY / MM-DD-YY  and  M.D.YY / MM.DD.YY
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b", name)
    if m:
        mo, da, yr = m.group(1), m.group(2), m.group(3)
        yr = int(yr)
        yr = yr + 2000 if yr < 100 else yr
        return f"{yr:04d}-{int(mo):02d}-{int(da):02d}"
    return ""


def load_csv():
    """Return (rows_by_bid, info_by_bid). rows_by_bid[bid] -> list of row dicts."""
    rows_by_bid = defaultdict(list)
    info_by_bid = {}
    with open(CSV_PATH, newline="") as f:
        for r in csv.DictReader(f):
            bid = r["broadcaster_id"]
            rows_by_bid[bid].append(r)
            if bid not in info_by_bid:
                info_by_bid[bid] = {
                    "name": r["broadcaster_name"],
                    "location": r["broadcaster_location"],
                    "denomination": r["broadcaster_denomination"],
                }
    return rows_by_bid, info_by_bid


def build_title_index(rows_by_bid):
    """bid -> {normtitle: [rows]}."""
    idx = {}
    for bid, rows in rows_by_bid.items():
        d = defaultdict(list)
        for r in rows:
            d[norm(r["title"])].append(r)
        idx[bid] = d
    return idx


def list_text_folders():
    out = []
    for name in sorted(os.listdir(HERE)):
        full = os.path.join(HERE, name)
        if os.path.isdir(full) and name.endswith("_text"):
            out.append(name)
    return out


def folder_files(folder):
    full = os.path.join(HERE, folder)
    return sorted(fn for fn in os.listdir(full) if fn.endswith(".txt"))


def detect_broadcaster(files, title_index):
    """Return (best_bid, best_score) by exact normalized-title match count."""
    normnames = [norm(fn) for fn in files]
    best_bid, best = None, 0
    for bid, titles in title_index.items():
        score = sum(1 for nn in normnames if nn in titles)
        if score > best:
            best, best_bid = score, bid
    return best_bid, best


def match_files(files, bid, title_index):
    """Match each file to a sermon row. Returns list of result dicts."""
    titles = title_index.get(bid, {})
    title_keys = list(titles.keys())
    used = set()  # sermon_ids already assigned
    results = []

    for fn in files:
        nn = norm(fn)
        date_in_name = parse_date_from_name(fn)
        chosen = None
        method = "none"
        score = ""

        candidates = titles.get(nn)
        if candidates:
            # filter out already-used rows
            avail = [c for c in candidates if c["sermon_id"] not in used]
            pool = avail or candidates
            if len(pool) > 1 and date_in_name:
                dated = [c for c in pool if c["date"] == date_in_name]
                if dated:
                    chosen = dated[0]
                    method = "exact+date"
            if chosen is None:
                chosen = pool[0]
                method = "exact" if method == "none" else method
            score = "1.0"
        else:
            close = difflib.get_close_matches(nn, title_keys, n=1, cutoff=0.92)
            if close:
                pool = [c for c in titles[close[0]] if c["sermon_id"] not in used] \
                    or titles[close[0]]
                chosen = pool[0]
                method = "fuzzy"
                score = f"{difflib.SequenceMatcher(None, nn, close[0]).ratio():.3f}"

        if chosen is not None:
            used.add(chosen["sermon_id"])

        results.append({
            "source_file": fn,
            "row": chosen,
            "method": method,
            "score": score,
            "date_in_name": date_in_name,
        })
    return results


def build_json(folder, bid, info, res):
    """Build the per-sermon JSON object."""
    full = os.path.join(HERE, folder)
    with open(os.path.join(full, res["source_file"]), encoding="utf-8", errors="replace") as f:
        text = f.read()

    row = res["row"]
    if row is not None:
        obj = {
            "sermon_id": row["sermon_id"],
            "broadcaster_id": bid,
            "church": row["broadcaster_name"],
            "location": row["broadcaster_location"],
            "denomination": row["broadcaster_denomination"],
            "speaker": row["speaker"],
            "date": row["date"],
            "title": row["title"],
            "series": row["series"],
            "bible_text": row["bible_text"],
            "duration_seconds": row["duration_seconds"],
            "source_file": res["source_file"],
            "match_method": res["method"],
            "match_score": res["score"],
            "text": text,
        }
        out_name = f"{row['sermon_id']}.json"
    else:
        church = folder[:-5].replace("_", " ").title() if folder.endswith("_text") else folder
        obj = {
            "sermon_id": None,
            "broadcaster_id": bid,
            "church": info["name"] if info else church,
            "location": info["location"] if info else "",
            "denomination": info["denomination"] if info else "",
            "speaker": "",
            "date": res["date_in_name"],
            "title": re.sub(r"\.txt$", "", res["source_file"]),
            "series": "",
            "bible_text": "",
            "duration_seconds": "",
            "source_file": res["source_file"],
            "match_method": res["method"],
            "match_score": res["score"],
            "text": text,
        }
        stem = re.sub(r"\.txt$", "", res["source_file"])
        out_name = f"unmatched__{stem}.json"
    return out_name, obj


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="Write report CSVs only; no JSON, no renames (default).")
    g.add_argument("--apply", action="store_true",
                   help="Write per-sermon JSON and rename folders.")
    ap.add_argument("--fuzzy-cutoff", type=float, default=0.92)
    ap.add_argument("--no-keep-txt", action="store_true",
                    help="Delete the original .txt after writing its JSON.")
    args = ap.parse_args()
    apply = args.apply
    if not apply:
        args.dry_run = True

    rows_by_bid, info_by_bid = load_csv()
    title_index = build_title_index(rows_by_bid)
    print(f"Loaded {sum(len(v) for v in rows_by_bid.values())} sermons "
          f"across {len(rows_by_bid)} broadcasters.", file=sys.stderr)

    folders = list_text_folders()
    map_rows = []
    report_rows = []
    plan = []  # (folder, bid, info, results)

    for folder in folders:
        files = folder_files(folder)
        bid, n = detect_broadcaster(files, title_index)
        rate = n / len(files) if files else 0
        if bid is None or n < MIN_MATCHES or rate < MIN_RATE:
            status, bid_use, info = "OFFLINE", None, None
            name = ""
        else:
            status, bid_use, info = "linked", bid, info_by_bid[bid]
            name = info["name"]
        map_rows.append({
            "folder": folder, "broadcaster_id": bid_use or "",
            "broadcaster_name": name, "files": len(files),
            "exact_matches": n, "status": status,
        })

        results = match_files(files, bid_use, title_index) if bid_use else \
            [{"source_file": fn, "row": None, "method": "none", "score": "",
              "date_in_name": parse_date_from_name(fn)} for fn in files]
        plan.append((folder, bid_use, info, results))

        nm = sum(1 for r in results if r["method"].startswith("exact"))
        nf = sum(1 for r in results if r["method"] == "fuzzy")
        nu = sum(1 for r in results if r["method"] == "none")
        print(f"  {folder:38s} -> {str(bid_use):16s} "
              f"files={len(files):4d} exact={nm:4d} fuzzy={nf:3d} unmatched={nu:3d} "
              f"[{status}]", file=sys.stderr)

        for r in results:
            report_rows.append({
                "folder": folder, "broadcaster_id": bid_use or "",
                "source_file": r["source_file"],
                "sermon_id": r["row"]["sermon_id"] if r["row"] else "",
                "match_method": r["method"], "match_score": r["score"],
                "date_in_name": r["date_in_name"],
            })

    # Write reports
    with open(MAP_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["folder", "broadcaster_id",
                                          "broadcaster_name", "files",
                                          "exact_matches", "status"])
        w.writeheader()
        w.writerows(map_rows)
    with open(REPORT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["folder", "broadcaster_id",
                                          "source_file", "sermon_id",
                                          "match_method", "match_score",
                                          "date_in_name"])
        w.writeheader()
        w.writerows(report_rows)
    print(f"\nWrote {MAP_PATH}", file=sys.stderr)
    print(f"Wrote {REPORT_PATH}", file=sys.stderr)

    if not apply:
        print("\nDry run complete. Review the CSVs, then re-run with --apply.",
              file=sys.stderr)
        return 0

    # Apply: write JSON, optionally drop .txt, rename folders
    n_json = 0
    for folder, bid, info, results in plan:
        full = os.path.join(HERE, folder)
        for r in results:
            out_name, obj = build_json(folder, bid, info, r)
            with open(os.path.join(full, out_name), "w", encoding="utf-8") as jf:
                json.dump(obj, jf, ensure_ascii=False, indent=2)
            n_json += 1
            if args.no_keep_txt:
                os.remove(os.path.join(full, r["source_file"]))
    print(f"\nWrote {n_json} JSON files.", file=sys.stderr)

    renamed = 0
    for folder, bid, info, results in plan:
        if not bid:
            continue
        target = f"{bid}_text"
        if folder == target:
            continue
        src = os.path.join(HERE, folder)
        dst = os.path.join(HERE, target)
        if os.path.exists(dst):
            print(f"  SKIP rename {folder} -> {target} (target exists)", file=sys.stderr)
            continue
        shutil.move(src, dst)
        print(f"  rename {folder} -> {target}", file=sys.stderr)
        renamed += 1
    print(f"Renamed {renamed} folders.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
