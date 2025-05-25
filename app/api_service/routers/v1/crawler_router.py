import sys
import logging
import json
import multiprocessing
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from app.api_service.schemas.base import BaseResponse
from app.crawler.schemas.card_list import CardItem, CardPagesItem, BankCardListPageData
from app.crawler.tccic.spiders.card_list_spider import CardListSpider
from app.crawler.tccic import settings as project_settings
from app.configs.global_settings import global_settings
from app.utils.logger_setup import LOG_FORMAT, LOG_DIR, LOG_FILENAME

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "banks.yaml"
SCRAPY_PROJECT_PATH = PROJECT_ROOT / "crawler"
sys.path.append(str(SCRAPY_PROJECT_PATH))

router = APIRouter()

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

def run_spider(config_path: str, bank_code: str, url: str):
    """
    Initializes and runs the Scrapy spider in a separate process.
    This function is intended to be the target of a multiprocessing.Process.

    Args:
        spider_config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        target_url: The URL the spider should start crawling.
    """
    try:
        process = CrawlerProcess(SCRAPY_SETTINGS)
        process.crawl(CardListSpider, config_path=config_path, bank_code=bank_code, url=url)
        process.start()
    except Exception as e:
        logger.error(f"Error occurred while running the spider: {e}")

@router.get("/cards")
async def crawl_card_list(bank_code: str, url: str):
    """ 
    Start crawling all card information from the provided URL. 
    """
    logger.info(f"Start crawling all card information from {url}, bank code: {bank_code}")

    p = multiprocessing.Process(target=run_spider, args=(CONFIG_PATH, bank_code, url))
    p.start()
    p.join()

    logger.info(f"Crawling completed.")

    # read the JSONL file and return the data
    base_response = BaseResponse[BankCardListPageData]()
    try:
        crawler_file_path = f"{global_settings.CRAWLER_DATA_DIR}/{bank_code}/card_list.jsonl"
        
        # remove duplicates
        cleaned_item = []
        with open(crawler_file_path, "r") as f:
            cards = set()
            for line in f:
                json_data = json.loads(line)
                if json_data['card_url'] not in cards:
                    cards.add(json_data['card_url'])
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
        
        base_response.data = BankCardListPageData(
            bank_code=bank_code, 
            bank_name=bank_name, 
            pages=list(page_map.values())
        )

        base_response.status = "success"
        base_response.message = f"Successfully crawled all card information."
        return JSONResponse(content=base_response.model_dump(), status_code=200)
    except FileNotFoundError as e:
        logger.error(f"File not found: {crawler_file_path}")

        base_response.status = "fail"
        base_response.message = f"Error occurred while reading the JSONL file."
        base_response.error = f"{e}"
        base_response.data = None
        return JSONResponse(content=base_response.model_dump(), status_code=500)
    except Exception as e:
        logger.error(f"Error occurred while reading the JSONL file: {e}")

        base_response.status = "fail"
        base_response.message = f"Error occurred while reading the JSONL file."
        base_response.error = f"{e}"
        base_response.data = None
        return JSONResponse(content=base_response.model_dump(), status_code=500)