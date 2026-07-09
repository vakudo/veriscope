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
- searches evidence per claim and shows sources with dates and types
  (possible primary source / reprint / opinion);
- classifies the stance of every (claim, source) pair:
  `supports` / `refutes` / `not_enough_info`;
- checks **source independence**: 20 reprints of one press release count as one
  piece of evidence, not twenty (near-duplicate clustering over embeddings +
  earliest-publication heuristic for the likely primary source);
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

## Evaluation plan

- **AVeriTeC** — primary benchmark: real-world claims with web evidence and
  justifications; mirrors this pipeline end to end.
- **FEVER / FEVEROUS** — evaluating the stance component
  (supports / refutes / NEI).
- Russian sets (Fakespeak-RUS, Kuzmin et al. 2020, the Kazakh-Russian
  7-category corpus) — **qualitative cross-lingual evaluation only**, not
  training data: they are small and their labels carry the bias of specific
  fact-checking agencies.

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
