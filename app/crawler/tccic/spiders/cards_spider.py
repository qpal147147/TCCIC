import scrapy
from scrapy.http.response.html import HtmlResponse
from twisted.python.failure import Failure

from app.crawler.tccic.items import CardsItem
from app.utils.config_utils import get_config
from app.configs.schemas import BankCrawlerConfig

class CardSpider(scrapy.Spider):
    name = "cardspider"

    def __init__(self, config_path: str, url: str, *args, **kwargs):
        super(CardSpider, self).__init__(*args, **kwargs)
        self.start_urls = [url]
        self.bank_crawler_config = BankCrawlerConfig(**get_config(config_path))
        self.bank_config = None

    def parse(self, response: HtmlResponse):
        # get the corresponding bank config from the url
        self.bank_config = next(
            (
                bank_config
                for bank_config in self.bank_crawler_config.banks
                if bank_config.bank_code in response.url
            ),
            None,
        )

        if self.bank_config is None:
            self.logger.error(f"No bank config found for url: {response.url}")
            return

        # get the tab URL from the page
        tab_links = response.xpath(self.bank_config.xpaths.tab_link).getall()
        self.logger.info(f"Found {len(tab_links)} tabs.")

        if len(tab_links) == 0:
            self.logger.error(f"No tab links found for url: {response.url}")
            return

        # get the card list from the page
        for tab_link in tab_links:
            yield response.follow(
                url=tab_link,
                callback=self.parse_tab,
                errback=self.errback_httpbin,
            )

    def parse_tab(self, response: HtmlResponse):
        # get the card division from the list
        card_divisions = response.xpath(self.bank_config.xpaths.division)
        self.logger.info(f"Found {len(card_divisions)} card divisions from url: {response.url}")

        if len(card_divisions) == 0:
            self.logger.error(f"No card divisions found from url: {response.url}")
            return
        
        for card_div in card_divisions:
            card_title = card_div.xpath(self.bank_config.xpaths.card.title).get()
            card_url = card_div.xpath(self.bank_config.xpaths.card.url).get()
            self.logger.info(f"Found card: {card_title}")

            yield CardsItem(
                bank_name = self.bank_config.bank_name,
                title = card_title,
                url = card_url,
            )

    def errback_httpbin(self, failure: Failure):
        url = failure.request.url
        err_msg = failure.getErrorMessage()

        self.logger.error(f"{err_msg} <GET {url}>")