import logging 

import scrapy
from scrapy.http.response.html import HtmlResponse

from app.crawler.tccic.items import CardsItem
from app.utils.config_utils import get_config
from app.configs.schemas import BankCrawlerConfig

logging.getLogger(__name__)

class CardSpider(scrapy.Spider):
    name = "cardspider"

    def __init__(self, config_path: str, url: str, *args, **kwargs):
        super(CardSpider, self).__init__(*args, **kwargs)
        self.start_urls = [url]
        self.bank_crawler_cfg = BankCrawlerConfig(**get_config(config_path))

    def parse(self, response: HtmlResponse):
        item = CardsItem()
        item.title = ""
        item.url = response.url

        yield item