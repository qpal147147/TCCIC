import scrapy
from scrapy.http.response.html import HtmlResponse

from app.utils.config_utils import get_config
from app.crawler.schemas.bank_config import BankCrawlerConfig

class CardFeatureSpider(scrapy.Spider):
    name = 'card_feature_spider'

    def __init__(self, config_path: str, bank_code: str, card_name: str, card_url: str, file_name: str, *args, **kwargs):
        super(CardFeatureSpider, self).__init__(*args, **kwargs)
        self.start_urls = [card_url]
        self.bank_code = bank_code
        self.card_name = card_name
        self.file_name = file_name
        self.bank_config = BankCrawlerConfig(**get_config(config_path)).get_bank_config(bank_code)

    def parse(self, response: HtmlResponse):
        self.logger.info(f"Parsing card feature information from '{self.card_name}'.")