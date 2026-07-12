# Roadmap

Current state: the pipeline works end to end, the offline test suite passes,
calibration is measured (83% on 75 claims), a balanced AVeriTeC baseline is
documented, and the backend ships hardened API boundaries (SSRF guards, rate
limiting, optional API key), observability endpoints, PostgreSQL persistence
and reproducible extension/container builds. What remains towards v1.0, in
priority order:

## 1. Verdict quality

- [ ] Re-run calibration (`python -m scripts.calibrate data/calibration_full.jsonl`)
      after the grounded-refutation change and update the README table —
      the published numbers predate it, and `conflicting` (0% accuracy) was
      driven exactly by ungrounded refutations.
- [ ] If `conflicting` is still weak: require at least two independent refuting
      source groups before a refutation can outweigh support
      (`app/pipeline/verdict.py`).
- [ ] Fine-tune the stance component (QLoRA on FEVER gold evidence, using the
      production prompt), measure before/after on the same calibration set.
      Adopt only if macro-F1 actually improves.

## 2. External benchmarks

- [ ] Full AVeriTeC dev split run (`python -m scripts.evaluate_averitec` without
      `--limit`) — the current baseline is a 20-claim balanced sample.
- [ ] FEVER dev: stance component accuracy in isolation
      (supports / refutes / NEI).
- [ ] Publish the results in the README — the measured numbers are the main
      artifact of this project.

## 3. Public beta

- [ ] Deploy the backend (docker compose is ready: VPS + Caddy/nginx with
      HTTPS; set `API_ACCESS_KEY`, `CORS_ORIGINS` and rate limits).
- [x] GitHub Pages: deployed automatically by the `pages` workflow from `docs/`.

## 4. v1.0 release

- [ ] Extension: icons, screenshots, Chrome Web Store listing
      (switch `host_permissions` from localhost to the production domain).
- [ ] Tag `v1.0.0` (the release workflow builds and attaches the extension ZIP).

## Deliberately out of scope

- A "truth percentage" — contradicts the core idea of the project.
- Accounts, queues, Kubernetes — unnecessary at this scale.
- Training on Russian fake-news datasets — cross-lingual qualitative
  evaluation only (see "A note on bias" in the README).
