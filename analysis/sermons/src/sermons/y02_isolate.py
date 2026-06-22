"""Y02 -- Isolate the sermon from a full-service transcript (the cascade).

For each parsed service transcript (y01) this finds the sermon span using a
cascade of independent signals, cheapest-and-most-precise first, and **proposes**
boundaries for human review (it never writes into ``sermons/`` -- that's y03):

  1. YouTube **chapters / description timestamps** from the y00 ``info.json`` --
     free and high-precision when the church marks the sermon.
  2. **Transcript scoring** (primary path): split the timeline into blocks at
     liturgical markers, large time gaps (music/silence), and song-lyric
     repetition runs, then pick the block that maximises
     ``duration x (scripture + homiletic density) x (1 - lyric_fraction)``.
     Reuses ``s04_scripture.build_matcher`` and ``s03_segment`` cues.
  3. **Speaker labels** corroborate when the MacWhisper export is diarized.
  4. **Ollama refinement** (``--llm``) only when 1-3 are weak/uncertain.

Outputs (under ``data/youtube_services/<congregation>/``):
  * ``isolated/<service_id>.sermon.txt`` and ``.full.txt``
  * ``service_manifest.parquet`` (canonical) and ``service_review.csv`` (edit the
    ``confirmed`` column / adjust ``sermon_start``/``sermon_end``, then run y03).

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/y02_isolate.py \
        --congregation grace_bible_text [--llm]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import polars as pl
import yaml

from sermons import common, s03_segment, s04_scripture

SERVICES_DIR = common.REPO_ROOT / "data" / "youtube_services"
MARKERS_YAML = common.CONFIG_DIR / "service_markers.yaml"

GAP_BOUNDARY_S = 25.0       # inter-segment silence/music gap that splits blocks
MIN_SERMON_MIN = 5.0        # blocks shorter than this can't be the sermon
MIN_LYRIC_RUN = 3           # consecutive lyric segments before it counts as singing
LLM_CONF_FLOOR = 0.6        # below this, --llm tries to refine

_SERMON_KW_RE = re.compile(r"\b(sermon|message|preach|homily|teaching|the word|exposition)\b", re.I)
_DESC_TS_RE = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})")


def load_markers() -> tuple[list[str], list[str], dict]:
    data = yaml.safe_load(MARKERS_YAML.read_text(encoding="utf-8"))
    return (
        [m.lower() for m in data.get("homiletic_markers", [])],
        [m.lower() for m in data.get("liturgical_markers", [])],
        data.get("lyric_repetition", {"window_segments": 12, "min_repeat_ratio": 0.45}),
    )


def _count_markers(text_lower: str, markers: list[str]) -> int:
    return sum(text_lower.count(m) for m in markers)


def _ts_to_seconds(s: str) -> float | None:
    m = _DESC_TS_RE.search(s)
    if not m:
        return None
    h, mi, sec = m.groups()
    return (int(h) if h else 0) * 3600 + int(mi) * 60 + int(sec)


# --- Signal 1: YouTube chapters / description -----------------------------

def from_chapters(info: dict, matcher) -> dict | None:
    chapters = info.get("chapters") or []
    if chapters:
        best, best_score, kw_match = None, -1.0, False
        for ch in chapters:
            start, end = ch.get("start_time"), ch.get("end_time")
            if start is None or end is None:
                continue
            title = ch.get("title", "")
            dur = end - start
            has_kw = bool(_SERMON_KW_RE.search(title))
            has_scrip = len(s04_scripture.extract(title, *matcher)) > 0
            score = dur * (2.0 if has_kw else 1.0) * (1.5 if has_scrip else 1.0)
            if score > best_score:
                best, best_score, kw_match = (start, end, title, has_kw, has_scrip), score, has_kw
        if best:
            start, end, title, has_kw, has_scrip = best
            conf = 0.9 if has_kw else (0.75 if has_scrip else 0.6)
            return {"sermon_start": float(start), "sermon_end": float(end),
                    "method": "chapter", "confidence": conf, "note": f"chapter: {title[:60]}"}

    # Description timestamp lines, e.g. "Sermon 32:15" / "32:15 - Message".
    desc = info.get("description") or ""
    marks = []
    for line in desc.splitlines():
        ts = _ts_to_seconds(line)
        if ts is not None:
            marks.append((ts, line.strip(), bool(_SERMON_KW_RE.search(line))))
    marks.sort()
    for i, (ts, line, is_sermon) in enumerate(marks):
        if is_sermon:
            end = marks[i + 1][0] if i + 1 < len(marks) else (info.get("duration") or ts + 1800)
            return {"sermon_start": float(ts), "sermon_end": float(end),
                    "method": "chapter", "confidence": 0.8, "note": f"description: {line[:60]}"}
    return None


# --- Signal 2: transcript block scoring -----------------------------------

def mark_lyrics(texts: list[str], window: int, min_ratio: float) -> list[bool]:
    """Flag segments inside high-repetition windows (singing)."""
    n = len(texts)
    norm = [re.sub(r"\s+", " ", t.lower().strip()) for t in texts]
    flags = [False] * n
    half = max(window // 2, 1)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        win = [w for w in norm[lo:hi] if w]
        if len(win) < 4:
            continue
        repeat_ratio = 1.0 - len(set(win)) / len(win)
        if repeat_ratio >= min_ratio:
            flags[i] = True
    return flags


def from_transcript(segs: pl.DataFrame, homiletic, liturgical, lyric_cfg, matcher) -> dict:
    starts = segs["start"].to_list()
    ends = segs["end"].to_list()
    texts = segs["text"].to_list()
    n = len(texts)
    lower = [t.lower() for t in texts]

    lyric = mark_lyrics(texts, lyric_cfg["window_segments"], lyric_cfg["min_repeat_ratio"])
    homi = [_count_markers(t, homiletic) for t in lower]
    litu = [_count_markers(t, liturgical) for t in lower]
    scrip = [len(s04_scripture.extract(t, *matcher)) for t in texts]

    # Sustained singing only: a lyric segment is a boundary when it's part of a
    # run of >= MIN_LYRIC_RUN consecutive lyric segments (an isolated repeated
    # refrain inside the sermon must not fragment it).
    lyric_boundary = [False] * n
    i = 0
    while i < n:
        if lyric[i]:
            j = i
            while j < n and lyric[j]:
                j += 1
            if j - i >= MIN_LYRIC_RUN:
                for k in range(i, j):
                    lyric_boundary[k] = True
            i = j
        else:
            i += 1

    # Boundaries: liturgical-marker segments, big time gaps, sustained singing.
    boundary = [False] * n
    for i in range(n):
        if litu[i] > 0 or lyric_boundary[i]:
            boundary[i] = True
        if i > 0 and (starts[i] - ends[i - 1]) > GAP_BOUNDARY_S:
            boundary[i] = True

    # Build contiguous blocks of non-boundary segments.
    blocks, cur = [], []
    for i in range(n):
        if boundary[i]:
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(i)
    if cur:
        blocks.append(cur)

    if not blocks:
        return {"sermon_start": float(starts[0]), "sermon_end": float(ends[-1]),
                "method": "heuristic", "confidence": 0.2, "note": "no clear blocks"}

    scored = []
    for blk in blocks:
        dur = ends[blk[-1]] - starts[blk[0]]
        nb = len(blk)
        s_hits = sum(scrip[i] for i in blk)
        h_hits = sum(homi[i] for i in blk)
        lyric_frac = sum(1 for i in blk if lyric[i]) / nb
        density = (s_hits + h_hits) / nb
        score = dur * (1.0 + 0.5 * density) * (1.0 - lyric_frac)
        scored.append({"blk": blk, "dur": dur, "score": score,
                       "s_hits": s_hits, "h_hits": h_hits})
    scored.sort(key=lambda d: d["score"], reverse=True)
    best = scored[0]
    blk = best["blk"]

    durs = sorted((b["dur"] for b in scored), reverse=True)
    second = durs[1] if len(durs) > 1 else 0.0
    conf = 0.5
    if best["s_hits"] >= 3:
        conf += 0.2
    if best["h_hits"] >= 2:
        conf += 0.15
    if second == 0.0 or best["dur"] >= 2 * second:
        conf += 0.15
    if best["dur"] < MIN_SERMON_MIN * 60:
        conf = min(conf, 0.35)
    conf = round(min(conf, 1.0), 3)

    return {"sermon_start": float(starts[blk[0]]), "sermon_end": float(ends[blk[-1]]),
            "method": "heuristic", "confidence": conf,
            "note": f"block {best['dur']/60:.1f}min, scrip={best['s_hits']}, homi={best['h_hits']}"}


# --- Signal 4: Ollama refinement ------------------------------------------

def downsample(segs: pl.DataFrame, step_s: float = 30.0) -> str:
    lines, next_t = [], 0.0
    for row in segs.iter_rows(named=True):
        if row["start"] >= next_t:
            mm, ss = divmod(int(row["start"]), 60)
            lines.append(f"[{mm:02d}:{ss:02d} | {int(row['start'])}s] {row['text'][:160]}")
            next_t = row["start"] + step_s
    return "\n".join(lines)


def from_llm(segs: pl.DataFrame, model: str) -> dict | None:
    from sermons import llm
    if not llm.is_available():
        print("    (ollama unavailable; skipping LLM refinement)")
        return None
    schema = {"type": "object", "properties": {
        "sermon_start": {"type": "number"}, "sermon_end": {"type": "number"},
        "confidence": {"type": "number"}, "reason": {"type": "string"}},
        "required": ["sermon_start", "sermon_end", "confidence"]}
    prompt = llm.load_prompt("sermon_boundary.txt").format(transcript=downsample(segs))
    data = llm.generate_json(prompt, model=model, schema=schema)
    if data.get("_parse_error") or "sermon_start" not in data:
        return None
    return {"sermon_start": float(data["sermon_start"]), "sermon_end": float(data["sermon_end"]),
            "method": "llm", "confidence": round(float(data.get("confidence", 0.5)), 3),
            "note": str(data.get("reason", ""))[:80]}


# --- assembly -------------------------------------------------------------

def cut_text(segs: pl.DataFrame, start: float, end: float) -> str:
    sub = segs.filter((pl.col("end") > start) & (pl.col("start") < end))
    joined = " ".join(t.strip() for t in sub["text"].to_list() if t.strip())
    return re.sub(r"\s+", " ", joined).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Y02 isolate sermon from service transcript.")
    parser.add_argument("--congregation", required=True)
    parser.add_argument("--llm", action="store_true", help="use Ollama to refine weak boundaries")
    parser.add_argument("--llm-model", default="llama3.1:8b")
    args = parser.parse_args()

    svc_dir = common.cache("services") / args.congregation
    index_path = svc_dir / "index.parquet"
    if not index_path.exists():
        raise SystemExit(f"No parsed transcripts: {index_path}. Run y01_parse.py first.")
    index = pl.read_parquet(index_path)

    homiletic, liturgical, lyric_cfg = load_markers()
    matcher = s04_scripture.build_matcher()
    meta_dir = SERVICES_DIR / args.congregation / "meta"
    iso_dir = SERVICES_DIR / args.congregation / "isolated"
    iso_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for rec in index.iter_rows(named=True):
        sid = rec["service_id"]
        # glob=False: service_id may contain [brackets] (yt-dlp video-id naming).
        segs = pl.read_parquet(svc_dir / f"{sid}.segments.parquet", glob=False)

        info = {}
        if rec["video_id"]:
            ip = meta_dir / f"{rec['video_id']}.info.json"
            if ip.exists():
                info = json.loads(ip.read_text(encoding="utf-8"))

        # Cascade.
        result = from_chapters(info, matcher) if info else None
        if result is None:
            result = from_transcript(segs, homiletic, liturgical, lyric_cfg, matcher)
        if args.llm and result["confidence"] < LLM_CONF_FLOOR:
            refined = from_llm(segs, args.llm_model)
            if refined:
                result = refined

        start, end = result["sermon_start"], result["sermon_end"]
        sermon_text = cut_text(segs, start, end)
        full_text = cut_text(segs, 0.0, float(segs["end"].max() or end))
        (iso_dir / f"{sid}.sermon.txt").write_text(sermon_text, encoding="utf-8")
        (iso_dir / f"{sid}.full.txt").write_text(full_text, encoding="utf-8")

        sents = s03_segment.split_sentences(sermon_text, None)
        rows.append({
            "service_id": sid,
            "congregation_dir": args.congregation,
            "video_id": rec["video_id"] or "",
            "title": info.get("title", sid),
            "upload_date": info.get("upload_date", ""),
            "method": result["method"],
            "confidence": result["confidence"],
            "sermon_start": round(start, 1),
            "sermon_end": round(end, 1),
            "sermon_minutes": round((end - start) / 60, 1),
            "n_words_sermon": len(sermon_text.split()),
            "n_words_full": len(full_text.split()),
            "has_closing_prayer": s03_segment.closing_prayer_fraction(sents) is not None,
            "note": result.get("note", ""),
            "transcript_path": rec["transcript_path"],
            "sermon_txt_path": common.rel_path(iso_dir / f"{sid}.sermon.txt"),
            "full_txt_path": common.rel_path(iso_dir / f"{sid}.full.txt"),
        })
        print(f"  {sid}: {result['method']} conf={result['confidence']} "
              f"{rows[-1]['sermon_minutes']}min ({rows[-1]['n_words_sermon']}w)  {result.get('note','')}")

    manifest = pl.DataFrame(rows)
    manifest.write_parquet(SERVICES_DIR / args.congregation / "service_manifest.parquet")

    # Editable review file: set confirmed=yes (and optionally adjust start/end), then run y03.
    review = manifest.select([
        "service_id", "congregation_dir", "title", "upload_date", "method", "confidence",
        "sermon_start", "sermon_end", "sermon_minutes", "n_words_sermon", "note",
    ]).with_columns(pl.lit("").alias("confirmed"))
    review_path = SERVICES_DIR / args.congregation / "service_review.csv"
    review.write_csv(review_path)

    print(f"\nWrote {manifest.height} proposals -> {SERVICES_DIR / args.congregation}")
    print(f"Review/adjust {review_path} (set confirmed=yes), then run y03_promote.py.")
    lowc = manifest.filter(pl.col("confidence") < LLM_CONF_FLOOR).height
    if lowc:
        print(f"  ⚠ {lowc} low-confidence proposal(s) -- check these closely"
              + ("" if args.llm else "; re-run with --llm to refine."))


if __name__ == "__main__":
    main()
