"""S06 -- Themes / topic modeling.

Runs BERTopic (UMAP + HDBSCAN + c-TF-IDF) over the *reused* chunk embeddings
from S05, then asks an LLM (Ollama) to turn each topic's top terms +
representative chunks into a human-readable theme label.  Aggregates theme
prevalence by denomination and over time.

Outputs:
  * ``topics.parquet``        -- topic_id, size, top_terms, llm_label, llm_summary
  * ``doc_topics.parquet``    -- doc_id -> dominant topic_id (+ denomination/year)
  * ``chunk_topics.parquet``  -- chunk-level topic assignment

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s06_topics.py
    uv run --group analysis python analysis/sermons/src/sermons/s06_topics.py --no-llm-labels
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

from sermons import common, llm

LABEL_MODEL = "llama3.1:8b"  # override with --label-model; use a cloud model for best labels


def label_topic(topic_id: int, terms: list[str], examples: list[str], model: str, host: str | None) -> dict:
    prompt = llm.load_prompt("topic_label.txt").format(
        terms=", ".join(terms),
        examples="\n---\n".join(e[:600] for e in examples[:4]),
    )
    schema = {"type": "object", "properties": {
        "label": {"type": "string"}, "summary": {"type": "string"}},
        "required": ["label", "summary"]}
    out = llm.generate_json(prompt, model=model, schema=schema, host=host)
    return {"llm_label": out.get("label", ""), "llm_summary": out.get("summary", "")}


def main() -> None:
    parser = argparse.ArgumentParser(description="S06 BERTopic + LLM theme labels.")
    parser.add_argument("--no-llm-labels", action="store_true")
    parser.add_argument("--label-model", default=LABEL_MODEL)
    parser.add_argument("--ollama-host", default=None, help="e.g. an Ollama Cloud endpoint")
    parser.add_argument("--min-topic-size", type=int, default=50)
    args = parser.parse_args()

    chunks = pl.read_parquet(common.cache("chunks.parquet"))
    emb = np.load(common.cache("chunk_emb.npy")).astype(np.float32)
    corpus = common.require("corpus.parquet").select(["doc_id", "denomination", "tradition_family", "year"])

    from bertopic import BERTopic
    from sklearn.feature_extraction.text import CountVectorizer

    vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2), min_df=10)
    model = BERTopic(min_topic_size=args.min_topic_size, vectorizer_model=vectorizer,
                     calculate_probabilities=False, verbose=True)
    docs = chunks["chunk_text"].to_list()
    topic_ids, _ = model.fit_transform(docs, embeddings=emb)

    chunks = chunks.with_columns(pl.Series("topic_id", topic_ids))
    common.write_parquet(chunks.select(["doc_id", "chunk_id", "topic_id"]), "chunk_topics.parquet")

    info = model.get_topic_info()
    rows = []
    for r in info.itertuples():
        if r.Topic == -1:
            continue
        terms = [w for w, _ in model.get_topic(r.Topic)][:10]
        rows.append({"topic_id": int(r.Topic), "size": int(r.Count),
                     "top_terms": terms, "llm_label": "", "llm_summary": ""})
    topics = pl.DataFrame(rows)

    if not args.no_llm_labels and llm.is_available(args.ollama_host):
        reps = model.get_representative_docs()
        labeled = []
        for row in topics.iter_rows(named=True):
            lab = label_topic(row["topic_id"], row["top_terms"],
                              reps.get(row["topic_id"], []), args.label_model, args.ollama_host)
            labeled.append({**row, **lab})
        topics = pl.DataFrame(labeled)
    else:
        print("Skipping LLM labels (disabled or Ollama unavailable).")

    common.write_parquet(topics, "topics.parquet")

    # Dominant topic per document (most frequent non-outlier chunk topic).
    dt = (chunks.filter(pl.col("topic_id") != -1)
          .group_by(["doc_id", "topic_id"]).len()
          .sort(["doc_id", "len"], descending=[False, True])
          .group_by("doc_id").first()
          .select(["doc_id", "topic_id"])
          .join(corpus, on="doc_id", how="left"))
    common.write_parquet(dt, "doc_topics.parquet")
    print(f"Wrote {topics.height} topics; dominant topic for {dt.height} documents")


if __name__ == "__main__":
    main()
