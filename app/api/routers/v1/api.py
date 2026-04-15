from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.routers.v1.crawler_router import router as crawler_router
from app.api.routers.v1.card_router import router as card_router
from app.api.schemas.base_schema import BaseResponse
from app.api.dependencies import verify_api_key
from app.services.rag import RAG

router = APIRouter()

router.include_router(crawler_router, prefix="/crawler", tags=["crawler"], dependencies=[Depends(verify_api_key)])
router.include_router(card_router, prefix="/card", tags=["card"], dependencies=[Depends(verify_api_key)])


@router.get("/health", tags=["health"])
async def health(request: Request):
    """Check service availability and Milvus connectivity."""
    rag: RAG = getattr(request.state, "rag", None)
    milvus_ok = rag.vector_manager.ping() if rag else False

    status_code = 200 if milvus_ok else 503
    response = BaseResponse(
        status="success" if milvus_ok else "fail",
        message="Service is healthy." if milvus_ok else "Milvus is unreachable.",
    )
    return JSONResponse(content=response.model_dump(), status_code=status_code)