# Veriscope

A news fact-checking **assistant** — not a "truth detector". It decomposes a news
article into atomic checkable claims, retrieves evidence for each claim from the
web, checks how independent the sources really are, and reports per-claim
verdicts with citations. When there is not enough evidence, it honestly says
"cannot verify" instead of inventing a fake confidence percentage.

## Why not a truth score

An LLM cannot reliably measure "how true" a news story is, and a made-up
percentage is worse than no score at all — it creates an illusion of precision.
Veriscope instead makes the verification process transparent:

- splits the story into atomic, independently checkable claims;
- scans long articles in overlapping chunks sampled across the full document,
  then deduplicates and selects claims round-robin so the ending is not ignored;
- searches evidence per claim and shows sources with dates and types
  (possible primary source / reprint / opinion);
- reports a transparent domain-based source category (official, academic,
  fact-check, social or other) without turning it into a hidden trust score;
- classifies the stance of every (claim, source) pair:
  `supports` / `refutes` / `not_enough_info`;
- checks **source independence**: 20 reprints of one press release count as one
  piece of evidence, not twenty (near-duplicate clustering over embeddings +
  earliest-publication heuristic for the likely primary source);
- searches for counter-evidence explicitly (a second refutation-oriented query
  per claim) and cross-lingually (Russian claims are also checked against
  English sources);
- can experimentally plan concrete verification questions and focused searches
  from date, speaker, location and article-title context (`QUERY_PLANNING=true`),
  while the measured default remains the simpler neutral/counter-evidence search;
- reads the full article of each cluster representative and judges stance on
  the most relevant paragraphs, not on a search snippet;
- re-verifies contested stance judgements: when sources disagree, the minority
  opinion is asked again and dropped if unstable;
- flags manipulation signals: clickbait headline, anonymous sources, emotional
  wording, missing dates/names;
- reports honest verdicts per claim: `supported` / `refuted` / `conflicting` /
  `unverifiable`, with a coarse `high`/`low` confidence based on the number of
  **independent** source groups — never a percentage.

## Architecture

```
Entry points (Telegram bot + browser extension)
        ↓
Text extraction (trafilatura)
        ↓
Claim decomposition (LLM → atomic claims)
        ↓
Evidence retrieval (web search + embedding rerank, per claim)
        ↓
Independence check (near-duplicate clustering, primary-source heuristic)
        ↓
Stance detection (per claim × source pair)
        ↓
Verdict + explanation (per claim, with manipulation flags and citations)
```

Essentially RAG turned inside out: not "find the answer", but "find evidence
for and against a statement".

## Stack

- **FastAPI** backend (`app/`), shared by both entry points
- **aiogram 3** Telegram bot (`bot/`)
- **Manifest V3** browser extension (`extension/`)
- **trafilatura** for article text extraction
- **Qwen2.5** (or any OpenAI-compatible endpoint: Ollama, vLLM, OpenRouter) for
  claim extraction, stance detection and embeddings
- **DuckDuckGo** web search for evidence retrieval
- **pgvector** evidence cache (optional; falls back to in-memory)
- Docker Compose + GitHub Actions CI

## Quickstart

### Local

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; on Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env        # fill in LLM endpoint and bot token
uvicorn app.main:app --reload
```

An OpenAI-compatible LLM endpoint must be reachable (default:
Ollama at `http://localhost:11434/v1` with `qwen2.5:7b-instruct` for chat and
`bge-m3` for embeddings).

Run the Telegram bot (needs `TELEGRAM_BOT_TOKEN` in `.env`):

```bash
python -m bot.main
```

Load the extension: `chrome://extensions` → Developer mode → Load unpacked →
select the `extension/` folder. The backend URL is configurable in the popup.

### Docker

```bash
docker compose up --build
```

Starts Postgres with pgvector (evidence cache), the API on port 8000 and the
bot. The LLM endpoint is configured via `.env`.

### API

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/news/article"}'
```

Request: `{"text": "..."}` or `{"url": "..."}` (optional `"title"`).
Response: per-claim verdicts with evidence, stances, source types, independence
clusters, manipulation flags and a summary.

### Tests

```bash
pytest
ruff check .
```

The test suite runs fully offline: LLM, search and embeddings are replaced with
deterministic fakes via dependency injection.

## Calibration: honest confidence instead of a fake score

The system never outputs "this news is 87% true". Instead, confidence is
*measured*: a labeled set of claims is run through the full pipeline, and the
per-verdict accuracy becomes the number shown in the UI ("verdicts of this
type were correct in N% of benchmark cases").

```bash
python -m scripts.calibrate data/calibration_full.jsonl
```

The script runs every claim through the real pipeline (web search, independence
clustering, stance detection), compares the produced verdict against the gold
label and writes per-label statistics to `calibration.json` (gitignored — it is
a local measurement artifact, not source code). The backend picks the file up
on startup and attaches `historical_accuracy` to every verdict.

Honesty guards built in:

- a percentage is only shown for verdict types with at least 20 benchmark
  samples (`CALIBRATION_MIN_SAMPLES`); small buckets are silently dropped —
  4/4 correct is luck, not a statistic;
- verdict types with no data show nothing rather than a made-up number;
- `data/calibration_full.jsonl` (75 claims) mixes well-documented facts,
  popular misconceptions and deliberately fabricated local "news" that no
  search can confirm — the latter measure how honestly the system says
  "cannot verify".

Measured on this set (qwen2.5:7b-instruct + nomic-embed-text, CPU, July 2026),
overall accuracy 83% (62/75):

| Produced verdict | Samples | Accuracy |
|---|---|---|
| supported | 26 | 92% |
| refuted | 19 | 95% |
| unverifiable | 24 | 83% |
| conflicting | 6 | 0% |

Notable results:

- **all 20 fabricated stories got "cannot verify"** — the system never
  confirmed a non-existent event, which is the failure mode that matters most
  for a fact-checking assistant;
- **"conflicting" is a known weak spot**: every time the system claimed
  sources contradict each other, the claim was actually clearly true or
  clearly false — one noisy stance judgement is enough to flip an otherwise
  correct verdict. Fixing this (stance fine-tuning, requiring at least two
  independent refuting groups) is the next planned experiment;
- errors concentrate in stance detection on borderline snippets, which is the
  argument for fine-tuning the stance component on FEVER (see evaluation
  plan).

## Demo

`docs/index.html` is a static demo with three pre-computed analyses (a real
news story, a myth compilation, a fabricated local story) produced by this
pipeline locally. Regenerate with a running backend:

```bash
python -m scripts.build_demo
```

To publish: repository Settings → Pages → deploy from branch `main`, folder
`/docs`.

## Fine-tuning the stance component

`notebooks/stance_lora.ipynb` is a Colab notebook that fine-tunes
Qwen2.5-7B-Instruct with QLoRA on FEVER gold evidence, using the exact prompt
the pipeline sends in production. It measures zero-shot vs fine-tuned macro-F1
and exports a GGUF for Ollama; the calibration table above is the before/after
benchmark for the whole system.

## Evaluation plan

- **AVeriTeC** — primary benchmark: real-world claims with web evidence and
  justifications; mirrors this pipeline end to end.
- **FEVER / FEVEROUS** — evaluating the stance component
  (supports / refutes / NEI).
- Russian sets (Fakespeak-RUS, Kuzmin et al. 2020, the Kazakh-Russian
  7-category corpus) — **qualitative cross-lingual evaluation only**, not
  training data: they are small and their labels carry the bias of specific
  fact-checking agencies.

### Reproducible AVeriTeC evaluation

Veriscope includes a benchmark harness that runs normalized AVeriTeC claims
through the real retrieval and verdict pipeline. It writes predictions compatible
with the official evaluator plus a standalone report with accuracy, macro-F1,
per-label precision/recall/F1, abstention metrics and a confusion matrix.

Download AVeriTeC separately and keep its dataset outside this repository. The
official data is licensed CC BY-NC 4.0 and is intentionally not redistributed here.

```bash
git clone --depth 1 https://github.com/MichSchli/AVeriTeC.git ../AVeriTeC
python -m scripts.evaluate_averitec ../AVeriTeC/data/dev.json --limit 20
```

For a deterministic balanced baseline across all four labels, use:

```bash
python -m scripts.evaluate_averitec ../AVeriTeC/data/dev.json \
  --sample-per-label 5 --seed 42 --output-dir artifacts/averitec-baseline-20
```

The first exploratory balanced run and its limitations are documented in
[`docs/evaluation/averitec-baseline-20.md`](docs/evaluation/averitec-baseline-20.md).

Add `--strict-dates` to reject evidence whose publication date cannot be
established. Without it, undated evidence remains eligible for better recall. Both
modes report publication-date coverage in `metrics.json`.

The LLM query planner is experimental and disabled by default because its first
frozen comparison increased retrieval recall but reduced verdict quality. Reproduce
that experiment with `--query-planner`; see
[`docs/evaluation/averitec-query-planner-20.md`](docs/evaluation/averitec-query-planner-20.md).

Results and a selection manifest containing the dataset SHA-256 and original row
indices are checkpointed under `artifacts/averitec/`. Continue
an interrupted matching run with `--resume`. Omit `--limit` for the complete dev
split. The harness excludes the target fact-check publisher domain from retrieval
to reduce answer leakage and disables cross-claim caching so results do not depend
on evaluation order. Sources with a known publication date after the AVeriTeC claim
date are excluded both after search and after full-page extraction. Sources with no
recoverable date remain eligible and must be reported as a limitation of benchmark
runs.

## A note on bias

Fact-checking labels — especially for Russian-language news — are politically
loaded and inherit the perspective of whoever produced them. This project does
not claim to escape that: it deliberately reports *evidence and its
independence structure* instead of a single truth score, keeps "cannot verify"
as a first-class answer, and treats Russian-language evaluation as a
cross-lingual transfer study rather than ground truth.

## Project structure

```
app/
  main.py            FastAPI app factory
  config.py          settings (env-driven)
  schemas.py         API and pipeline models
  llm.py             OpenAI-compatible chat + embeddings client
  api/routes.py      /api/analyze, /api/health
  cache/store.py     evidence cache (pgvector or in-memory)
  pipeline/
    extract.py       article text extraction
    claims.py        claim decomposition
    search.py        web search + embedding rerank
    independence.py  near-duplicate clustering, source typing
    stance.py        per (claim, source) stance detection
    manipulation.py  clickbait / anonymity / emotion / attribution heuristics
    verdict.py       verdict aggregation over independent clusters
    runner.py        pipeline orchestration
bot/main.py          Telegram bot (aiogram 3)
extension/           Manifest V3 browser extension
tests/               offline unit + API tests with fakes
```
