"""Y01 -- Parse MacWhisper transcript exports into normalized segments.

Transcription happens out-of-band in MacWhisper; this stage ingests its exports
(``.srt`` / ``.vtt`` / ``.json``) and normalizes them to timestamped segments
``{seg_id, start, end, text, speaker?}`` that y02 can score.  Speaker labels are
parsed when present (MacWhisper Pro diarization) but never required.

Each transcript is paired with a YouTube ``video_id`` when one can be recovered
from the filename (yt-dlp's default ``"Title [VIDEOID]"`` naming) so y02 can pull
the matching ``info.json`` chapters fetched by y00.

Input dir : ``data/youtube_services/<congregation>/transcripts/*.{srt,vtt,json}``
Output    : ``cache/services/<congregation>/<service_id>.segments.parquet`` and
            ``cache/services/<congregation>/index.parquet``

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/y01_parse.py \
        --congregation grace_bible_text
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import polars as pl

from sermons import common

SERVICES_DIR = common.REPO_ROOT / "data" / "youtube_services"

# yt-dlp default names files "Title [VIDEOID].ext"; recover the 11-char id.
_VIDEO_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
# SRT/VTT timestamp: HH:MM:SS,mmm or HH:MM:SS.mmm
_TS_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")
_CUE_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})")
# VTT inline speaker tag: <v Speaker Name>text</v>
_VTT_SPEAKER_RE = re.compile(r"<v\s+([^>]+)>(.*?)(?:</v>)?$", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _ts_to_seconds(ts: str) -> float:
    m = _TS_RE.search(ts)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt_vtt(text: str) -> list[dict]:
    """Parse SRT or VTT into segments. Blocks are separated by blank lines."""
    segs: list[dict] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].strip().upper().startswith("WEBVTT"):
            continue
        cue = next((ln for ln in lines if _CUE_RE.search(ln)), None)
        if not cue:
            continue
        m = _CUE_RE.search(cue)
        start, end = _ts_to_seconds(m.group(1)), _ts_to_seconds(m.group(2))
        cue_idx = lines.index(cue)
        body_lines = lines[cue_idx + 1:]
        body = " ".join(body_lines).strip()
        speaker = None
        sm = _VTT_SPEAKER_RE.search(body)
        if sm:
            speaker, body = sm.group(1).strip(), sm.group(2).strip()
        body = _TAG_RE.sub("", body).strip()
        if body:
            segs.append({"start": start, "end": end, "text": body, "speaker": speaker})
    return segs


def parse_json(text: str) -> list[dict]:
    """Parse MacWhisper / Whisper JSON. Handles a few common shapes."""
    data = json.loads(text)
    if isinstance(data, dict):
        rows = data.get("segments") or data.get("transcription") or data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    segs = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        start = r.get("start", r.get("startTime", r.get("from")))
        end = r.get("end", r.get("endTime", r.get("to")))
        body = (r.get("text") or r.get("transcript") or "").strip()
        if body and start is not None:
            segs.append({"start": float(start), "end": float(end or start),
                         "text": _TAG_RE.sub("", body).strip(),
                         "speaker": r.get("speaker")})
    return segs


def parse_transcript(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            return parse_json(text)
        except json.JSONDecodeError:
            return []
    return parse_srt_vtt(text)


def guess_video_id(stem: str) -> str | None:
    m = _VIDEO_ID_RE.search(stem)
    return m.group(1) if m else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Y01 parse MacWhisper transcripts to segments.")
    parser.add_argument("--congregation", required=True, help="congregation_dir")
    args = parser.parse_args()

    tdir = SERVICES_DIR / args.congregation / "transcripts"
    if not tdir.exists():
        raise SystemExit(f"No transcripts dir: {tdir}\nCreate it and add MacWhisper .srt/.vtt/.json exports.")

    out_dir = common.cache("services") / args.congregation
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in tdir.iterdir() if p.suffix.lower() in {".srt", ".vtt", ".json"})
    if not files:
        raise SystemExit(f"No .srt/.vtt/.json files in {tdir}")

    index_rows = []
    for path in files:
        service_id = path.stem
        segs = parse_transcript(path)
        if not segs:
            print(f"  ! no segments parsed from {path.name}; skipping")
            continue
        df = pl.DataFrame(
            [{"seg_id": i, **s} for i, s in enumerate(segs)],
            schema={"seg_id": pl.Int64, "start": pl.Float64, "end": pl.Float64,
                    "text": pl.Utf8, "speaker": pl.Utf8},
        )
        df.write_parquet(out_dir / f"{service_id}.segments.parquet")
        has_speaker = df["speaker"].drop_nulls().n_unique() > 1
        index_rows.append({
            "service_id": service_id,
            "congregation_dir": args.congregation,
            "video_id": guess_video_id(service_id),
            "transcript_path": common.rel_path(path),
            "n_segments": df.height,
            "duration": float(df["end"].max() or 0.0),
            "has_speaker": has_speaker,
        })
        print(f"  {service_id}: {df.height} segments, {index_rows[-1]['duration']/60:.1f} min"
              f"{', diarized' if has_speaker else ''}"
              f"{', video='+index_rows[-1]['video_id'] if index_rows[-1]['video_id'] else ''}")

    if not index_rows:
        raise SystemExit("No transcripts produced segments.")
    index = pl.DataFrame(index_rows)
    index.write_parquet(out_dir / "index.parquet")
    print(f"\nWrote {index.height} parsed transcripts -> {out_dir}")
    print("Next: run y02_isolate.py --congregation " + args.congregation)


if __name__ == "__main__":
    main()
