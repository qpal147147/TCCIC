import logging
import multiprocessing
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.routers.v1.api import router as v1_router
from app.utils.logger_setup import setup_app_logger
from app.services.rag import RAG
from app.configs.global_settings import global_settings


setup_app_logger()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"FastAPI is started")

    rag = RAG(
        vector_storage_url=global_settings.VECTOR_CLIENT_URL,
        collection_name=global_settings.VECTOR_COLLECTION_NAME
    )
    yield {"rag": rag}
    await rag.close()
    logger.info(f"FastAPI is down")

app = FastAPI(title="TCCIC FastAPI Application", version="1.0.0", lifespan=lifespan)
app.include_router(v1_router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse)
async def root():
    return "<h1>Welcome to TCCIC FastAPI Application</h1>"


if __name__ == "__main__":
    # multiprocessing.set_start_method("spawn")

    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=1108, reload=False, workers=2)