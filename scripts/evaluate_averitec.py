import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from app.config import get_settings
from app.evaluation.averitec import (
    claim_date,
    classification_metrics,
    evidence_date_metrics,
    fact_check_domain,
    load_references,
    prediction_from_verdict,
    select_references,
    stratified_indices,
)
from app.llm import LLMClient
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import DdgsSearch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Veriscope on normalized AVeriTeC claims and report verdict metrics."
    )
    parser.add_argument("dataset", help="Path to the official AVeriTeC dev.json or train.json")
    parser.add_argument("--output-dir", default="artifacts/averitec")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--sample-per-label",
        type=int,
        help="Select this many deterministic examples from each of the four labels",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--strict-dates",
        action="store_true",
        help="Reject evidence without a known publication date in historical evaluation",
    )
    parser.add_argument("--sleep", type=float, default=1.0, help="Delay between web searches")
    parser.add_argument("--resume", action="store_true", help="Continue a matching partial run")
    return parser.parse_args()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def resumed_predictions(path: Path, references: list[dict], resume: bool) -> list[dict]:
    if not resume or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) > len(references):
        raise ValueError("existing predictions are not a partial run for this dataset slice")
    for index, prediction in enumerate(payload):
        if prediction.get("claim") != references[index]["claim"]:
            raise ValueError(f"existing prediction {index} does not match the selected dataset slice")
    return payload


def build_selection(args: argparse.Namespace, all_references: list[dict]) -> tuple[list[dict], list[int]]:
    if args.sample_per_label is not None:
        if args.offset or args.limit is not None:
            raise ValueError("--sample-per-label cannot be combined with --offset or --limit")
        indices = stratified_indices(all_references, args.sample_per_label, args.seed)
        return [all_references[index] for index in indices], indices
    references = select_references(all_references, args.offset, args.limit)
    return references, list(range(args.offset, args.offset + len(references)))


def selection_manifest(
    dataset_path: Path,
    references: list[dict],
    indices: list[int],
    args: argparse.Namespace,
) -> dict:
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    return {
        "dataset_file": dataset_path.name,
        "dataset_sha256": digest,
        "selection": {
            "offset": args.offset if args.sample_per_label is None else None,
            "limit": args.limit if args.sample_per_label is None else None,
            "samples_per_label": args.sample_per_label,
            "seed": args.seed if args.sample_per_label is not None else None,
        },
        "examples": [
            {
                "dataset_index": index,
                "claim": reference["claim"],
                "label": reference["label"],
                "claim_date": reference.get("claim_date"),
            }
            for index, reference in zip(indices, references, strict=True)
        ],
    }


def ensure_manifest(path: Path, manifest: dict, resume: bool) -> None:
    if resume and path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise ValueError("existing manifest does not match this dataset and selection")
        return
    write_json(path, manifest)


async def run() -> None:
    args = parse_args()
    if args.sleep < 0:
        raise ValueError("sleep must be non-negative")
    dataset_path = Path(args.dataset)
    references, indices = build_selection(args, load_references(dataset_path))
    output_dir = Path(args.output_dir)
    prediction_path = output_dir / "predictions.json"
    metrics_path = output_dir / "metrics.json"
    manifest = selection_manifest(dataset_path, references, indices, args)
    ensure_manifest(output_dir / "manifest.json", manifest, args.resume)
    predictions = resumed_predictions(prediction_path, references, args.resume)
    if not args.resume:
        write_json(prediction_path, predictions)

    settings = get_settings()
    llm = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        embed_model=settings.embed_model,
        timeout=settings.request_timeout,
    )
    pipeline = FactCheckPipeline(
        llm=llm,
        search=DdgsSearch(),
        cache=None,
        settings=settings,
    )
    started = time.perf_counter()
    try:
        for index in range(len(predictions), len(references)):
            reference = references[index]
            verdict = await pipeline.verify_claim(
                reference["claim"],
                claim_id=indices[index],
                exclude_domain=fact_check_domain(reference),
                lang="en",
                published_before=claim_date(reference),
                require_known_dates=args.strict_dates,
            )
            predictions.append(prediction_from_verdict(verdict))
            write_json(prediction_path, predictions)
            running = classification_metrics(predictions, references[: len(predictions)])
            mark = "+" if predictions[-1]["label"] == reference["label"] else "-"
            print(
                f"[{len(predictions)}/{len(references)}] {mark} "
                f"{reference['claim'][:72]} -> {predictions[-1]['label']} "
                f"(gold: {reference['label']}, accuracy: {running['accuracy']:.1%})",
                flush=True,
            )
            if args.sleep and index + 1 < len(references):
                await asyncio.sleep(args.sleep)
    finally:
        await llm.close()

    metrics = classification_metrics(predictions, references)
    metrics["evidence_dates"] = evidence_date_metrics(predictions)
    metrics["run"] = {
        "dataset": str(Path(args.dataset).resolve()),
        "dataset_sha256": manifest["dataset_sha256"],
        "selection": manifest["selection"],
        "llm_model": settings.llm_model,
        "embed_model": settings.embed_model,
        "search_provider": "DuckDuckGo",
        "deep_evidence": settings.deep_evidence,
        "verify_conflicts": settings.verify_conflicts,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
        "temporal_filtering": "exclude known source dates after claim_date",
        "strict_dates": args.strict_dates,
    }
    write_json(metrics_path, metrics)
    print(f"predictions: {prediction_path}")
    print(f"metrics: {metrics_path}")
    print(f"accuracy: {metrics['accuracy']:.1%}; macro-F1: {metrics['macro_f1']:.1%}")


if __name__ == "__main__":
    asyncio.run(run())
