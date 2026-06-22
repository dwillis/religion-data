"""Y00 -- Fetch YouTube service metadata (chapters / description / date).

Many congregations publish their *entire* worship service on YouTube.  The
sermon-isolation cascade (y02) gets a big precision boost from YouTube
**chapters** and description timestamps -- but importing a URL straight into a
transcription tool (e.g. MacWhisper) discards that metadata.  This stage uses
``yt-dlp`` in *metadata-only* mode (no audio download) to capture each video's
``info.json`` so y02 can read its chapters, upload date, title, and description.

Output: ``data/youtube_services/<congregation>/meta/<video_id>.info.json`` and a
printed summary.  Cheap, network-only; audio/transcription happen out-of-band.

Usage:
    uv run --group youtube python analysis/sermons/src/sermons/y00_fetch.py \
        --congregation grace_bible_text https://youtu.be/VIDEOID

    # A whole channel/playlist (yt-dlp enumerates it):
    uv run --group youtube python analysis/sermons/src/sermons/y00_fetch.py \
        --congregation grace_bible_text --max 25 \
        https://www.youtube.com/@SomeChurch/streams

    # From a file of URLs (one per line):
    uv run --group youtube python analysis/sermons/src/sermons/y00_fetch.py \
        --congregation grace_bible_text --urls-file urls.txt
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from sermons import common

SERVICES_DIR = common.REPO_ROOT / "data" / "youtube_services"


def meta_dir(congregation: str):
    d = SERVICES_DIR / congregation / "meta"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_url(url: str, max_videos: int | None) -> list[dict]:
    """Return a list of info dicts for a URL (one per video; playlists expand)."""
    cmd = ["yt-dlp", "--skip-download", "--dump-json", "--ignore-errors"]
    if max_videos:
        cmd += ["--playlist-items", f"1-{max_videos}"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 and not proc.stdout.strip():
        print(f"  ! yt-dlp failed for {url}:\n{proc.stderr.strip()[:500]}", file=sys.stderr)
        return []
    infos = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            infos.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return infos


def summarize(info: dict) -> dict:
    chapters = info.get("chapters") or []
    return {
        "video_id": info.get("id", ""),
        "title": info.get("title", ""),
        "upload_date": info.get("upload_date", ""),  # YYYYMMDD
        "duration": info.get("duration"),
        "n_chapters": len(chapters),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Y00 fetch YouTube service metadata (no audio).")
    parser.add_argument("urls", nargs="*", help="Video / playlist / channel URLs")
    parser.add_argument("--congregation", required=True,
                        help="congregation_dir these videos belong to (e.g. grace_bible_text)")
    parser.add_argument("--urls-file", help="File with one URL per line")
    parser.add_argument("--max", type=int, default=None, help="Cap videos per playlist/channel URL")
    args = parser.parse_args()

    if not shutil.which("yt-dlp"):
        raise SystemExit("yt-dlp not found. Install it: `uv sync --group youtube` (or `pipx install yt-dlp`).")

    urls = list(args.urls)
    if args.urls_file:
        with open(args.urls_file) as f:
            urls += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not urls:
        parser.error("Provide at least one URL or --urls-file")

    mdir = meta_dir(args.congregation)
    written = 0
    for url in urls:
        print(f"[+] {url}")
        for info in fetch_url(url, args.max):
            vid = info.get("id")
            if not vid:
                continue
            (mdir / f"{vid}.info.json").write_text(json.dumps(info), encoding="utf-8")
            s = summarize(info)
            written += 1
            print(f"    {s['video_id']}  {s['upload_date']}  chapters={s['n_chapters']}  {s['title'][:60]}")

    print(f"\nWrote {written} info.json files -> {mdir}")
    if written:
        print("Next: drop the matching MacWhisper transcript exports in "
              f"{SERVICES_DIR / args.congregation / 'transcripts'} and run y01_parse.py.")


if __name__ == "__main__":
    main()
