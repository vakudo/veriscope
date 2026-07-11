import argparse
import asyncio
import json
from pathlib import Path

from app.cache.store import MemoryEvidenceCache
from app.config import get_settings
from app.llm import LLMClient
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import DdgsSearch
from app.schemas import Claim


async def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--output", default="calibration.json")
    parser.add_argument("--sleep", type=float, default=2.0)
    args = parser.parse_args()
    settings = get_settings()
    llm = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        embed_model=settings.embed_model,
        timeout=settings.request_timeout,
    )
    pipeline = FactCheckPipeline(
        llm=llm, search=DdgsSearch(), cache=MemoryEvidenceCache(), settings=settings
    )
    stats: dict[str, dict[str, int]] = {}
    lines = [line.strip() for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()]
    rows = [json.loads(line) for line in lines if line]
    correct_total = 0
    for index, row in enumerate(rows):
        verdict = await pipeline._check_claim(Claim(id=index, text=row["claim"]))
        label = verdict.label.value
        bucket = stats.setdefault(label, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if label == row["gold"]:
            bucket["correct"] += 1
            correct_total += 1
        mark = "+" if label == row["gold"] else "-"
        accuracy = correct_total / (index + 1)
        print(
            f"[{index + 1}/{len(rows)}] {mark} {row['claim'][:60]} -> {label} "
            f"(gold: {row['gold']}, running accuracy: {accuracy:.0%})",
            flush=True,
        )
        Path(args.output).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if args.sleep > 0 and index + 1 < len(rows):
            await asyncio.sleep(args.sleep)
    print(f"saved: {args.output}")
    await llm.close()


if __name__ == "__main__":
    asyncio.run(run())
