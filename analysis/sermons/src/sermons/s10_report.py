"""S10 -- Reporting.

Builds summary rollups (committable CSVs) and charts (Altair HTML) over whatever
stage outputs exist, then writes a Markdown digest.  Uses DuckDB to query the
Parquet tables directly.  Tolerant of missing optional stages -- it reports what
is available and skips the rest.

Outputs under ``data/sermons_analysis/report/``:
  * ``*.csv``      -- rollup tables (corpus, scripture, themes, style, rhetoric, ner)
  * ``*.html``     -- Altair charts
  * ``SUMMARY.md`` -- narrative digest with the headline numbers

Usage:
    uv run --group analysis python analysis/sermons/src/sermons/s10_report.py
"""

from __future__ import annotations

import duckdb
import polars as pl

from sermons import common

REPORT = common.OUT_DIR / "report"
REPORT.mkdir(parents=True, exist_ok=True)


def p(name: str) -> str:
    return str(common.out(name))


def exists(name: str) -> bool:
    return common.out(name).exists()


def save_csv(df: pl.DataFrame, name: str) -> None:
    df.write_csv(REPORT / name)


def chart(df: pl.DataFrame, name: str, spec_fn) -> None:
    try:
        import altair as alt  # noqa: F401

        spec_fn(df).save(str(REPORT / name))
    except Exception as exc:  # noqa: BLE001
        print(f"  (chart {name} skipped: {exc})")


def main() -> None:
    con = duckdb.connect()
    md: list[str] = ["# Sermon Corpus Analysis -- Summary\n"]

    # --- Corpus overview ---
    corpus = common.require("corpus.parquet")
    n_total = corpus.height
    n_usable = int(corpus["usable"].sum())
    md.append(f"- **Documents:** {n_total} ({n_usable} usable)")
    md.append(f"- **Congregations:** {corpus['congregation_dir'].n_unique()}")
    comp = con.execute(f"""
        SELECT tradition_family, doc_type, count(*) n, round(avg(word_count)) avg_words
        FROM read_parquet('{p("corpus.parquet")}') WHERE usable
        GROUP BY 1,2 ORDER BY 1,2""").pl()
    save_csv(comp, "corpus_composition.csv")

    dated = corpus.filter(pl.col("year").is_not_null())
    if dated.height:
        by_year = dated.group_by("year").len().sort("year")
        save_csv(by_year, "documents_by_year.csv")
        md.append(f"- **Dated documents:** {dated.height} "
                  f"({dated['year'].min()}–{dated['year'].max()})")

    # --- Scripture coverage (chosen axis) ---
    if exists("scripture_coverage.parquet"):
        heat = con.execute(f"""
            SELECT tradition_family, book, testament, sum(n_refs) refs, count(distinct doc_id) docs
            FROM read_parquet('{p("scripture_coverage.parquet")}')
            GROUP BY 1,2,3 ORDER BY refs DESC""").pl()
        save_csv(heat, "scripture_book_by_tradition.csv")
        otnt = con.execute(f"""
            SELECT tradition_family, testament, sum(n_refs) refs
            FROM read_parquet('{p("scripture_coverage.parquet")}')
            GROUP BY 1,2 ORDER BY 1,2""").pl()
        save_csv(otnt, "scripture_ot_nt_by_tradition.csv")
        top_books = heat.group_by("book").agg(pl.col("refs").sum()).sort("refs", descending=True).head(20)
        md.append(f"- **Top books preached:** {', '.join(top_books['book'].to_list()[:10])}")

        def _heatmap(df):
            import altair as alt

            top = df.group_by("book").agg(pl.col("refs").sum()).sort("refs", descending=True).head(25)["book"]
            d = df.filter(pl.col("book").is_in(top.to_list()))
            return alt.Chart(d.to_pandas()).mark_rect().encode(
                x=alt.X("tradition_family:N", title="Tradition"),
                y=alt.Y("book:N", sort=top.to_list(), title="Book"),
                color=alt.Color("refs:Q", scale=alt.Scale(scheme="blues")),
            ).properties(title="Scripture coverage: book x tradition", width=300, height=500)

        chart(heat, "scripture_heatmap.html", _heatmap)

    # --- Themes ---
    if exists("doc_topics.parquet") and exists("topics.parquet"):
        topics = pl.read_parquet(p("topics.parquet"))
        prevalence = con.execute(f"""
            SELECT t.tradition_family, dt.topic_id, count(*) n
            FROM read_parquet('{p("doc_topics.parquet")}') dt
            JOIN read_parquet('{p("corpus.parquet")}') t USING (doc_id)
            GROUP BY 1,2""").pl().join(
                topics.select(["topic_id", "llm_label", "top_terms"]), on="topic_id", how="left")
        save_csv(prevalence, "theme_prevalence_by_tradition.csv")
        if "year" in corpus.columns:
            over_time = con.execute(f"""
                SELECT dt.year, dt.topic_id, count(*) n
                FROM read_parquet('{p("doc_topics.parquet")}') dt
                WHERE dt.year IS NOT NULL GROUP BY 1,2 ORDER BY 1""").pl().join(
                    topics.select(["topic_id", "llm_label"]), on="topic_id", how="left")
            save_csv(over_time, "theme_over_time.csv")
        md.append(f"- **Topics discovered:** {topics.height}")

    # --- Style & rhetoric (faceted by doc_type) ---
    for stage, cols in [("style.parquet", ["flesch_kincaid_grade", "mean_sentence_len",
                                           "mattr", "pron_second_rate", "pron_first_pl_rate"]),
                        ("rhetoric.parquet", ["question_rate", "imperative_rate", "anaphora_score",
                                              "exhortation_rate", "booster_rate", "hedge_rate"])]:
        if exists(stage):
            df = pl.read_parquet(p(stage))
            agg = df.group_by(["tradition_family", "doc_type"]).agg(
                [pl.col(c).mean().round(3).alias(c) for c in cols if c in df.columns])
            save_csv(agg, stage.replace(".parquet", "_by_tradition.csv"))

    # --- NER ---
    if exists("entities.parquet"):
        ents = con.execute(f"""
            SELECT label, lower(text) entity, count(*) n
            FROM read_parquet('{p("entities.parquet")}')
            GROUP BY 1,2 ORDER BY n DESC""").pl()
        save_csv(ents.head(500), "top_entities.csv")
        md.append(f"- **Entity mentions:** {int(ents['n'].sum())} "
                  f"across {ents['entity'].n_unique()} unique entities")

    # --- Structure ---
    if exists("structure.parquet"):
        st = pl.read_parquet(p("structure.parquet"))
        md.append(f"- **Closing prayer detected:** {int(st['has_closing_prayer'].sum())}/{st.height} docs; "
                  f"**Q&A-format:** {int(st['is_qa_format'].sum())}")

    (REPORT / "SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote report to {REPORT}")
    print("\n".join(md))


if __name__ == "__main__":
    main()
