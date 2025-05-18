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
        self.bank_crawler_config = BankCrawlerConfig(**get_config(config_path))

    def parse(self, response: HtmlResponse):
        # get the corresponding bank config from the url
        bank_config = next(
            (
                bank_config
                for bank_config in self.bank_crawler_config.banks
                if bank_config.bank_code in response.url
            ),
            None,
        )

        if bank_config is None:
            logging.error(f"No bank config found for url: {response.url}")
            return

        # get the tab URL from the page
        tab_links = response.xpath(bank_config.xpaths.tab_links).getall()
        
        item = CardsItem()
        yield item