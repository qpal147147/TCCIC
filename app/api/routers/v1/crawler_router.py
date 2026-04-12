import os
import sys
import logging
import json
import asyncio
import multiprocessing
from typing import Literal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
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
from app.utils.logger_setup import LOG_FORMAT, LOG_DIR, LOG_FILENAME

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
    # scrapy_settings.set('LOG_LEVEL', global_settings.LOG_LEVEL)
    # scrapy_settings.set('LOG_FILE', f"{LOG_DIR}/{LOG_FILENAME}")
    # scrapy_settings.set('LOG_FORMAT', LOG_FORMAT)
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
    Initializes and runs the Scrapy spider in a separate process.  
    This function supports passing in a list for batch crawling.
    """
    try:
        for data in spider_data:
            config_path = data.config_path
            bank_code = data.bank_code
            url = data.url
            file_name = data.file_name

            logger.info(f"Start crawling all card information from '{url}', bank code: '{bank_code}'.")
            logger.info(f"The crawl result will be saved to '{file_name}'.jsonl.")
            
            # crawler startup
            p = multiprocessing.Process(
                target=crawl_card_list,
                args=(config_path, bank_code, url, file_name)
            )
            p.start()
            p.join()

            logger.info(f"Crawling completed.")
    except Exception as e:
        logger.error(f"An error occurred during card list crawling: {str(e)}")

def run_card_feature_spider(spider_data: list[CardFeatureSpiderData]):
    """
    Initializes and runs the Scrapy spider in a separate process.  
    This function supports passing in a list for batch crawling.
    """
    try:
        for data in spider_data:
            config_path = data.config_path
            bank_code = data.bank_code
            card_name = data.card_name
            card_url = data.card_url
            file_name = data.file_name
            job_id = data.job_id
            job_status_txt_path = data.job_status_txt_path

            logger.info(f"Start crawling all card information from '{card_url}', bank code: '{bank_code}', card name: '{card_name}'.")
            logger.info(f"The crawl result will be saved to '{file_name}'.jsonl.")
            
            # crawler startup
            p = multiprocessing.Process(
                target=crawl_card_feature,
                args=(config_path, bank_code, card_name, card_url, file_name)
            )
            p.start()
            p.join()

            logger.info(f"Crawling completed.")
            logger.info(f"Start to save the card information to the vector database.")

            feature_jsonl_path = Path(global_settings.CRAWLER_DATA_DIR) / bank_code / "card_feature" / file_name / f"{file_name}.jsonl"
            if not feature_jsonl_path.exists():
                logger.error(f"The feature jsonl file does not exist at {feature_jsonl_path}.")
                write_job_status(job_status_txt_path, job_id, "Error")
                continue

            if os.stat(feature_jsonl_path).st_size == 0:
                logger.info(f"The feature jsonl file is empty, skipping.")
                write_job_status(job_status_txt_path, job_id, "Error")
                continue
            
            rag = RAG(
                vector_storage_url=global_settings.VECTOR_CLIENT_URL,
                collection_name=global_settings.VECTOR_COLLECTION_NAME
            )
            asyncio.run(rag.chunk_images_to_vecdb(
                feature_jsonl_path,
                file_name,
                card_name,
                bank_code,
                batch_size=15
            ))
            write_job_status(job_status_txt_path, job_id, "True")

            logger.info(f"Card information has been saved.")

    except Exception as e:
        logger.error(f"An error occurred during card feature crawling: {e}")

def write_job_status(txt_path: str|Path, job_id: str, status: Literal["True", "False", "Error"]):
    Path(txt_path).touch(exist_ok=True)
    lines = []
    with open(txt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        if line.startswith(job_id):
            lines[i] = f"{job_id},{status}\n"
            found = True
            break
    
    if found:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    else:
        with open(txt_path, "a", encoding="utf-8") as f:
            f.write(f"{job_id},{status}\n")


### API endpoints ###
@router.post("/card-list")
async def card_list(request: CardListRequest, background_tasks: BackgroundTasks):
    """ 
    Start crawling all card information from the provided URL. 
    """
    job_id = str(uuid4())
    list_id = f"list-{uuid4().hex}"

    try:
        background_tasks.add_task(
            run_card_list_spider,
            spider_data=[CardListSpiderData(
                config_path=CONFIG_PATH,
                bank_code=request.bank_code,
                url=request.url,
                file_name=list_id,
                job_id=job_id
            )]
        )      

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, list_id=list_id, bank_code=request.bank_code)
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except Exception as e:
        logger.error(f"Error occurred while running the spider: {e}.")
        
        response = BaseResponse[JobIDResponse](
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.post("/batch/card-list")
async def batch_card_list(request: list[CardListRequest], background_tasks: BackgroundTasks):
    """ 
    Start crawling all card information from the provided URL.  
    This function supports batch processing.
    """
    try:
        logger.info(f"Create a batch task")
        spider_data: list[CardListSpiderData] = []
        for req in request:
            job_id = str(uuid4())
            list_id = f"list-{uuid4().hex}"

            spider_data.append(CardListSpiderData(
                config_path=CONFIG_PATH,
                bank_code=req.bank_code,
                url=req.url,
                file_name=list_id,
                job_id=job_id
            ))
        
        # start crawling
        background_tasks.add_task(
            run_card_list_spider,
            spider_data=spider_data
        )      

        response = BaseResponse[list[JobIDResponse]](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=[
                JobIDResponse(job_id=job_id, list_id=data.file_name, bank_code=req.bank_code) 
                for req, data in zip(request, spider_data)
            ]
        )
        return JSONResponse(content=response.model_dump(), status_code=202)

    except Exception as e:
        logger.error(f"Error occurred while running the spider: {e}.")
        
        response = BaseResponse[JobIDResponse](
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
            message = f"Successfully crawled all card information.",
            data = BankCardListPageData(
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
        logger.error(f"File not found: {card_list_file_path}")

        response = BaseResponse(
            status="fail",
            message = f"File not found: {card_list_file_path}",
            error = f"{e}"
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
    except ValueError as e:
        logger.error(f"Error occurred while reading the JSONL file: {e}")
        response = BaseResponse(
            status="fail",
            message = f"Error occurred while reading the JSONL file.",
            error = f"{e}"
        )
        return JSONResponse(content=response.model_dump(), status_code=400)
    except Exception as e:
        logger.error(f"Error occurred while reading the JSONL file: {e}")

        response = BaseResponse(
            status="fail",
            message = f"Error occurred while reading the JSONL file.",
            error = f"{e}"
        )
        return JSONResponse(content=response.model_dump(), status_code=500)


@router.post("/card-feature")
async def card_feature(request: CardFeatureRequest, background_tasks: BackgroundTasks):
    """
    Start crawling card feature information from the provided URL.  
    And save the result to the vector database.
    """
    job_id = str(uuid4())
    card_id = f"card-{uuid4().hex}"

    try:
        write_job_status(JOB_STATUS_TXT_PATH, job_id, "False")

        # start crawling
        background_tasks.add_task(
            run_card_feature_spider, 
            spider_data=[CardFeatureSpiderData(
                config_path=CONFIG_PATH, 
                bank_code=request.bank_code, 
                card_name=request.card_name, 
                card_url=request.card_url, 
                file_name=card_id, 
                job_id=job_id, 
                job_status_txt_path=JOB_STATUS_TXT_PATH
            )]
        )    

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, bank_code=request.bank_code, card_name=request.card_name, card_id=card_id)
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
    except Exception as e:
        logger.error(f"Error occurred while running the spider: {e}.")
        
        response = BaseResponse(
            status="fail",
            message="Errors during crawling.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.post("/batch/card-feature")
async def batch_card_feature(request: list[CardFeatureRequest], background_tasks: BackgroundTasks):
    """
    Start crawling card feature information from the provided URL.  
    And save the result to the vector database.  
    This function supports batch processing.
    """
    try:
        logger.info(f"Create a batch task")
        spider_data: list[CardFeatureSpiderData] = []
        for req in request:
            job_id = str(uuid4())
            card_id = f"card-{uuid4().hex}"

            write_job_status(JOB_STATUS_TXT_PATH, job_id, "False")
            spider_data.append(CardFeatureSpiderData(
                config_path=CONFIG_PATH, 
                bank_code=req.bank_code, 
                card_name=req.card_name, 
                card_url=req.card_url, 
                file_name=card_id, 
                job_id=job_id, 
                job_status_txt_path=JOB_STATUS_TXT_PATH
            ))

        # start crawling
        background_tasks.add_task(run_card_feature_spider, spider_data=spider_data)

        response = BaseResponse[list[JobIDResponse]](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=[
                JobIDResponse(job_id=data.job_id, bank_code=req.bank_code, card_name=req.card_name, card_id=data.file_name)
                for req, data in zip(request, spider_data)
            ]
        )
        return JSONResponse(content=response.model_dump(), status_code=202)
            
    except Exception as e:
        logger.error(f"Error occurred while running the batch spider: {e}.")
        
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
                fjob_id, fjog_status = line.strip().split(",")
                if fjob_id == job_id:
                    response = BaseResponse[CardFeatureResponse](
                        status="success",
                        message="Query job status successfully.",
                        data=CardFeatureResponse(job_status=bool(fjog_status))
                    )
                    return JSONResponse(content=response.model_dump(), status_code=200)
        
        # if not found, it will raise
        raise ValueError(f"Job {job_id} not found.")
    
    except Exception as e:
        logger.error(f"Error occurred while getting the job status: {e}")

        response = BaseResponse(
            status="fail",
            message="Error occurred while getting the job status.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)

