"""
Crawl submission endpoints.

This router only accepts work: every job is recorded in the metadata store,
queued, and acknowledged with a job_id. Status and results are served by job_router, 
so there is exactly one way to ask about a job.
"""

import asyncio
import json
import logging
import multiprocessing
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from app.api.schemas.base_schema import BaseResponse, JobIDResponse
from app.api.schemas.crawler_schema import (
    CardFeatureRequest,
    CardFeatureSpiderData,
    CardListRequest,
    CardListSpiderData,
)
from app.crawler.tccic.spiders.card_list_spider import CardListSpider
from app.crawler.tccic.spiders.card_feature_spider import CardFeatureSpider
from app.crawler.tccic import settings as project_settings
from app.services.rag import RAG
from app.services.store import Store
from app.configs.global_settings import global_settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "banks"
SCRAPY_PROJECT_PATH = PROJECT_ROOT / "crawler"
sys.path.append(str(SCRAPY_PROJECT_PATH))


router = APIRouter()

### Scrapy settings ###
def load_scrapy_settings() -> Settings:
    """
    Loads Scrapy project settings from the project_settings module using
    Scrapy's native setmodule(), which correctly handles all setting types
    (including dict-type settings like DEFAULT_REQUEST_HEADERS).
    """
    scrapy_settings = Settings()
    scrapy_settings.setmodule(project_settings, priority='project')
    scrapy_settings.set('LOG_ENABLED', False)
    return scrapy_settings

SCRAPY_SETTINGS: Settings = load_scrapy_settings()


### Artifact paths ###
def card_list_path(bank_code: str, job_id: str) -> Path:
    """
    Where a card-list crawl writes its results.

    Named by job_id: a card list is a snapshot of one execution, so it needs no
    identity of its own.
    """
    return Path(global_settings.CRAWLER_DATA_DIR) / bank_code / "card_list" / f"{job_id}.jsonl"


def card_feature_dir(bank_code: str, card_key: str) -> Path:
    """
    Where a card-feature crawl writes its screenshots and JSONL.

    Named by card_key, so re-crawling a card replaces its artifacts instead of
    leaving a new directory behind on every run.
    """
    return Path(global_settings.CRAWLER_DATA_DIR) / bank_code / "card_feature" / card_key


### Spider functions ###
def crawl_card_list(config_path: str|Path, bank_code: str, url: str, file_name: str):
    process = CrawlerProcess(SCRAPY_SETTINGS)
    process.crawl(CardListSpider, config_path, bank_code, url, file_name)
    process.start()


def crawl_card_feature(config_path: str|Path, bank_code: str, card_name: str, card_url: str, file_name: str):
    process = CrawlerProcess(SCRAPY_SETTINGS)
    process.crawl(CardFeatureSpider, config_path, bank_code, card_name, card_url, file_name)
    process.start()


def _card_list_stats(jsonl_path: Path) -> dict:
    """
    Count what a card-list crawl actually found.

    Recorded per job so a later run can be compared against it — a bank that
    suddenly yields 3 cards instead of 48 has almost certainly changed its markup.
    """
    cards: set[tuple[str, str]] = set()
    pages: set[str] = set()
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            cards.add((item["card_url"], item["card_title"]))
            pages.add(item["page_url"])
    return {"cards": len(cards), "pages": len(pages)}


def run_card_list_spider(spider_data: list[CardListSpiderData], store: Store):
    """
    Runs the card-list spider once per item, recording each job's outcome.

    Each item is isolated: one failure must not abandon the rest of a batch, nor
    leave the remaining jobs stuck in a non-final state forever.
    """
    for data in spider_data:
        try:
            logger.info(f"Start crawling card list from '{data.url}', bank code: '{data.bank_code}'.")
            store.jobs.mark_running(data.job_id)

            p = multiprocessing.Process(
                target=crawl_card_list,
                args=(data.config_path, data.bank_code, data.url, data.job_id)
            )
            p.start()
            p.join()

            jsonl_path = card_list_path(data.bank_code, data.job_id)
            if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
                logger.error(f"Card list crawl produced no results: {jsonl_path}")
                store.jobs.mark_failed(data.job_id, "Crawl produced no results.")
                continue

            stats = _card_list_stats(jsonl_path)
            store.jobs.mark_completed(data.job_id, stats=stats, artifact_dir=str(jsonl_path))
            logger.info(f"Card list crawling completed: {stats}.")
        except Exception as e:
            logger.error(f"An error occurred during card list crawling: {e}")
            store.jobs.mark_failed(data.job_id, str(e))


def run_card_feature_spider(spider_data: list[CardFeatureSpiderData], store: Store):
    """
    Runs the card-feature spider once per item, then vectorizes the results.

    The RAG client is built on first use and reused for the whole batch — one
    Milvus connection rather than one per card — and closed on the way out.
    Building it lazily also means a crawl that fails before vectorization never
    needs Milvus at all.
    """
    rag: RAG | None = None
    try:
        for data in spider_data:
            try:
                logger.info(
                    f"Start crawling card feature from '{data.card_url}', "
                    f"bank: '{data.bank_code}', card: '{data.card_name}'."
                )
                store.jobs.mark_running(data.job_id)

                p = multiprocessing.Process(
                    target=crawl_card_feature,
                    args=(data.config_path, data.bank_code, data.card_name, data.card_url, data.card_key)
                )
                p.start()
                p.join()

                feature_dir = card_feature_dir(data.bank_code, data.card_key)
                feature_jsonl_path = feature_dir / f"{data.card_key}.jsonl"

                if not feature_jsonl_path.exists() or feature_jsonl_path.stat().st_size == 0:
                    logger.error(f"Feature JSONL missing or empty: {feature_jsonl_path}")
                    store.jobs.mark_failed(data.job_id, "Crawl produced no images.")
                    continue

                logger.info("Card feature crawling completed. Starting vectorization.")
                if rag is None:
                    rag = RAG(
                        vector_storage_url=global_settings.VECTOR_CLIENT_URL,
                        collection_name=global_settings.VECTOR_COLLECTION_NAME
                    )

                image_count = sum(1 for _ in open(feature_jsonl_path, encoding="utf-8"))
                success, failed = asyncio.run(rag.chunk_images_to_vecdb(
                    feature_jsonl_path,
                    data.card_key,
                    data.card_name,
                    data.bank_code,
                ))
                stats = {"images": image_count, "vectorized": success, "failed": failed}

                if success == 0:
                    logger.error(f"Vectorization produced no summaries for '{data.card_name}'.")
                    store.jobs.mark_failed(
                        data.job_id,
                        f"Vectorization produced no summaries ({failed} image(s) failed).",
                        stats=stats,
                    )
                    continue

                # last_changed_at is deliberately left unset: until content hashing
                # lands there is no way to tell a real change from an identical re-crawl.
                store.cards.mark_crawled(data.card_key)
                store.jobs.mark_completed(
                    data.job_id,
                    stats=stats,
                    artifact_dir=str(feature_dir),
                )
                logger.info(f"Card information saved to vector database ({success} ok, {failed} failed).")
            except Exception as e:
                logger.error(f"An error occurred during card feature crawling: {e}")
                store.jobs.mark_failed(data.job_id, str(e))
    finally:
        if rag is not None:
            rag.close()


### API endpoints ###

@router.post("/card-list")
async def card_list(request: Request, body: CardListRequest):
    """
    Submit a card-list crawl job. The job is queued and processed by a background worker.
    """
    store: Store = request.state.store
    queue: asyncio.Queue = request.state.list_queue
    job_id = str(uuid4())

    try:
        store.jobs.create(job_id, "card_list", body.bank_code, body.url)

        spider_data = [CardListSpiderData(
            config_path=CONFIG_PATH,
            bank_code=body.bank_code,
            url=body.url,
            job_id=job_id
        )]
        queue.put_nowait(spider_data)

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, bank_code=body.bank_code)
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        store.jobs.mark_failed(job_id, "Job queue is full.")
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503, headers={"Retry-After": "60"})
    except Exception as e:
        logger.error(f"Error submitting card-list job: {e}")
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.post("/batch/card-list")
async def batch_card_list(request: Request, body: list[CardListRequest]):
    """
    Submit multiple card-list crawl jobs in one request.
    """
    if len(body) > global_settings.CRAWL_BATCH_MAX_SIZE:
        response = BaseResponse(
            status="fail",
            message=f"Batch size cannot exceed {global_settings.CRAWL_BATCH_MAX_SIZE} items.",
            error=f"Received {len(body)} items."
        )
        return JSONResponse(content=response.model_dump(), status_code=400)

    store: Store = request.state.store
    queue: asyncio.Queue = request.state.list_queue
    batch_id = str(uuid4())
    spider_data: list[CardListSpiderData] = []

    try:
        for req in body:
            job_id = str(uuid4())
            store.jobs.create(job_id, "card_list", req.bank_code, req.url, batch_id=batch_id)
            spider_data.append(CardListSpiderData(
                config_path=CONFIG_PATH,
                bank_code=req.bank_code,
                url=req.url,
                job_id=job_id
            ))

        queue.put_nowait(spider_data)

        response = BaseResponse[list[JobIDResponse]](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=[
                JobIDResponse(job_id=data.job_id, bank_code=req.bank_code)
                for req, data in zip(body, spider_data)
            ]
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        for data in spider_data:
            store.jobs.mark_failed(data.job_id, "Job queue is full.")
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503, headers={"Retry-After": "60"})
    except Exception as e:
        logger.error(f"Error submitting batch card-list job: {e}")
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.post("/card-feature")
async def card_feature(request: Request, body: CardFeatureRequest):
    """
    Submit a card-feature crawl + vectorize job.
    The job is queued and processed by a background worker.
    """
    store: Store = request.state.store
    queue: asyncio.Queue = request.state.feature_queue
    job_id = str(uuid4())

    try:
        card = store.cards.upsert(body.bank_code, body.card_name, body.card_url)
        active = store.jobs.find_active_by_card_key(card.card_key)

        if active is not None:
            logger.info(f"Card '{body.card_name}' is already {active.status}; returning job {active.job_id}.")
            response = BaseResponse[JobIDResponse](
                status="success",
                message=f"This card is already being crawled (job is '{active.status}').",
                data=JobIDResponse(
                    job_id=active.job_id,
                    bank_code=body.bank_code,
                    card_name=body.card_name,
                    card_key=card.card_key
                )
            )
            return JSONResponse(content=response.model_dump(), status_code=200)

        store.jobs.create(job_id, "card_feature", body.bank_code, body.card_url, card_key=card.card_key)

        spider_data = [CardFeatureSpiderData(
            config_path=CONFIG_PATH,
            bank_code=body.bank_code,
            card_name=body.card_name,
            card_url=body.card_url,
            card_key=card.card_key,
            job_id=job_id
        )]
        queue.put_nowait(spider_data)

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(
                job_id=job_id,
                bank_code=body.bank_code,
                card_name=body.card_name,
                card_key=card.card_key
            )
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        store.jobs.mark_failed(job_id, "Job queue is full.")
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503, headers={"Retry-After": "60"})
    except Exception as e:
        logger.error(f"Error submitting card-feature job: {e}")
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.post("/batch/card-feature")
async def batch_card_feature(request: Request, body: list[CardFeatureRequest]):
    """
    Submit multiple card-feature crawl + vectorize jobs in one request.
    """
    if len(body) > global_settings.CRAWL_BATCH_MAX_SIZE:
        response = BaseResponse(
            status="fail",
            message=f"Batch size cannot exceed {global_settings.CRAWL_BATCH_MAX_SIZE} items.",
            error=f"Received {len(body)} items."
        )
        return JSONResponse(content=response.model_dump(), status_code=400)

    store: Store = request.state.store
    queue: asyncio.Queue = request.state.feature_queue
    batch_id = str(uuid4())
    spider_data: list[CardFeatureSpiderData] = []

    try:
        acknowledged: list[JobIDResponse] = []
        duplicates = 0

        for req in body:
            card = store.cards.upsert(req.bank_code, req.card_name, req.card_url)

            active = store.jobs.find_active_by_card_key(card.card_key)
            if active is not None:
                duplicates += 1
                acknowledged.append(JobIDResponse(
                    job_id=active.job_id,
                    bank_code=req.bank_code,
                    card_name=req.card_name,
                    card_key=card.card_key
                ))
                continue

            job_id = str(uuid4())
            store.jobs.create(
                job_id, "card_feature", req.bank_code, req.card_url,
                card_key=card.card_key, batch_id=batch_id
            )
            spider_data.append(CardFeatureSpiderData(
                config_path=CONFIG_PATH,
                bank_code=req.bank_code,
                card_name=req.card_name,
                card_url=req.card_url,
                card_key=card.card_key,
                job_id=job_id
            ))
            acknowledged.append(JobIDResponse(
                job_id=job_id,
                bank_code=req.bank_code,
                card_name=req.card_name,
                card_key=card.card_key
            ))

        if spider_data:
            queue.put_nowait(spider_data)

        message = f"{len(spider_data)} crawling job(s) submitted."
        if duplicates:
            message += f" {duplicates} card(s) are already being crawled."

        response = BaseResponse[list[JobIDResponse]](
            status="success",
            message=message,
            data=acknowledged
        )
        # Nothing was accepted for processing when every item was a duplicate.
        return JSONResponse(content=response.model_dump(), status_code=202 if spider_data else 200)
    except asyncio.QueueFull:
        # Only the jobs created here — the deduplicated ones belong to crawls
        # that are still live and must not be marked failed.
        for data in spider_data:
            store.jobs.mark_failed(data.job_id, "Job queue is full.")
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503, headers={"Retry-After": "60"})
    except Exception as e:
        logger.error(f"Error submitting batch card-feature job: {e}")
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
