import logging
from fastapi import APIRouter
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from app.crawler.tccic.spiders.cards_spider import CardSpider

logging.getLogger(__name__)
router = APIRouter()
CONFIG_PATH = "./app/configs/banks.yaml"


@router.get("/cards")
def start_crawling(url: str):
    logging.info(f"Start crawling all card information from {url}.")
    
    process = CrawlerProcess(get_project_settings())
    process.crawl(CardSpider, config_path=CONFIG_PATH, url=url)
    process.start()

    return "OK"