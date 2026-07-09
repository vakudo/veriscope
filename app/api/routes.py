from fastapi import APIRouter, HTTPException, Request

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
            text=payload.text, url=payload.url, title=payload.title
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
