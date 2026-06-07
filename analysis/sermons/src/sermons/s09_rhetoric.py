"""S09 -- Rhetoric.

Pattern- and lexicon-based rhetorical features over every usable document
(``raw_text``), plus an optional LLM pass on a stratified sample that labels the
dominant rhetorical mode (expository/hortatory/narrative/polemical) and devices.

Outputs:
  * ``rhetoric.parquet``        -- per-doc pattern/lexicon features (+ doc_type).
  * ``rhetoric_modes.parquet``  -- LLM mode labels for the sample (if enabled).

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s09_rhetoric.py
    uv run --group analysis python analysis/sermons/src/sermons/s09_rhetoric.py --llm-sample 1500
"""

from __future__ import annotations

import argparse
import re
from collections import Counter

import polars as pl
import yaml
from tqdm import tqdm

from sermons import common, llm

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z']+")
# Verbs that commonly open an imperative/hortatory sentence in preaching.
IMPERATIVE_OPENERS = {
    "let", "consider", "remember", "look", "listen", "turn", "notice", "think",
    "behold", "repent", "come", "go", "see", "hear", "watch", "beware", "trust",
    "believe", "pray", "give", "take", "follow", "stop", "don't", "do",
}
LEXICONS_PATH = common.CONFIG_DIR / "rhetoric_lexicons.yaml"


def load_lexicons() -> dict[str, list[str]]:
    return yaml.safe_load(LEXICONS_PATH.read_text(encoding="utf-8"))


def anaphora_score(sentences: list[str], window: int = 6) -> float:
    """Fraction of sentences whose first two words repeat a recent sentence
    opener (a simple proxy for anaphora / parallel structure)."""
    openers = []
    hits = 0
    for s in sentences:
        ws = _WORD_RE.findall(s.lower())
        op = " ".join(ws[:2]) if len(ws) >= 2 else (ws[0] if ws else "")
        if op and op in openers[-window:]:
            hits += 1
        openers.append(op)
    return round(hits / max(len(sentences), 1), 4)


def rhetoric_features(text: str, lexicons: dict) -> dict:
    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    n_sent = max(len(sentences), 1)
    tokens = [w.lower() for w in _WORD_RE.findall(text)]
    n_tok = max(len(tokens), 1)
    low = text.lower()

    questions = sum(1 for s in sentences if s.rstrip().endswith("?"))
    exclam = sum(1 for s in sentences if s.rstrip().endswith("!"))
    imperatives = sum(1 for s in sentences
                      if (_WORD_RE.findall(s.lower()) or [""])[0] in IMPERATIVE_OPENERS)

    def lex_rate(words: list[str]) -> float:
        return round(1000 * sum(low.count(w) for w in words) / n_tok, 3)

    return {
        "question_rate": round(1000 * questions / n_sent, 2),
        "exclamation_rate": round(1000 * exclam / n_sent, 2),
        "imperative_rate": round(1000 * imperatives / n_sent, 2),
        "anaphora_score": anaphora_score(sentences),
        "hedge_rate": lex_rate(lexicons.get("hedges", [])),
        "booster_rate": lex_rate(lexicons.get("boosters", [])),
        "exhortation_rate": lex_rate(lexicons.get("exhortation", [])),
        "inclusive_rate": lex_rate(lexicons.get("inclusive", [])),
    }


def stratified_sample(corpus: pl.DataFrame, n: int) -> pl.DataFrame:
    """Sample ~evenly across (doc_type, denomination) so minority groups appear."""
    groups = corpus.group_by(["doc_type", "denomination"]).len().height
    per = max(n // max(groups, 1), 1)
    return (corpus.filter(pl.col("usable"))
            .group_by(["doc_type", "denomination"], maintain_order=True)
            .head(per).head(n))


def run_llm_modes(sample: pl.DataFrame, clean_lookup: dict, model: str, host: str | None) -> pl.DataFrame:
    prompt_tmpl = llm.load_prompt("rhetoric_mode.txt")
    schema = {"type": "object", "properties": {
        "mode": {"type": "string"}, "devices": {"type": "array", "items": {"type": "string"}},
        "audience_address": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["mode"]}
    rows = []
    for row in tqdm(sample.iter_rows(named=True), total=sample.height, desc="llm-modes"):
        excerpt = (clean_lookup.get(row["doc_id"], "") or "")[:2500]
        if not excerpt:
            continue
        out = llm.generate_json(prompt_tmpl.format(excerpt=excerpt), model=model, schema=schema, host=host)
        rows.append({"doc_id": row["doc_id"], "doc_type": row["doc_type"],
                     "denomination": row["denomination"], "mode": out.get("mode", ""),
                     "devices": out.get("devices", []), "audience_address": out.get("audience_address", ""),
                     "confidence": float(out.get("confidence", 0) or 0)})
    return pl.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="S09 rhetorical features + optional LLM modes.")
    common.add_common_args(parser)
    parser.add_argument("--llm-sample", type=int, default=0, help="N docs for LLM mode labeling (0=skip)")
    parser.add_argument("--llm-model", default="llama3.1:8b")
    parser.add_argument("--ollama-host", default=None)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet").filter(pl.col("usable")), args)
    clean = pl.read_parquet(common.cache("clean.parquet")).select(["doc_id", "raw_text", "clean_text"])
    df = corpus.select(["doc_id", "doc_type", "denomination", "tradition_family", "year"]).join(
        clean, on="doc_id", how="inner")

    lexicons = load_lexicons()
    rows = []
    for row in tqdm(df.iter_rows(named=True), total=df.height, desc="rhetoric"):
        feats = rhetoric_features(row["raw_text"] or "", lexicons)
        rows.append({"doc_id": row["doc_id"], "doc_type": row["doc_type"],
                     "denomination": row["denomination"], "tradition_family": row["tradition_family"],
                     "year": row["year"], **feats})
    rhet = pl.DataFrame(rows)
    common.write_parquet(rhet, "rhetoric.parquet")
    print(f"Wrote rhetoric.parquet: {rhet.height} rows")

    if args.llm_sample > 0 and llm.is_available(args.ollama_host):
        sample = stratified_sample(corpus, args.llm_sample)
        clean_lookup = dict(zip(clean["doc_id"].to_list(), clean["clean_text"].to_list()))
        modes = run_llm_modes(sample, clean_lookup, args.llm_model, args.ollama_host)
        common.write_parquet(modes, "rhetoric_modes.parquet")
        print(f"Wrote rhetoric_modes.parquet: {modes.height} labeled; mode counts:")
        print(modes.group_by("mode").len().sort("len", descending=True))
    elif args.llm_sample > 0:
        print("LLM mode labeling requested but Ollama unavailable; skipped.")


if __name__ == "__main__":
    main()
