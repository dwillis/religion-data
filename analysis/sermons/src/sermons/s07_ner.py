"""S07 -- Named-entity recognition.

Three complementary passes over ``clean_text``:
  1. spaCy ``en_core_web_lg`` (fast, multiprocessed) for standard PERSON / GPE /
     ORG / NORP entities.
  2. Gazetteer PhraseMatcher for domain types DEITY, BIBLICAL_FIGURE, THEOLOGIAN
     (from config/*.txt) -- high precision for the names that matter here.
  3. (optional) GLiNER zero-shot for richer domain types; enable with --gliner.
     Runs on a sample by default since it is slower.

Output: ``entities.parquet`` (doc_id, text, label, source).  Co-occurrence /
network analysis is built in the reporting stage.

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s07_ner.py
    uv run --group analysis python analysis/sermons/src/sermons/s07_ner.py --gliner --gliner-sample 2000
"""

from __future__ import annotations

import argparse

import polars as pl
from tqdm import tqdm

from sermons import common

SPACY_LABELS = {"PERSON", "GPE", "ORG", "NORP", "LOC", "EVENT", "WORK_OF_ART"}
GLINER_LABELS = ["biblical figure", "deity", "theologian", "place",
                 "denomination", "biblical event", "church"]


def load_gazetteers() -> dict[str, list[str]]:
    """Parse @LABEL-sectioned gazetteer files into {label: [phrases]}."""
    out: dict[str, list[str]] = {}
    for fname in ("biblical_figures.txt", "theologians.txt"):
        path = common.CONFIG_DIR / fname
        if not path.exists():
            continue
        label = "THEOLOGIAN" if "theolog" in fname else "BIBLICAL_FIGURE"
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("@"):
                label = line[1:].strip().upper()
                continue
            out.setdefault(label, []).append(line)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="S07 NER over clean_text.")
    common.add_common_args(parser)
    parser.add_argument("--spacy-model", default="en_core_web_lg")
    parser.add_argument("--n-process", type=int, default=4)
    parser.add_argument("--gliner", action="store_true", help="also run GLiNER zero-shot pass")
    parser.add_argument("--gliner-sample", type=int, default=2000)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet").filter(pl.col("usable")), args)
    clean = pl.read_parquet(common.cache("clean.parquet")).select(["doc_id", "clean_text"])
    df = corpus.select(["doc_id", "content_sha"]).join(clean, on="doc_id", how="inner")

    # Incremental: NER is the most expensive stage (spaCy over 265M tokens), so
    # only process documents new/changed since the last run (tracked in a ledger).
    ledger_path = common.cache("ner_ledger.parquet")
    ledger = pl.read_parquet(ledger_path) if (ledger_path.exists() and not args.force) else None
    prior_ents = None if args.force else common.read_parquet("entities.parquet")
    pending = common.select_pending(df, ledger)
    print(f"{pending.height} documents to NER ({df.height - pending.height} unchanged).")
    if pending.is_empty():
        return
    df = pending

    import spacy
    from spacy.matcher import PhraseMatcher

    nlp = spacy.load(args.spacy_model, disable=["lemmatizer", "tagger", "parser", "attribute_ruler"])
    nlp.max_length = 4_000_000

    gaz = load_gazetteers()
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    for label, phrases in gaz.items():
        matcher.add(label, list(nlp.tokenizer.pipe(phrases)))

    ids = df["doc_id"].to_list()
    texts = df["clean_text"].to_list()
    rows = []
    for did, doc in tqdm(zip(ids, nlp.pipe(texts, n_process=args.n_process, batch_size=32)),
                         total=len(texts), desc="ner"):
        for ent in doc.ents:
            if ent.label_ in SPACY_LABELS:
                rows.append({"doc_id": did, "text": ent.text, "label": ent.label_, "source": "spacy"})
        for mid, start, end in matcher(doc):
            rows.append({"doc_id": did, "text": doc[start:end].text,
                         "label": nlp.vocab.strings[mid], "source": "gazetteer"})

    if args.gliner:
        rows += run_gliner(df.head(args.gliner_sample))

    fresh = pl.DataFrame(rows, schema={"doc_id": pl.Utf8, "text": pl.Utf8, "label": pl.Utf8, "source": pl.Utf8})
    # Drop any stale entities for reprocessed docs, then append fresh ones.
    if prior_ents is not None and not prior_ents.is_empty():
        prior_ents = prior_ents.filter(~pl.col("doc_id").is_in(df["doc_id"].to_list()))
        ents = pl.concat([prior_ents, fresh], how="diagonal_relaxed")
    else:
        ents = fresh
    common.write_parquet(ents, "entities.parquet")
    # Update the processed ledger.
    new_ledger = common.merge_incremental(ledger, df.select(["doc_id", "content_sha"]))
    new_ledger.write_parquet(ledger_path)
    print(f"Wrote entities.parquet: {ents.height} mentions ({fresh.height} new)")
    print(ents.group_by("label").len().sort("len", descending=True))


def run_gliner(df: pl.DataFrame) -> list[dict]:
    from gliner import GLiNER

    model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
    rows = []
    for row in tqdm(df.iter_rows(named=True), total=df.height, desc="gliner"):
        # GLiNER works on shorter spans; feed the first ~2000 chars per doc.
        for ent in model.predict_entities(row["clean_text"][:2000], GLINER_LABELS, threshold=0.5):
            rows.append({"doc_id": row["doc_id"], "text": ent["text"],
                         "label": ent["label"].upper().replace(" ", "_"), "source": "gliner"})
    return rows


if __name__ == "__main__":
    main()
