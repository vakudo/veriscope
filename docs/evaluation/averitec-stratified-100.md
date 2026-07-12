# AVeriTeC stratified run (100 claims)

Date: 2026-07-12

Follow-up to the [20-claim exploratory baseline](averitec-baseline-20.md), run
after two verdict changes: refutations must quote an explicit contradiction
from the evidence excerpt (absence is not refutation), and a conflict verdict
requires at least two independent refuting source groups.

## Reproduction

Dataset: official AVeriTeC `dev.json`

- dataset SHA-256: `f0c1f7146d511983c47f3ef77a546f34b8b15c391ce18ea60cacc1a4058df5ed`
- selection: twenty-five examples from each of the four labels
- random seed: `42`
- model: `qwen2.5:7b-instruct`
- embedding model: `nomic-embed-text`
- search: DuckDuckGo
- deep evidence: enabled
- conflict re-verification: enabled
- temporal policy: exclude sources with known dates after the claim date
- publication-date coverage of retained evidence: 13.7% (30 of 219 items)
- elapsed time: 3127.4 seconds

```bash
python -m scripts.evaluate_averitec ../AVeriTeC/data/dev.json \
  --sample-per-label 25 --seed 42 --output-dir artifacts/averitec-stratified-100
```

## Verdict metrics

| Metric | This run | Baseline-20 |
|---|---:|---:|
| Accuracy | 37.0% | 30.0% |
| Macro-F1 | 31.3% | 30.4% |
| Abstention rate | 42.0% | 45.0% |
| Abstention precision | 31.0% | 22.2% |
| Accuracy when not abstaining | 41.4% | 36.4% |

| Gold label | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| Supported | 40.0% | 64.0% | 49.2% | 25 |
| Refuted | 44.4% | 32.0% | 37.2% | 25 |
| Not Enough Evidence | 31.0% | 52.0% | 38.8% | 25 |
| Conflicting Evidence/Cherrypicking | 0.0% | 0.0% | 0.0% | 25 |

### Confusion matrix

Rows are gold labels; columns are predictions.

| Gold / predicted | Supported | Refuted | Not Enough Evidence | Conflicting |
|---|---:|---:|---:|---:|
| Supported | 16 | 2 | 7 | 0 |
| Refuted | 5 | 8 | 12 | 0 |
| Not Enough Evidence | 9 | 3 | 13 | 0 |
| Conflicting Evidence/Cherrypicking | 10 | 5 | 10 | 0 |

## Reading the numbers

1. **The grounded-refutation rule trades refutation recall for precision.**
   Half of the missed refutations abstained (12 of 25 became Not Enough
   Evidence) instead of guessing; confidently wrong refutations are rarer than
   in the baseline. This is the intended direction for an assistant that
   prefers "cannot verify" over a wrong verdict.
2. **The conflicting column is empty by design.** After the two-group conflict
   rule the pipeline essentially never emits `conflicting` from noisy
   single-source disagreements — and AVeriTeC's fourth label additionally
   covers cherrypicking/misleading context, which Veriscope does not model at
   all. Its 25 examples scatter across the other three predictions. Mapping
   this class properly needs a dedicated misleading-context model, not a
   threshold tweak.
3. **Retrieval remains the bottleneck.** Most abstentions and Supported→NEI
   errors come from evidence that was never retrieved, and only 13.7% of
   retained evidence has a recoverable publication date, which limits temporal
   filtering.
4. Source authority is still scarce: 186 of 219 evidence items fall into the
   `other` category; official and academic sources are rare in DuckDuckGo
   results for these claims.

## Limitations

- The sample is balanced by label and does not reflect AVeriTeC's natural
  class distribution; 25 per label still yields wide confidence intervals.
- Only verdict classification metrics were computed; the official evidence
  and justification score was not run.
- Web search and live pages change over time; reruns will not be
  byte-identical.
- AVeriTeC labels inherit the judgments of their annotators and source
  fact-checking organizations.
