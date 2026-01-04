from fastapi import APIRouter
from app.api.routers.v1.crawler_router import router as crawler_router
from app.api.routers.v1.card_router import router as card_router

router = APIRouter()
router.include_router(crawler_router, prefix="/crawler", tags=["crawler"])
router.include_router(card_router, prefix="/card", tags=["card"])