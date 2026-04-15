import os
import sys
import asyncio
import logging
import json
import multiprocessing
from typing import Literal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from filelock import FileLock
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from app.api.schemas.base_schema import BaseResponse, JobIDResponse
from app.api.schemas.crawler_schema import CardListRequest, CardFeatureRequest, CardFeatureResponse, CardListSpiderData, CardFeatureSpiderData
from app.crawler.schemas.card_list import CardItem, CardPagesItem, BankCardListPageData
from app.crawler.tccic.spiders.card_list_spider import CardListSpider
from app.crawler.tccic.spiders.card_feature_spider import CardFeatureSpider
from app.crawler.tccic import settings as project_settings
from app.services.rag import RAG
from app.configs.global_settings import global_settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "banks"
SCRAPY_PROJECT_PATH = PROJECT_ROOT / "crawler"
sys.path.append(str(SCRAPY_PROJECT_PATH))

JOB_STATUS_TXT_PATH = f"{global_settings.CRAWLER_DATA_DIR}/feature_job_status.txt"


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

### Spider functions ###
def crawl_card_list(config_path: str|Path, bank_code: str, url: str, file_name: str):
    process = CrawlerProcess(SCRAPY_SETTINGS)
    process.crawl(CardListSpider, config_path, bank_code, url, file_name)
    process.start()

def crawl_card_feature(config_path: str|Path, bank_code: str, card_name: str, card_url: str, file_name: str):
    process = CrawlerProcess(SCRAPY_SETTINGS)
    process.crawl(CardFeatureSpider, config_path, bank_code, card_name, card_url, file_name)
    process.start()

def run_card_list_spider(spider_data: list[CardListSpiderData]):
    """
    Runs the Scrapy card-list spider sequentially for each item in spider_data.
    Called from a worker thread (asyncio.to_thread) inside main.py's list worker pool.
    """
    try:
        for data in spider_data:
            logger.info(f"Start crawling card list from '{data.url}', bank code: '{data.bank_code}'.")
            logger.info(f"Result will be saved to '{data.file_name}'.jsonl.")

            p = multiprocessing.Process(
                target=crawl_card_list,
                args=(data.config_path, data.bank_code, data.url, data.file_name)
            )
            p.start()
            p.join()

            logger.info("Card list crawling completed.")
    except Exception as e:
        logger.error(f"An error occurred during card list crawling: {str(e)}")

def run_card_feature_spider(spider_data: list[CardFeatureSpiderData]):
    """
    Runs the Scrapy card-feature spider sequentially for each item in spider_data,
    then vectorizes the results into Milvus.
    Called from a worker thread (asyncio.to_thread) inside main.py's feature worker pool.
    """
    try:
        for data in spider_data:
            logger.info(f"Start crawling card feature from '{data.card_url}', bank: '{data.bank_code}', card: '{data.card_name}'.")
            logger.info(f"Result will be saved to '{data.file_name}'.jsonl.")

            p = multiprocessing.Process(
                target=crawl_card_feature,
                args=(data.config_path, data.bank_code, data.card_name, data.card_url, data.file_name)
            )
            p.start()
            p.join()

            logger.info("Card feature crawling completed. Starting vectorization.")

            feature_jsonl_path = (
                Path(global_settings.CRAWLER_DATA_DIR)
                / data.bank_code / "card_feature" / data.file_name / f"{data.file_name}.jsonl"
            )
            if not feature_jsonl_path.exists():
                logger.error(f"Feature JSONL not found: {feature_jsonl_path}")
                write_job_status(data.job_status_txt_path, data.job_id, "error")
                continue

            if os.stat(feature_jsonl_path).st_size == 0:
                logger.info("Feature JSONL is empty, skipping.")
                write_job_status(data.job_status_txt_path, data.job_id, "error")
                continue

            rag = RAG(
                vector_storage_url=global_settings.VECTOR_CLIENT_URL,
                collection_name=global_settings.VECTOR_COLLECTION_NAME
            )
            asyncio.run(rag.chunk_images_to_vecdb(
                feature_jsonl_path,
                data.file_name,
                data.card_name,
                data.bank_code,
            ))
            write_job_status(data.job_status_txt_path, data.job_id, "completed")
            logger.info("Card information saved to vector database.")

    except Exception as e:
        logger.error(f"An error occurred during card feature crawling: {e}")

def write_job_status(txt_path: str|Path, job_id: str, status: Literal["pending", "completed", "error"]):
    txt_path = Path(txt_path)
    lock_path = txt_path.with_suffix(".lock")
    txt_path.touch(exist_ok=True)

    with FileLock(lock_path):
        lines = txt_path.read_text(encoding="utf-8").splitlines(keepends=True)

        found = False
        for i, line in enumerate(lines):
            if line.startswith(job_id):
                lines[i] = f"{job_id},{status}\n"
                found = True
                break

        if not found:
            lines.append(f"{job_id},{status}\n")

        txt_path.write_text("".join(lines), encoding="utf-8")


### API endpoints ###

@router.post("/card-list")
async def card_list(request: Request, body: CardListRequest):
    """
    Submit a card-list crawl job. The job is queued and processed by a background worker.
    """
    job_id = str(uuid4())
    list_id = f"list-{uuid4().hex}"
    queue: asyncio.Queue = request.state.list_queue

    try:
        spider_data = [CardListSpiderData(
            config_path=CONFIG_PATH,
            bank_code=body.bank_code,
            url=body.url,
            file_name=list_id,
            job_id=job_id
        )]
        queue.put_nowait(spider_data)

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, list_id=list_id, bank_code=body.bank_code)
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503)
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

    queue: asyncio.Queue = request.state.list_queue

    try:
        spider_data: list[CardListSpiderData] = []
        for req in body:
            job_id = str(uuid4())
            list_id = f"list-{uuid4().hex}"
            spider_data.append(CardListSpiderData(
                config_path=CONFIG_PATH,
                bank_code=req.bank_code,
                url=req.url,
                file_name=list_id,
                job_id=job_id
            ))

        queue.put_nowait(spider_data)

        response = BaseResponse[list[JobIDResponse]](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=[
                JobIDResponse(job_id=data.job_id, list_id=data.file_name, bank_code=req.bank_code)
                for req, data in zip(body, spider_data)
            ]
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503)
    except Exception as e:
        logger.error(f"Error submitting batch card-list job: {e}")
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.get("/card-list/{list_id}")
async def card_list_result(list_id: str):
    try:
        card_list_file_path = next(Path(global_settings.CRAWLER_DATA_DIR).rglob(f"{list_id}.jsonl"))

        if os.stat(card_list_file_path).st_size == 0:
            raise ValueError("The crawl has not yet completed or errors occurred during the crawl.")

        # remove duplicates
        cleaned_item = []
        with open(card_list_file_path, "r") as f:
            cards = set()
            for line in f:
                json_data = json.loads(line)
                card_info = (json_data['card_url'], json_data['card_title'])

                if card_info not in cards:
                    cards.add(card_info)
                    cleaned_item.append(json_data)

        # process the cleaned JSON data
        page_map = {}
        bank_name = ""
        bank_code = ""

        for item in cleaned_item:
            bank_name = item['bank_name']
            bank_code = item['bank_code']
            page_url = item['page_url']

            card = CardItem(title=item['card_title'], url=item['card_url'])
            if page_url not in page_map:
                page_map[page_url] = CardPagesItem(page_url=page_url, cards=[card])
            else:
                page_map[page_url].cards.append(card)

        response = BaseResponse[BankCardListPageData](
            status="success",
            message="Successfully crawled all card information.",
            data=BankCardListPageData(
                bank_code=bank_code,
                bank_name=bank_name,
                pages=list(page_map.values())
            )
        )
        return JSONResponse(content=response.model_dump(), status_code=200)
    except StopIteration:
        response = BaseResponse(
            status="fail",
            message="The crawl has not yet completed or the file does not exist.",
            error=f"No JSONL file found for list_id='{list_id}'."
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        response = BaseResponse(
            status="fail",
            message="File not found.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
    except ValueError as e:
        logger.error(f"Error reading JSONL file: {e}")
        response = BaseResponse(
            status="fail",
            message="Error occurred while reading the JSONL file.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
    except Exception as e:
        logger.error(f"Unexpected error reading JSONL file: {e}")
        response = BaseResponse(
            status="fail",
            message="Error occurred while reading the JSONL file.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=500)


@router.post("/card-feature")
async def card_feature(request: Request, body: CardFeatureRequest):
    """
    Submit a card-feature crawl + vectorize job.
    The job is queued and processed by a background worker.
    """
    job_id = str(uuid4())
    card_id = f"card-{uuid4().hex}"
    queue: asyncio.Queue = request.state.feature_queue

    try:
        write_job_status(JOB_STATUS_TXT_PATH, job_id, "pending")

        spider_data = [CardFeatureSpiderData(
            config_path=CONFIG_PATH,
            bank_code=body.bank_code,
            card_name=body.card_name,
            card_url=body.card_url,
            file_name=card_id,
            job_id=job_id,
            job_status_txt_path=JOB_STATUS_TXT_PATH
        )]
        queue.put_nowait(spider_data)

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, bank_code=body.bank_code, card_name=body.card_name, card_id=card_id)
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        write_job_status(JOB_STATUS_TXT_PATH, job_id, "error")
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503)
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

    queue: asyncio.Queue = request.state.feature_queue

    try:
        spider_data: list[CardFeatureSpiderData] = []
        for req in body:
            job_id = str(uuid4())
            card_id = f"card-{uuid4().hex}"

            write_job_status(JOB_STATUS_TXT_PATH, job_id, "pending")
            spider_data.append(CardFeatureSpiderData(
                config_path=CONFIG_PATH,
                bank_code=req.bank_code,
                card_name=req.card_name,
                card_url=req.card_url,
                file_name=card_id,
                job_id=job_id,
                job_status_txt_path=JOB_STATUS_TXT_PATH
            ))

        queue.put_nowait(spider_data)

        response = BaseResponse[list[JobIDResponse]](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=[
                JobIDResponse(job_id=data.job_id, bank_code=req.bank_code, card_name=req.card_name, card_id=data.file_name)
                for req, data in zip(body, spider_data)
            ]
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except asyncio.QueueFull:
        for data in spider_data:
            write_job_status(JOB_STATUS_TXT_PATH, data.job_id, "error")
        response = BaseResponse(
            status="fail",
            message="Server is busy. Please retry later.",
            error="Job queue is full."
        )
        return JSONResponse(content=response.model_dump(), status_code=503)
    except Exception as e:
        logger.error(f"Error submitting batch card-feature job: {e}")
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.get("/card-feature/{job_id}/status")
async def card_status(job_id: str):
    try:
        logger.info(f"Query job status: {job_id}")

        with open(JOB_STATUS_TXT_PATH, "r") as f:
            for line in f:
                fjob_id, fjob_status = line.strip().split(",")
                if fjob_id == job_id:
                    response = BaseResponse[CardFeatureResponse](
                        status="success",
                        message="Query job status successfully.",
                        data=CardFeatureResponse(job_status=fjob_status)
                    )
                    return JSONResponse(content=response.model_dump(), status_code=200)

        raise ValueError(f"Job {job_id} not found.")

    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        response = BaseResponse(
            status="fail",
            message="Error occurred while getting the job status.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
