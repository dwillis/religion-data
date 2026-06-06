"""Shared helpers for the sermon-analysis pipeline.

Every stage reads and writes Parquet keyed by ``doc_id`` under
``data/sermons_analysis/``.  Stages are *resumable*: a stage records the input
content hash for each document, and on re-run only reprocesses documents whose
input changed (or that are new).  Heavy third-party deps (torch, spaCy,
BERTopic, gliner, ollama) are imported lazily inside the stages that need them
so the lightweight stages run with only polars/duckdb/pyarrow installed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl

# --- Paths -----------------------------------------------------------------

# repo_root/analysis/sermons/src/sermons/common.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[4]
SERMONS_DIR = REPO_ROOT / "sermons"
PKG_DIR = Path(__file__).resolve().parents[1]  # analysis/sermons/src
CONFIG_DIR = REPO_ROOT / "analysis" / "sermons" / "config"
PROMPTS_DIR = REPO_ROOT / "analysis" / "sermons" / "prompts"
OUT_DIR = REPO_ROOT / "data" / "sermons_analysis"
CACHE_DIR = OUT_DIR / "cache"  # large, gitignored intermediates (normalized text, embeddings)

for _d in (OUT_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def out(name: str) -> Path:
    """Path to a pipeline output table/artifact under data/sermons_analysis/."""
    return OUT_DIR / name


def cache(name: str) -> Path:
    """Path to a gitignored cache artifact (embeddings, normalized text)."""
    return CACHE_DIR / name


# --- Identity & hashing ----------------------------------------------------


def doc_id_for(path: Path | str) -> str:
    """Deterministic 16-hex-char id derived from the path relative to the repo.

    Stable across machines because it is computed from the repo-relative POSIX
    path, not the absolute path.
    """
    p = Path(path)
    try:
        rel = p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = p.as_posix()
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def rel_path(path: Path | str) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


# --- Parquet I/O & resumability -------------------------------------------


def read_parquet(name: str) -> pl.DataFrame | None:
    p = out(name)
    if p.exists():
        return pl.read_parquet(p)
    return None


def write_parquet(df: pl.DataFrame, name: str) -> Path:
    p = out(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    return p


def require(name: str) -> pl.DataFrame:
    """Load a prerequisite stage output or fail with a helpful message."""
    df = read_parquet(name)
    if df is None:
        raise SystemExit(
            f"Missing prerequisite '{name}' under {OUT_DIR}. "
            f"Run the earlier stage that produces it first."
        )
    return df


def select_pending(corpus: pl.DataFrame, prior: pl.DataFrame | None, hash_col: str = "content_sha") -> pl.DataFrame:
    """Return rows of ``corpus`` not yet processed in ``prior``.

    A document is pending if its ``doc_id`` is absent from ``prior`` or its
    ``hash_col`` differs (input changed).  This is the core of incremental,
    resumable processing.
    """
    if prior is None or prior.is_empty():
        return corpus
    cols = ["doc_id"]
    if hash_col in corpus.columns and hash_col in prior.columns:
        cols.append(hash_col)
    seen = prior.select(cols).unique()
    joined = corpus.join(seen, on=cols, how="anti")
    return joined


def merge_incremental(prior: pl.DataFrame | None, fresh: pl.DataFrame, key: str = "doc_id") -> pl.DataFrame:
    """Combine newly-processed rows with prior rows, fresh wins on key collision."""
    if prior is None or prior.is_empty():
        return fresh
    keep = prior.join(fresh.select(key).unique(), on=key, how="anti")
    out_df = pl.concat([keep, fresh], how="diagonal_relaxed")
    return out_df


# --- CLI helpers -----------------------------------------------------------


def add_common_args(parser) -> None:
    parser.add_argument("--limit", type=int, default=None, help="Process at most N documents (dev runs).")
    parser.add_argument("--congregation", type=str, default=None, help="Restrict to one congregation_dir.")
    parser.add_argument("--force", action="store_true", help="Reprocess all documents, ignoring cached state.")


def apply_filters(corpus: pl.DataFrame, args) -> pl.DataFrame:
    df = corpus
    if getattr(args, "congregation", None):
        df = df.filter(pl.col("congregation_dir") == args.congregation)
    if getattr(args, "limit", None):
        df = df.head(args.limit)
    return df
