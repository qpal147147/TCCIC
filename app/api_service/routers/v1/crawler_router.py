import sys
import logging
import multiprocessing
from pathlib import Path

from fastapi import APIRouter
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings

from app.crawler.tccic.spiders.cards_spider import CardSpider
from app.crawler.tccic import settings as project_settings
from app.configs.settings import global_settings
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
        process.crawl(CardSpider, config_path=config_path, bank_code=bank_code, url=url)
        process.start()
    except Exception as e:
        logger.error(f"Error occurred while running the spider: {e}")

@router.get("/cards")
async def start_crawling(bank_code: str, url: str):
    """ 
    Start crawling all card information from the provided URL. 
    """
    logger.info(f"Start crawling all card information from {url}, bank code: {bank_code}")
    
    result_queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=run_spider, args=(CONFIG_PATH, bank_code, url, result_queue))
    p.start()
    p.join()

    return "OK"