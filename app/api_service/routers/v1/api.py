from fastapi import APIRouter
from app.api_service.routers.v1.crawler_router import router as crawler_router

router = APIRouter()
router.include_router(crawler_router, prefix="/crawler", tags=["crawler"])