"""
Card-list spider.

Crawls the card-listing page of a single bank and yields CardItems.
All bank-specific logic (tab navigation, card parsing, pagination) is
delegated to a BankStrategy instance resolved at construction time.
The spider itself is responsible only for the Scrapy request/yield
lifecycle and Playwright page management.
"""

import scrapy
from scrapy.http.response.html import HtmlResponse
from playwright.async_api import Page
from twisted.python.failure import Failure

from app.crawler.tccic.items import CardItem
from app.utils.config_utils import get_config
from app.crawler.schemas.bank_config import BankCrawlerConfig
from app.crawler.strategies.registry import get_strategy


class CardListSpider(scrapy.Spider):
    name = "card_list_spider"

    def __init__(
        self,
        config_path: str,
        bank_code: str,
        url: str,
        file_name: str,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.start_urls = [url]
        self.file_name = file_name
        self.bank_code = bank_code

        bank_config = BankCrawlerConfig(**get_config(config_path)).get_bank_config(bank_code)
        if bank_config is None:
            raise ValueError(f"No configuration found for bank_code='{bank_code}'")

        # Resolve the appropriate strategy; passes the spider logger so all
        # strategy log messages appear under this spider's name.
        self.strategy = get_strategy(bank_config, self.logger)

    # ------------------------------------------------------------------
    # Scrapy callbacks
    # ------------------------------------------------------------------

    def start_requests(self):
        """
        Override Scrapy's default start_requests so that dynamic-mode banks
        launch a Playwright browser directly for the first request, bypassing
        the plain HTTP hop that would otherwise be rejected with 403/4xx by
        bot-detection systems before parse() is ever called.
        """
        for url in self.start_urls:
            if self.strategy.config.is_dynamic:
                self.logger.info("Dynamic mode — starting with Playwright request.")
                yield scrapy.Request(
                    url=url,
                    meta={
                        "playwright": True,
                        "playwright_include_page": True,
                    },
                    callback=self.parse_dynamic_page,
                    errback=self.errback_httpbin,
                )
            else:
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    errback=self.errback_httpbin,
                )

    def parse(self, response: HtmlResponse):
        """
        Entry point for static-mode banks only.
        Follows tab links derived from the bank's XPath configuration.
        """
        self.logger.info("Static mode — following tab links.")
        yield from self.strategy.get_tab_requests(
            response,
            callback=self.parse_static_page,
            errback=self.errback_httpbin,
        )

    async def parse_dynamic_page(self, response: HtmlResponse):
        """
        Playwright callback for JS-rendered listing pages.

        Delegates tab navigation to the strategy's async generator, then
        parses each yielded mock response for card items.
        """
        page: Page = response.meta.get("playwright_page")
        if not page:
            self.logger.error("Playwright page object not found in response meta.")
            return

        try:
            async for mock_response in self.strategy.navigate_dynamic_page(page, response):
                for item in self.strategy.parse_cards(mock_response):
                    yield item
        except Exception as exc:
            self.logger.error(f"Unhandled error during dynamic page crawl: {exc}")
        finally:
            await page.close()

    def parse_static_page(self, response: HtmlResponse):
        """Parse card items from a single static listing page (one tab)."""
        yield from self.strategy.parse_cards(response)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def errback_httpbin(self, failure: Failure):
        self.logger.error(f"{failure.getErrorMessage()} <GET {failure.request.url}>")
