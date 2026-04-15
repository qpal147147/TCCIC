import asyncio
import logging
import multiprocessing
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.api.routers.v1.api import router as v1_router
from app.api.routers.v1.crawler_router import run_card_feature_spider, run_card_list_spider
from app.utils.logger_setup import setup_app_logger
from app.services.rag import RAG
from app.configs.global_settings import global_settings


setup_app_logger()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI is started")

    rag = RAG(
        vector_storage_url=global_settings.VECTOR_CLIENT_URL,
        collection_name=global_settings.VECTOR_COLLECTION_NAME
    )

    feature_queue: asyncio.Queue = asyncio.Queue(maxsize=global_settings.CRAWL_QUEUE_MAX_SIZE)
    list_queue: asyncio.Queue = asyncio.Queue(maxsize=global_settings.CRAWL_QUEUE_MAX_SIZE)

    async def _feature_worker():
        while True:
            spider_data = await feature_queue.get()
            try:
                await asyncio.to_thread(run_card_feature_spider, spider_data)
            except Exception as e:
                logger.error(f"Feature worker error: {e}")
            finally:
                feature_queue.task_done()

    async def _list_worker():
        while True:
            spider_data = await list_queue.get()
            try:
                await asyncio.to_thread(run_card_list_spider, spider_data)
            except Exception as e:
                logger.error(f"List worker error: {e}")
            finally:
                list_queue.task_done()

    workers = (
        [asyncio.create_task(_feature_worker()) for _ in range(global_settings.CRAWL_MAX_CONCURRENT_JOBS)]
        + [asyncio.create_task(_list_worker()) for _ in range(global_settings.CRAWL_MAX_CONCURRENT_JOBS)]
    )

    yield {
        "rag": rag,
        "feature_queue": feature_queue,
        "list_queue": list_queue,
    }

    # Graceful shutdown: cancel workers and wait for them to exit
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    await rag.close()
    logger.info("FastAPI is down")


app = FastAPI(title="TCCIC FastAPI Application", version="1.0.0", lifespan=lifespan)
app.include_router(v1_router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse)
async def root():
    return "<h1>Welcome to TCCIC FastAPI Application</h1>"


if __name__ == "__main__":
    # multiprocessing.set_start_method("spawn")

    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=1108, reload=False, workers=2)
