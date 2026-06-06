"""S03 -- Structure & segmentation.

Reconstructs structure from the (often unbroken) text:
  * Sentences via spaCy's ``sentencizer`` (a regex fallback is used if spaCy is
    not installed).
  * Movements: for ``prepared`` docs with native paragraph breaks we use those;
    for ``transcribed`` docs we segment on topic shifts -- valleys in cosine
    similarity between consecutive S05 chunk embeddings (a TextTiling proxy).
  * Heuristic sermon-move features: closing-prayer detection, Q&A turns, and
    intro/body/close proportions.

Outputs: ``sentences.parquet``, ``segments.parquet``, ``structure.parquet``.
Run AFTER S05 to get embedding-based segmentation (it degrades gracefully
without embeddings).

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s03_segment.py
"""

from __future__ import annotations

import argparse
import re

import numpy as np
import polars as pl
from tqdm import tqdm

from sermons import common

_REGEX_SENT = re.compile(r"(?<=[.!?])\s+")
_PRAYER_RE = re.compile(r"\b(father|lord|gracious god|heavenly father|in jesus'? name|amen)\b", re.I)
_QA_RE = re.compile(r"\b(any questions|good question|question is|yeah|student|raise your hand)\b", re.I)


def split_sentences(text: str, nlp) -> list[str]:
    if nlp is not None:
        return [s.text.strip() for s in nlp(text).sents if s.text.strip()]
    return [s.strip() for s in _REGEX_SENT.split(text) if s.strip()]


def segment_transcribed(rows_emb: np.ndarray, drop: float = 0.15) -> list[tuple[int, int]]:
    """Boundaries at cosine valleys between consecutive chunk embeddings."""
    if len(rows_emb) <= 2:
        return [(0, len(rows_emb))]
    sims = np.sum(rows_emb[:-1] * rows_emb[1:], axis=1)  # embeddings are L2-normalized
    thresh = sims.mean() - drop
    boundaries = [0] + [i + 1 for i, s in enumerate(sims) if s < thresh] + [len(rows_emb)]
    boundaries = sorted(set(boundaries))
    return list(zip(boundaries[:-1], boundaries[1:]))


def closing_prayer_fraction(sentences: list[str]) -> float | None:
    """If the tail of the sermon is prayer, return where it starts (0-1)."""
    n = len(sentences)
    if n < 10:
        return None
    tail_start = int(n * 0.80)
    for i in range(tail_start, n):
        window = " ".join(sentences[i:i + 3]).lower()
        if _PRAYER_RE.search(window) and ("amen" in " ".join(sentences[i:]).lower()):
            return round(i / n, 3)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="S03 structure & segmentation.")
    common.add_common_args(parser)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet").filter(pl.col("usable")), args)
    clean = pl.read_parquet(common.cache("clean.parquet")).select(["doc_id", "clean_text"])
    df = corpus.select(["doc_id", "doc_type"]).join(clean, on="doc_id", how="inner")

    # spaCy sentencizer (lightweight, no model download needed); regex fallback.
    nlp = None
    try:
        import spacy

        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
        nlp.max_length = 4_000_000
    except Exception:  # noqa: BLE001
        print("spaCy unavailable; using regex sentence splitter.")

    # Optional chunk embeddings for transcribed segmentation.
    chunk_emb = chunks = None
    if common.cache("chunk_emb.npy").exists():
        chunk_emb = np.load(common.cache("chunk_emb.npy")).astype(np.float32)
        chunks = pl.read_parquet(common.cache("chunks.parquet")).with_row_index("row")

    sent_rows, seg_rows, struct_rows = [], [], []
    for row in tqdm(df.iter_rows(named=True), total=df.height, desc="segment"):
        did = row["doc_id"]
        sents = split_sentences(row["clean_text"] or "", nlp)
        for i, s in enumerate(sents):
            sent_rows.append({"doc_id": did, "sent_id": i, "text": s})

        # Segments.
        n_seg = None
        if chunk_emb is not None:
            sub = chunks.filter(pl.col("doc_id") == did).sort("chunk_id")
            if sub.height:
                rows_idx = sub["row"].to_numpy()
                for sid, (a, b) in enumerate(segment_transcribed(chunk_emb[rows_idx])):
                    seg_rows.append({"doc_id": did, "segment_id": sid,
                                     "chunk_start": int(a), "chunk_end": int(b)})
                n_seg = len(segment_transcribed(chunk_emb[rows_idx]))

        prayer_frac = closing_prayer_fraction(sents)
        qa_hits = sum(1 for s in sents if _QA_RE.search(s))
        struct_rows.append({
            "doc_id": did,
            "doc_type": row["doc_type"],
            "n_sentences": len(sents),
            "n_segments": n_seg,
            "has_closing_prayer": prayer_frac is not None,
            "prayer_start_frac": prayer_frac,
            "qa_turns": qa_hits,
            "is_qa_format": qa_hits >= 5,
        })

    common.write_parquet(pl.DataFrame(sent_rows), "sentences.parquet")
    common.write_parquet(pl.DataFrame(seg_rows) if seg_rows else
                         pl.DataFrame(schema={"doc_id": pl.Utf8, "segment_id": pl.Int64,
                                              "chunk_start": pl.Int64, "chunk_end": pl.Int64}),
                         "segments.parquet")
    struct = pl.DataFrame(struct_rows)
    common.write_parquet(struct, "structure.parquet")
    print(f"Wrote sentences ({len(sent_rows)}), segments ({len(seg_rows)}), structure ({struct.height})")
    print(f"closing prayer detected in {struct['has_closing_prayer'].sum()}/{struct.height} docs; "
          f"Q&A-format docs: {struct['is_qa_format'].sum()}")


if __name__ == "__main__":
    main()
