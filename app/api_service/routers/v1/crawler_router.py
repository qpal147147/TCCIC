import os
import sys
import logging
import json
import asyncio
import multiprocessing
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from app.api_service.schemas.base_schema import BaseResponse, JobIDResponse
from app.api_service.schemas.crawler_schema import CardListRequest, CardFeatureRequest, CardFeatureResponse
from app.crawler.schemas.card_list import CardItem, CardPagesItem, BankCardListPageData
from app.crawler.tccic.spiders.card_list_spider import CardListSpider
from app.crawler.tccic.spiders.card_feature_spider import CardFeatureSpider
from app.crawler.tccic import settings as project_settings
from app.services.rag import RAG
from app.configs.global_settings import global_settings
from app.utils.logger_setup import LOG_FORMAT, LOG_DIR, LOG_FILENAME

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "banks.yaml"
SCRAPY_PROJECT_PATH = PROJECT_ROOT / "crawler"
sys.path.append(str(SCRAPY_PROJECT_PATH))

router = APIRouter()

### Scrapy settings ###
def load_scrapy_settings() -> Settings:
    """
    Loads Scrapy project settings from the project_settings module.
    It iterates through all uppercase attributes of project_settings
    and sets them on a new Scrapy Settings object.
    """
    scrapy_settings = Settings()
    for setting_name in dir(project_settings):
        if setting_name.isupper():
            scrapy_settings.set(setting_name, getattr(project_settings, setting_name))
    
    scrapy_settings.set('LOG_LEVEL', global_settings.LOG_LEVEL)
    scrapy_settings.set('LOG_FILE', f"{LOG_DIR}/{LOG_FILENAME}")
    scrapy_settings.set('LOG_FORMAT', LOG_FORMAT)
    return scrapy_settings

SCRAPY_SETTINGS: Settings = load_scrapy_settings()

### Spider functions ###
def run_card_list_spider(config_path: str, bank_code: str, url: str, file_name: str):
    """
    Initializes and runs the Scrapy spider in a separate process.  
    This function is intended to be the target of a multiprocessing.Process.

    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        url: The URL the spider should start crawling.
        file_name: The name of the file to write the results to.
    """
    try:
        logger.info(f"Start crawling all card information from '{url}', bank code: '{bank_code}'.")
        logger.info(f"The crawl result will be saved to '{file_name}'.jsonl.")
        
        process = CrawlerProcess(SCRAPY_SETTINGS)
        process.crawl(CardListSpider, config_path=config_path, bank_code=bank_code, url=url, file_name=file_name)
        process.start()

        logger.info(f"Crawling completed.")
    except Exception as e:
        raise

def run_card_feature_spider(
    config_path: str, 
    bank_code: str, 
    card_name: str, 
    card_url: str, 
    file_name: str, 
    job_id: str,
    job_status_txt_path: str
):
    """
    Initializes and runs the Scrapy spider in a separate process.  
    This function is intended to be the target of a multiprocessing.Process.

    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        card_name: The name of the card to be crawled.
        card_url: The URL the spider should start crawling.
        file_name: The name of the file to write the results to.
        job_id: The ID of the job.
        job_status_txt_path: The path to the job status text file.
    """

    try:
        logger.info(f"Start crawling all card information from '{card_url}', bank code: '{bank_code}', card name: '{card_name}'.")
        logger.info(f"The crawl result will be saved to '{file_name}'.jsonl.")
        
        process = CrawlerProcess(SCRAPY_SETTINGS)
        process.crawl(CardFeatureSpider, config_path, bank_code, card_name, card_url, file_name)
        process.start()

        logger.info(f"Crawling completed.")
        logger.info(f"Start to save the card information to the vector database.")

        feature_jsonl_path = Path(global_settings.CRAWLER_DATA_DIR) / bank_code / "card_feature" / file_name / f"{file_name}.jsonl"
        logger.info(f"Find the feature jsonl file at {feature_jsonl_path}.")
        
        rag = RAG(
            vector_storage_path=global_settings.VECTOR_STORE_DIR,
            collection_name=global_settings.VECTOR_COLLECTION_NAME
        )
        asyncio.run(rag.chunk_images_to_vecdb(
            feature_jsonl_path,
            file_name,
            card_name,
            bank_code,
            batch_size=15,
        ))
        write_job_status(job_status_txt_path, job_id, True)

        logger.info(f"Card information has been saved.")

        
    except Exception as e:
        raise

def write_job_status(txt_path: str, job_id: str, status: bool):
    Path(txt_path).touch(exist_ok=True)

    with open(txt_path, "r+", encoding="utf-8") as f:
        lines = f.readlines()
        f.seek(0)

        found = False
        for i, line in enumerate(lines):
            if line.startswith(job_id):
                lines[i] = f"{job_id},{status}"
                found = True
                break
        
        if not found:
            lines.append(f"{job_id},{status}")

        f.write("\n".join(lines))


### API endpoints ###
@router.post("/card-list")
async def crawl_card_list(request: CardListRequest):
    """ 
    Start crawling all card information from the provided URL. 
    """
    job_id = str(uuid4())
    list_id = f"list-{uuid4().hex}"

    try:
        p = multiprocessing.Process(target=run_card_list_spider, args=(CONFIG_PATH, request.bank_code, request.url, list_id))
        p.start()        

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, list_id=list_id)
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
async def get_card_list(list_id: str):
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
async def crawl_card_info(request: CardFeatureRequest):
    """
    Start crawling card feature information from the provided URL.
    And save the result to the vector database.
    """
    job_id = str(uuid4())
    card_id = f"card-{uuid4().hex}"

    try:
        # write job status
        job_status_txt_path = f"{global_settings.CRAWLER_DATA_DIR}/feature_job_status.txt"
        write_job_status(job_status_txt_path, job_id, False)

        # start crawling
        p = multiprocessing.Process(
            target=run_card_feature_spider, 
            args=(
                CONFIG_PATH, 
                request.bank_code, 
                request.card_name, 
                request.card_url, 
                card_id, 
                job_id, 
                job_status_txt_path
            )
        )
        p.start()        

        response = BaseResponse[JobIDResponse](
            status="success",
            message="The crawling job has been submitted successfully.",
            data=JobIDResponse(job_id=job_id, card_id=card_id)
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


@router.get("/card-feature/{job_id}/status")
async def get_card_info(job_id: str):
    try:
        logger.info(f"Query job status: {job_id}")

        job_status_txt_path = f"{global_settings.CRAWLER_DATA_DIR}/feature_job_status.txt"

        with open(job_status_txt_path, "r") as f:
            for line in f:
                fjob_id, fjog_status = line.strip().split(",")
                if fjob_id == job_id:
                    response = BaseResponse[CardFeatureResponse](
                        status="success",
                        message="Query job status successfully.",
                        data=CardFeatureResponse(job_status=fjog_status)
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

