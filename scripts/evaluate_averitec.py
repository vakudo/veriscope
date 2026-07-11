import argparse
import asyncio
import json
import time
from pathlib import Path

from app.config import get_settings
from app.evaluation.averitec import (
    classification_metrics,
    fact_check_domain,
    load_references,
    prediction_from_verdict,
    select_references,
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


async def run() -> None:
    args = parse_args()
    if args.sleep < 0:
        raise ValueError("sleep must be non-negative")
    references = select_references(load_references(args.dataset), args.offset, args.limit)
    output_dir = Path(args.output_dir)
    prediction_path = output_dir / "predictions.json"
    metrics_path = output_dir / "metrics.json"
    predictions = resumed_predictions(prediction_path, references, args.resume)

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
                claim_id=args.offset + index,
                exclude_domain=fact_check_domain(reference),
                lang="en",
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
    metrics["run"] = {
        "dataset": str(Path(args.dataset).resolve()),
        "offset": args.offset,
        "limit": args.limit,
        "llm_model": settings.llm_model,
        "embed_model": settings.embed_model,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }
    write_json(metrics_path, metrics)
    print(f"predictions: {prediction_path}")
    print(f"metrics: {metrics_path}")
    print(f"accuracy: {metrics['accuracy']:.1%}; macro-F1: {metrics['macro_f1']:.1%}")


if __name__ == "__main__":
    asyncio.run(run())
