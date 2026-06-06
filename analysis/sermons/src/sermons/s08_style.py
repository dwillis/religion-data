"""S08 -- Style / stylometrics.

Per-document metrics computed on ``raw_text`` (disfluencies and verbal register
are part of the style signal).  Core metrics use only ``textstat`` + regex so
the stage runs without heavy ML deps; an optional ``--spacy`` pass adds POS mix
and passive-voice rate.

Output: ``style.parquet`` (one row per usable document).  Always carries
``doc_type`` so reports can facet -- written and spoken sermons differ
systematically and must never be pooled.

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s08_style.py
    uv run --group analysis python analysis/sermons/src/sermons/s08_style.py --spacy
"""

from __future__ import annotations

import argparse
import re
from collections import Counter

import polars as pl
from tqdm import tqdm

from sermons import common

_WORD_RE = re.compile(r"[A-Za-z']+")
_SENT_RE = re.compile(r"[.!?]+")
PRONOUNS = {
    "i": "first_sg", "me": "first_sg", "my": "first_sg", "mine": "first_sg",
    "we": "first_pl", "us": "first_pl", "our": "first_pl", "ours": "first_pl",
    "you": "second", "your": "second", "yours": "second",
}
MODALS = {"can", "could", "may", "might", "must", "shall", "should", "will", "would", "ought"}


def mattr(tokens: list[str], window: int = 200) -> float:
    """Moving-average type-token ratio -- length-robust lexical diversity."""
    if len(tokens) <= window:
        return len(set(tokens)) / max(len(tokens), 1)
    ratios = []
    for i in range(0, len(tokens) - window + 1, window // 2):
        win = tokens[i:i + window]
        ratios.append(len(set(win)) / window)
    return sum(ratios) / len(ratios)


def style_features(text: str) -> dict:
    import textstat

    tokens = [w.lower() for w in _WORD_RE.findall(text)]
    n = max(len(tokens), 1)
    sents = [s for s in _SENT_RE.split(text) if s.strip()]
    sent_lens = [len(_WORD_RE.findall(s)) for s in sents] or [0]
    pron = Counter(PRONOUNS[t] for t in tokens if t in PRONOUNS)
    counts = Counter(tokens)
    hapax = sum(1 for _, c in counts.items() if c == 1)
    return {
        "n_words": len(tokens),
        "n_sentences": len(sents),
        "mean_sentence_len": sum(sent_lens) / len(sent_lens),
        "flesch_reading_ease": textstat.flesch_reading_ease(text),
        "flesch_kincaid_grade": textstat.flesch_kincaid_grade(text),
        "gunning_fog": textstat.gunning_fog(text),
        "mattr": round(mattr(tokens), 4),
        "hapax_ratio": round(hapax / n, 4),
        "pron_first_sg_rate": round(1000 * pron["first_sg"] / n, 3),
        "pron_first_pl_rate": round(1000 * pron["first_pl"] / n, 3),
        "pron_second_rate": round(1000 * pron["second"] / n, 3),
        "modal_rate": round(1000 * sum(counts[m] for m in MODALS) / n, 3),
    }


def add_spacy_pos(df: pl.DataFrame, clean_lookup: dict, model: str, n_process: int) -> pl.DataFrame:
    import spacy

    nlp = spacy.load(model, disable=["ner", "lemmatizer"])
    nlp.max_length = 4_000_000
    ids = df["doc_id"].to_list()
    texts = [clean_lookup[d] for d in ids]
    pos_rows = []
    for did, doc in tqdm(zip(ids, nlp.pipe(texts, n_process=n_process, batch_size=16)),
                         total=len(texts), desc="pos"):
        pos = Counter(t.pos_ for t in doc if not t.is_space)
        total = max(sum(pos.values()), 1)
        passive = sum(1 for t in doc if t.dep_ in ("nsubjpass", "auxpass"))
        pos_rows.append({
            "doc_id": did,
            "verb_rate": round(pos["VERB"] / total, 4),
            "noun_rate": round(pos["NOUN"] / total, 4),
            "adj_rate": round(pos["ADJ"] / total, 4),
            "adv_rate": round(pos["ADV"] / total, 4),
            "passive_rate": round(1000 * passive / total, 3),
        })
    return df.join(pl.DataFrame(pos_rows), on="doc_id", how="left")


def main() -> None:
    parser = argparse.ArgumentParser(description="S08 stylometrics.")
    common.add_common_args(parser)
    parser.add_argument("--spacy", action="store_true", help="add POS mix + passive rate")
    parser.add_argument("--spacy-model", default="en_core_web_lg")
    parser.add_argument("--n-process", type=int, default=4)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet").filter(pl.col("usable")), args)
    clean = pl.read_parquet(common.cache("clean.parquet")).select(["doc_id", "raw_text", "clean_text"])
    df = corpus.select(["doc_id", "doc_type", "denomination", "tradition_family", "year", "disfluency_rate"]).join(
        clean, on="doc_id", how="inner")

    rows = []
    for row in tqdm(df.iter_rows(named=True), total=df.height, desc="style"):
        feats = style_features(row["raw_text"] or "")
        rows.append({"doc_id": row["doc_id"], "doc_type": row["doc_type"],
                     "denomination": row["denomination"], "tradition_family": row["tradition_family"],
                     "year": row["year"], "disfluency_rate": row["disfluency_rate"], **feats})
    style = pl.DataFrame(rows)

    if args.spacy:
        clean_lookup = dict(zip(df["doc_id"].to_list(), df["clean_text"].to_list()))
        style = add_spacy_pos(style, clean_lookup, args.spacy_model, args.n_process)

    common.write_parquet(style, "style.parquet")
    print(f"Wrote style.parquet: {style.height} rows")
    print(style.group_by("tradition_family").agg(
        pl.col("flesch_kincaid_grade").mean().round(2),
        pl.col("mean_sentence_len").mean().round(1),
        pl.col("pron_second_rate").mean().round(2)).sort("tradition_family"))


if __name__ == "__main__":
    main()
