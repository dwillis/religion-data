"""Pipeline orchestrator.

Runs the stages in dependency order.  Each stage is resumable, so re-running the
whole pipeline after adding sermons only processes what changed.

    uv run --group analysis python analysis/sermons/src/sermons/run.py            # full pipeline
    uv run --group analysis python analysis/sermons/src/sermons/run.py --light    # skip ML stages
    uv run --group analysis python analysis/sermons/src/sermons/run.py --from s05 # resume at a stage
    uv run --group analysis python analysis/sermons/src/sermons/run.py --only s04 --congregation hopebible_text

Dependency order:
    s00 ingest -> s01 index -> s02 clean -> s04 scripture
                                          -> s05 embed -> s06 topics
                                                       -> s03 segment
    s07 ner, s08 style, s09 rhetoric  (need s01/s02)
    s10 report  (consumes everything available)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

STAGES = ["s00_ingest", "s01_index", "s02_clean", "s04_scripture", "s05_embed",
          "s06_topics", "s03_segment", "s07_ner", "s08_style", "s09_rhetoric", "s10_report"]
LIGHT = {"s00_ingest", "s01_index", "s02_clean", "s04_scripture", "s08_style", "s09_rhetoric", "s10_report"}
HERE = Path(__file__).resolve().parent


def stage_name(token: str) -> str:
    for s in STAGES:
        if s == token or s.startswith(token) or s.split("_")[0] == token:
            return s
    raise SystemExit(f"Unknown stage '{token}'. Known: {', '.join(STAGES)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sermon-analysis pipeline.")
    parser.add_argument("--from", dest="start", default=None, help="resume at this stage (e.g. s05)")
    parser.add_argument("--only", default=None, help="run a single stage")
    parser.add_argument("--light", action="store_true", help="skip ML stages (embed/topics/ner/segment)")
    parser.add_argument("--congregation", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args, passthrough = parser.parse_known_args()

    if args.only:
        stages = [stage_name(args.only)]
    else:
        stages = STAGES
        if args.start:
            start = stage_name(args.start)
            stages = stages[stages.index(start):]
        if args.light:
            stages = [s for s in stages if s in LIGHT]

    common_args = []
    if args.congregation:
        common_args += ["--congregation", args.congregation]
    if args.limit:
        common_args += ["--limit", str(args.limit)]

    for stage in stages:
        # s10/s06 don't accept --limit/--congregation; pass only to stages that take them.
        extra = common_args if stage not in {"s06_topics", "s10_report"} else []
        cmd = [sys.executable, str(HERE / f"{stage}.py"), *extra, *passthrough]
        print(f"\n=== {stage} ===\n$ {' '.join(cmd)}")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise SystemExit(f"Stage {stage} failed (exit {result.returncode}).")


if __name__ == "__main__":
    main()
