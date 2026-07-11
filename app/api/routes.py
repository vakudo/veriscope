import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.schemas import AnalysisResult, AnalyzeRequest

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze", response_model=AnalysisResult)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalysisResult:
    if not payload.text and not payload.url:
        raise HTTPException(status_code=422, detail="either text or url is required")
    try:
        return await request.app.state.pipeline.analyze(
            text=payload.text, url=payload.url, title=payload.title, force=payload.force
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analyze/stream")
async def analyze_stream(payload: AnalyzeRequest, request: Request) -> StreamingResponse:
    if not payload.text and not payload.url:
        raise HTTPException(status_code=422, detail="either text or url is required")
    pipeline = request.app.state.pipeline
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress(event: dict) -> None:
        await queue.put(event)

    async def worker() -> None:
        try:
            result = await pipeline.analyze(
                text=payload.text,
                url=payload.url,
                title=payload.title,
                force=payload.force,
                progress=progress,
            )
            await queue.put({"stage": "done", "result": result.model_dump(mode="json")})
        except ValueError as error:
            await queue.put({"stage": "error", "detail": str(error)})
        except Exception:
            await queue.put({"stage": "error", "detail": "internal error"})

    task = asyncio.create_task(worker())

    async def stream():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("stage") in {"done", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
