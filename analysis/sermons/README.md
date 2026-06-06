# Sermon Corpus Analysis Pipeline

Broad text analysis of the ~28k transcribed sermons in `sermons/` — themes,
style, rhetoric, NER, and structure — with comparisons across **denomination /
tradition**, **time**, and **scripture coverage**.

The pipeline is a chain of **resumable, incremental stages**. Each reads/writes
Parquet keyed by `doc_id` under `data/sermons_analysis/`, so stages join cleanly
and re-running after adding sermons only reprocesses what changed.

## Design at a glance

- **Document text** lives once in `cache/normalized.parquet` (S00); everything
  downstream joins on `doc_id`.
- **`corpus.parquet`** (S01) is the spine: identity, title, resolved
  `sermon_date`, detected `doc_type` ∈ {transcribed, prepared, unknown}, a
  `usable` quality flag, and the congregation metadata join.
- **`doc_type`** is a first-class covariate. The corpus today is effectively all
  `transcribed`; when prepared/written sermons are added they are auto-detected
  and the type-aware branches (cleaning, segmentation, style, rhetoric) adapt so
  spoken and written sermons are never pooled.
- **Embeddings** (S05) are computed once and reused by topics (S06) and
  segmentation (S03).
- **Classical/statistical NLP** does the full-corpus work; **Ollama** is used
  only for human-readable theme labels (S06) and a sampled rhetorical-mode pass
  (S09). Prompts are versioned in `prompts/`; LLM responses are cached.

## Metadata you maintain

Two files under `config/` are yours to curate (the pipeline consumes, never
invents them):

- **`congregations.csv`** — `congregation_dir → congregation, denomination,
  tradition_family, location`. A best-effort starter version is checked in;
  correct it (notably `mlibc_text`, `ststephens_text`, `household_faith_text`).
  If it's missing, S01 writes a seed template listing every directory and exits.
- **`sermon_dates.csv`** *(optional)* — `doc_id` (or `path`) → `sermon_date`.
  When present it is preferred over dates parsed from filenames; the
  `date_source` column on `corpus.parquet` records which was used.

Gazetteers/lexicons (also editable): `bible_books.csv`, `biblical_figures.txt`,
`theologians.txt`, `rhetoric_lexicons.yaml`.

## Stages

| Stage | Script | Output | Notes |
|------|--------|--------|-------|
| S00 | `s00_ingest.py` | `cache/normalized.parquet` | txt/md/docx/pdf → text; incremental on file hash |
| S01 | `s01_index.py` | `corpus.parquet` | metadata, date resolution, doc-type, quality flag |
| S02 | `s02_clean.py` | `cache/clean.parquet` | boilerplate stripping (per congregation×doc_type) |
| S04 | `s04_scripture.py` | `scripture_refs/coverage.parquet` | case-sensitive book matcher, confidence tiers |
| S05 | `s05_embed.py` | `cache/chunk_emb.npy`, `doc_emb.parquet` | sentence-transformers on MPS |
| S06 | `s06_topics.py` | `topics/doc_topics.parquet` | BERTopic + Ollama labels |
| S03 | `s03_segment.py` | `sentences/segments/structure.parquet` | sentencizer + embedding topic-shift + moves |
| S07 | `s07_ner.py` | `entities.parquet` | spaCy + gazetteers (+ optional GLiNER); incremental |
| S08 | `s08_style.py` | `style.parquet` | readability, lexical diversity, register |
| S09 | `s09_rhetoric.py` | `rhetoric.parquet` (+ `rhetoric_modes`) | patterns/lexicons + sampled LLM modes |
| S10 | `s10_report.py` | `report/*.csv`, `*.html`, `SUMMARY.md` | DuckDB rollups + Altair charts |

## Setup

```bash
uv sync --group analysis
uv run python -m spacy download en_core_web_lg   # for S07 NER and S08 --spacy
```

## Run

```bash
# Full pipeline (resumable; re-runs only process new/changed docs)
uv run --group analysis python analysis/sermons/src/sermons/run.py

# Just the fast stages (no embeddings/topics/NER/segmentation)
uv run --group analysis python analysis/sermons/src/sermons/run.py --light

# Resume at embeddings; or run one stage on one congregation
uv run --group analysis python analysis/sermons/src/sermons/run.py --from s05
uv run --group analysis python analysis/sermons/src/sermons/run.py --only s04 --congregation hopebible_text
```

Stages can also be run directly, e.g.
`uv run --group analysis python analysis/sermons/src/sermons/s01_index.py --limit 200`.
All stages accept `--limit N`, `--congregation <dir>`, and `--force`.

## Querying results

Outputs are Parquet — query ad hoc with DuckDB:

```python
import duckdb
duckdb.sql("""
  SELECT tradition_family, book, sum(n_refs) refs
  FROM 'data/sermons_analysis/scripture_coverage.parquet'
  GROUP BY 1,2 ORDER BY refs DESC LIMIT 20
""")
```

The headline numbers and rollup CSVs land in `data/sermons_analysis/report/`.

## What's committed vs. cached

Small summary tables (`corpus.parquet`, `scripture_*`, `topics`, `style`,
`rhetoric`, `entities`, `report/*.csv`) are committed. Large intermediates
(normalized/clean text, embeddings, LLM cache) live under
`data/sermons_analysis/cache/` and are gitignored.
