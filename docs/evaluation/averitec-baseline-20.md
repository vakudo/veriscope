# AVeriTeC exploratory baseline (20 claims)

Date: 2026-07-11

This is a small diagnostic baseline, not an estimate of production accuracy. Its
purpose is to expose failure modes on an independent dataset before optimizing the
pipeline against it.

## Reproduction

Dataset: official AVeriTeC `dev.json`

- dataset SHA-256: `f0c1f7146d511983c47f3ef77a546f34b8b15c391ce18ea60cacc1a4058df5ed`
- selection: five examples from each of the four labels
- random seed: `42`
- model: `qwen2.5:7b-instruct`
- embedding model: `nomic-embed-text`
- search: DuckDuckGo
- deep evidence: enabled
- conflict re-verification: enabled
- temporal policy: exclude sources with known dates after the claim date
- elapsed time: 498.9 seconds

```bash
python -m scripts.evaluate_averitec ../AVeriTeC/data/dev.json \
  --sample-per-label 5 --seed 42 --output-dir artifacts/averitec-baseline-20
```

The manifest produced by the command records the exact source row indices and the
dataset digest. Search results remain time-dependent, so a rerun is not expected to
produce byte-identical predictions.

## Verdict metrics

| Metric | Result |
|---|---:|
| Accuracy | 30.0% |
| Macro-F1 | 30.4% |
| Abstention rate | 45.0% |
| Abstention precision | 22.2% |
| Accuracy when not abstaining | 36.4% |

| Gold label | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| Supported | 20.0% | 20.0% | 20.0% | 5 |
| Refuted | 50.0% | 40.0% | 44.4% | 5 |
| Not Enough Evidence | 22.2% | 40.0% | 28.6% | 5 |
| Conflicting Evidence/Cherrypicking | 50.0% | 20.0% | 28.6% | 5 |

### Confusion matrix

Rows are gold labels; columns are predictions.

| Gold / predicted | Supported | Refuted | Not Enough Evidence | Conflicting |
|---|---:|---:|---:|---:|
| Supported | 1 | 1 | 2 | 1 |
| Refuted | 1 | 2 | 2 | 0 |
| Not Enough Evidence | 2 | 1 | 2 | 0 |
| Conflicting Evidence/Cherrypicking | 1 | 0 | 3 | 1 |

## Observed failure modes

1. **Absence is sometimes treated as contradiction.** A source that does not mention
   the alleged event can be labeled `refutes` instead of `not_enough_info`. This
   produced confident but unsupported refutations.
2. **Retrieval recall is low.** Six of the twenty claims had no retained evidence.
   Three of the five cherrypicking examples became `Not Enough Evidence`.
3. **Undated sources weaken temporal filtering.** Known future dates are removed, but
   search results without a recoverable date remain eligible and can still introduce
   post-claim information.
4. **The fourth label is not semantically aligned.** AVeriTeC combines conflicting
   evidence and cherrypicking. Veriscope currently emits `conflicting` only from a
   support/refute tie and has no explicit misleading-context or cherrypicking model.
5. **Source independence is not source authority.** Several verdicts relied on
   low-authority secondary pages even when the underlying claim referred to an
   official report or primary record.

## Next actions

1. Make `refutes` require an explicit contradiction in the evidence excerpt; absence
   or unrelated information must resolve to `not_enough_info`.
2. Record publication-date coverage and add a strict historical evaluation mode for
   evidence whose pre-claim availability can be established.
3. Add question decomposition and claim context to retrieval instead of relying on a
   truncated claim-shaped search query.
4. Separate `conflicting evidence` from `misleading context/cherrypicking` in the
   internal verdict model before treating AVeriTeC's fourth class as a direct mapping.
5. Add source authority and primary-record retrieval, then rerun this frozen manifest
   before expanding the sample.

## Limitations

- Twenty examples are too few for a stable accuracy estimate.
- The sample is balanced by label and therefore does not reflect AVeriTeC's natural
  class distribution.
- Only verdict classification metrics were computed. The official evidence and
  justification score was not run in this baseline.
- Web search and live pages change over time.
- AVeriTeC labels and evidence inherit the judgments and biases of their annotators
  and source fact-checking organizations.
