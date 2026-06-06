"""S05 -- Embeddings (chunk + document level).

Embeds ``clean_text`` with a sentence-transformer on Apple-Silicon MPS (falls
back to CUDA/CPU).  Long sermons are split into overlapping word-chunks
(~320 words) so each embedding stays within the model's context; a mean-pooled
document embedding is also stored.  Computed once and reused by S03
(segmentation), S06 (topics), and semantic search.

Outputs (gitignored, in cache/):
  * ``chunks.parquet``   -- doc_id, chunk_id, word_start, word_end, chunk_text
  * ``chunk_emb.npy``    -- float16 matrix aligned row-for-row with chunks.parquet
  * ``doc_emb.parquet``  -- doc_id + mean-pooled embedding (list[f32])

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s05_embed.py
    uv run --group analysis python analysis/sermons/src/sermons/s05_embed.py --model nomic-embed-text
"""

from __future__ import annotations

import argparse

import numpy as np
import polars as pl
from tqdm import tqdm

from sermons import common

CHUNK_WORDS = 320
OVERLAP_WORDS = 64
DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"


def pick_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def chunk_words(text: str) -> list[tuple[int, int, str]]:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = CHUNK_WORDS - OVERLAP_WORDS
    for start in range(0, len(words), step):
        end = min(start + CHUNK_WORDS, len(words))
        chunks.append((start, end, " ".join(words[start:end])))
        if end == len(words):
            break
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="S05 compute chunk + doc embeddings.")
    common.add_common_args(parser)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="sentence-transformers model id")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet").filter(pl.col("usable")), args)
    clean = pl.read_parquet(common.cache("clean.parquet")).select(["doc_id", "clean_text"])
    df = corpus.select(["doc_id"]).join(clean, on="doc_id", how="inner")

    # Build chunk table.
    chunk_rows = []
    for row in tqdm(df.iter_rows(named=True), total=df.height, desc="chunking"):
        for i, (ws, we, ctext) in enumerate(chunk_words(row["clean_text"] or "")):
            chunk_rows.append({"doc_id": row["doc_id"], "chunk_id": i,
                               "word_start": ws, "word_end": we, "chunk_text": ctext})
    chunks = pl.DataFrame(chunk_rows)
    print(f"{chunks.height} chunks from {df.height} documents")

    from sentence_transformers import SentenceTransformer

    device = pick_device()
    print(f"Embedding on device={device} with model={args.model}")
    model = SentenceTransformer(args.model, device=device)
    texts = chunks["chunk_text"].to_list()
    emb = model.encode(texts, batch_size=args.batch_size, show_progress_bar=True,
                       normalize_embeddings=True).astype(np.float16)

    common.write_parquet(chunks, "cache/chunks.parquet")
    np.save(common.cache("chunk_emb.npy"), emb)

    # Mean-pool per document.
    idx = chunks.with_row_index("row")
    doc_vecs = []
    for did, grp in idx.group_by("doc_id"):
        rows = grp["row"].to_numpy()
        v = emb[rows].astype(np.float32).mean(axis=0)
        n = np.linalg.norm(v)
        doc_vecs.append({"doc_id": did[0] if isinstance(did, tuple) else did,
                         "embedding": (v / n if n else v).tolist()})
    pl.DataFrame(doc_vecs).write_parquet(common.cache("doc_emb.parquet"))
    print(f"Wrote chunk_emb.npy {emb.shape}, doc_emb.parquet {len(doc_vecs)} docs")


if __name__ == "__main__":
    main()
