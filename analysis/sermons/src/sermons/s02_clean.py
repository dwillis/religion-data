"""S02 -- Clean & normalize.

Most congregations wrap every sermon in near-identical boilerplate (a spoken
intro "The following message is brought to you by..." and a closing copyright
notice).  We detect that boilerplate by *word-level consensus within each
(congregation_dir, doc_type) group* -- the leading/trailing run of tokens shared
by a majority of the group's documents -- and strip it.  Detected templates are
written to ``config/boilerplate/`` for transparency.

Output: ``cache/clean.parquet`` (doc_id, raw_text, clean_text, n_prefix_stripped,
n_suffix_stripped, disfluency_count).  ``raw_text`` is preserved verbatim for
style/rhetoric; ``clean_text`` (boilerplate removed, whitespace/quotes
normalized) feeds themes/NER/scripture.

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s02_clean.py
"""

from __future__ import annotations

import argparse
import re
from collections import Counter

import polars as pl
from tqdm import tqdm

from sermons import common

MAX_SCAN = 120          # words to scan at each end when looking for boilerplate
CONSENSUS = 0.60        # fraction of group docs that must share a token position
MATCH_THRESH = 0.70     # fraction of consensus tokens a doc must match to be stripped
MIN_GROUP = 5           # need at least this many docs to trust a consensus
BOILER_DIR = common.CONFIG_DIR / "boilerplate"

_DISFLUENCY_RE = re.compile(r"\b(uh|um|uhh|umm|er)\b", re.I)
_WS_RE = re.compile(r"\s+")
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}


def normalize_ws(text: str) -> str:
    for k, v in _QUOTES.items():
        text = text.replace(k, v)
    return _WS_RE.sub(" ", text).strip()


def consensus_run(word_lists: list[list[str]], from_end: bool) -> list[str]:
    """Longest run of leading (or trailing) tokens shared by >=CONSENSUS of docs."""
    run: list[str] = []
    for i in range(MAX_SCAN):
        toks = []
        for w in word_lists:
            if len(w) <= i:
                continue
            toks.append(w[-(i + 1)].lower() if from_end else w[i].lower())
        if len(toks) < MIN_GROUP:
            break
        tok, cnt = Counter(toks).most_common(1)[0]
        if cnt / len(word_lists) >= CONSENSUS:
            run.append(tok)
        else:
            break
    return run


def strip_count(words: list[str], consensus: list[str], from_end: bool) -> int:
    """How many tokens to strip from this doc given the group consensus run."""
    if not consensus:
        return 0
    n = len(consensus)
    if len(words) <= n:
        return 0
    seg = [w.lower() for w in (words[-n:][::-1] if from_end else words[:n])]
    matches = sum(1 for a, b in zip(seg, consensus) if a == b)
    return n if matches / n >= MATCH_THRESH else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="S02 strip boilerplate + normalize.")
    common.add_common_args(parser)
    args = parser.parse_args()

    corpus = common.apply_filters(common.require("corpus.parquet"), args)
    norm = pl.read_parquet(common.cache("normalized.parquet")).select(["doc_id", "text"])
    df = corpus.select(["doc_id", "congregation_dir", "doc_type", "content_sha"]).join(norm, on="doc_id", how="inner")

    prior = None if args.force else (
        pl.read_parquet(common.cache("clean.parquet")) if common.cache("clean.parquet").exists() else None)
    pending = common.select_pending(df, prior)
    print(f"{pending.height} documents to clean ({df.height - pending.height} unchanged).")
    if pending.is_empty():
        return

    BOILER_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for (cong, dtype), group in tqdm(list(pending.group_by(["congregation_dir", "doc_type"])),
                                     desc="groups"):
        texts = group["text"].to_list()
        ids = group["doc_id"].to_list()
        word_lists = [t.split() for t in texts]
        pre = consensus_run(word_lists, from_end=False) if len(texts) >= MIN_GROUP else []
        suf = consensus_run(word_lists, from_end=True) if len(texts) >= MIN_GROUP else []
        if pre or suf:
            (BOILER_DIR / f"{cong}__{dtype}.txt").write_text(
                "=== PREFIX ===\n" + " ".join(pre) + "\n\n=== SUFFIX ===\n" + " ".join(reversed(suf)) + "\n",
                encoding="utf-8")
        for did, raw, words in zip(ids, texts, word_lists):
            np_ = strip_count(words, pre, from_end=False)
            ns_ = strip_count(words, suf, from_end=True)
            body = words[np_: len(words) - ns_] if ns_ else words[np_:]
            clean = normalize_ws(" ".join(body))
            rows.append({
                "doc_id": did,
                "raw_text": raw,
                "clean_text": clean,
                "n_prefix_stripped": np_,
                "n_suffix_stripped": ns_,
                "disfluency_count": len(_DISFLUENCY_RE.findall(raw)),
            })

    fresh = pl.DataFrame(rows)
    merged = common.merge_incremental(prior, fresh)
    merged.write_parquet(common.cache("clean.parquet"))
    print(f"Wrote cache/clean.parquet: {merged.height} rows")
    print(f"mean prefix stripped: {fresh['n_prefix_stripped'].mean():.1f} words, "
          f"suffix: {fresh['n_suffix_stripped'].mean():.1f} words")


if __name__ == "__main__":
    main()
