#!/usr/bin/env python3
"""
consolidate_json.py

Collapse the per-sermon JSON sidecars in sermons/*_text/ into ONE JSON file
per church (folder), then delete the per-sermon folders.

Each output file (sermons/<broadcaster_id>.json, or the descriptive name for
OFFLINE folders) has church-level fields hoisted to the top and a `sermons`
array of the per-sermon records (church fields removed from each).

Usage:
    python sermons/consolidate_json.py --dry-run    # report only, no writes
    python sermons/consolidate_json.py --apply       # write files + delete folders
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Per-sermon keys that are constant within a folder -> hoisted to the top level.
HOIST_KEYS = ["broadcaster_id", "church", "location", "denomination"]
# Per-sermon keys kept in the array, in order.
SERMON_KEYS = ["sermon_id", "date", "title", "speaker", "series", "bible_text",
               "duration_seconds", "source_file", "match_method", "match_score", "text"]


def text_folders():
    out = []
    for name in sorted(os.listdir(HERE)):
        full = os.path.join(HERE, name)
        if os.path.isdir(full) and name.endswith("_text"):
            out.append(name)
    return out


def load_folder(folder):
    """Read all per-sermon JSON in a folder. Returns (records, json_filenames)."""
    full = os.path.join(HERE, folder)
    names = sorted(fn for fn in os.listdir(full) if fn.endswith(".json"))
    records = []
    for fn in names:
        with open(os.path.join(full, fn), encoding="utf-8") as f:
            records.append(json.load(f))
    return records, names


def build_consolidated(folder, records):
    # Hoist church-level fields: take from the first record that has them set.
    top = {k: None for k in HOIST_KEYS}
    for rec in records:
        for k in HOIST_KEYS:
            if top[k] in (None, "") and rec.get(k) not in (None, ""):
                top[k] = rec.get(k)
    # Fallback church name from folder if none of the records carried one.
    if not top.get("church"):
        top["church"] = folder[:-5].replace("_", " ").title() if folder.endswith("_text") else folder

    sermons = []
    for rec in records:
        sermons.append({k: rec.get(k) for k in SERMON_KEYS})
    # Sort by date; empty/None dates sort last.
    sermons.sort(key=lambda s: (s.get("date") in (None, ""), s.get("date") or ""))

    obj = {**top, "source_folder": folder, "sermon_count": len(sermons), "sermons": sermons}
    return obj


def out_name(folder):
    return (folder[:-5] if folder.endswith("_text") else folder) + ".json"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="Report only; write nothing, delete nothing (default).")
    g.add_argument("--apply", action="store_true",
                   help="Write consolidated files and delete the per-sermon folders.")
    args = ap.parse_args()
    apply = args.apply

    folders = text_folders()
    if not folders:
        print("No *_text folders found.", file=sys.stderr)
        return 1

    total = 0
    plan = []
    for folder in folders:
        records, names = load_folder(folder)
        obj = build_consolidated(folder, records)
        on = out_name(folder)
        # Estimate output size (compact) for the report.
        est = len(json.dumps(obj, ensure_ascii=False))
        plan.append((folder, on, obj, len(names)))
        total += obj["sermon_count"]
        print(f"  {folder:34s} -> {on:28s} sermons={obj['sermon_count']:4d} "
              f"~{est/1_000_000:6.1f} MB  church={obj['church']!r}", file=sys.stderr)

    print(f"\nFolders: {len(folders)}  Total sermons: {total}", file=sys.stderr)

    if not apply:
        print("\nDry run complete. Re-run with --apply to write files and delete folders.",
              file=sys.stderr)
        return 0

    # Write all consolidated files first (verify counts), then delete folders.
    for folder, on, obj, n_json in plan:
        if obj["sermon_count"] != n_json:
            print(f"  ABORT: {folder} count mismatch "
                  f"({obj['sermon_count']} != {n_json} json files)", file=sys.stderr)
            return 1
        with open(os.path.join(HERE, on), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(plan)} consolidated JSON files.", file=sys.stderr)

    removed = 0
    for folder, on, obj, n_json in plan:
        shutil.rmtree(os.path.join(HERE, folder))
        removed += 1
    print(f"Deleted {removed} *_text folders.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
