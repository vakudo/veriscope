# Experimental query planner comparison

Date: 2026-07-12

This experiment used the same balanced 20-claim AVeriTeC manifest as the initial
baseline: five examples per label, seed 42, and dataset SHA-256
`f0c1f7146d511983c47f3ef77a546f34b8b15c391ce18ea60cacc1a4058df5ed`.

The only intended retrieval change was an LLM planner that used claim date,
speaker, location and reporting-source context to produce verification questions
and focused web queries. Neutral and counter-evidence fallback queries were kept.

```bash
python -m scripts.evaluate_averitec ../AVeriTeC/data/dev.json \
  --sample-per-label 5 --seed 42 --query-planner \
  --output-dir artifacts/averitec-query-plan-20
```

## Result

| Metric | Original baseline | Query planner | Change |
|---|---:|---:|---:|
| Accuracy | 30.0% | 25.0% | -5.0 pp |
| Macro-F1 | 30.4% | 22.3% | -8.1 pp |
| Abstention rate | 45.0% | 30.0% | -15.0 pp |
| Abstention precision | 22.2% | 16.7% | -5.5 pp |
| Accuracy when not abstaining | 36.4% | 28.6% | -7.8 pp |

The planner improved retrieval recall and fixed some previously evidence-starved
claims, but the extra material caused more false `supported` verdicts. `Refuted`
F1 fell to zero on this sample, while `Supported` recall rose from 20% to 60% with
precision of only 27.3%.

Only 5 of 48 retained evidence items had a recognized publication date (10.4%
coverage). This makes it unsafe to interpret higher live-web recall as historically
valid evidence for claims from 2020.

## Decision

The query planner remains available for experiments but is disabled by default.
It must not become the production default until source authority, historical
availability and mention-versus-confirmation handling improve on the frozen
manifest without reducing abstention precision.

## Follow-up

1. Rank official and primary records ahead of secondary pages.
2. Distinguish a source repeating an allegation from independently confirming it.
3. Recover publication dates or archive availability before historical stance
   aggregation.
4. Rerun the exact manifest before enabling the planner by default.
