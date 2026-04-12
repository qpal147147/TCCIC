"""
Card-feature spider.

Crawls a single credit card page and yields FeatureItems (page URL + screenshot path)
for each captured image. All Playwright interaction logic is delegated to PageInteractor;
this spider is responsible only for the Scrapy request/yield lifecycle.
"""

from pathlib import Path

import scrapy
from scrapy.http import HtmlResponse
from playwright.async_api import Page
from twisted.python.failure import Failure

from app.crawler.tccic.items import FeatureItem
from app.utils.config_utils import get_config
from app.crawler.schemas.bank_config import BankCrawlerConfig
from app.configs.global_settings import global_settings
from app.crawler.page_interactor import PageInteractor


class CardFeatureSpider(scrapy.Spider):
    name = "card_feature_spider"

    def __init__(
        self,
        config_path: str,
        bank_code: str,
        card_name: str,
        card_url: str,
        file_name: str,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.start_urls = [card_url]
        self.bank_code = bank_code
        self.card_name = card_name
        self.file_name = file_name
        self._image_dir = Path(global_settings.CRAWLER_DATA_DIR) / bank_code / "card_feature" / file_name

        bank_config = BankCrawlerConfig(**get_config(config_path)).get_bank_config(bank_code)
        if bank_config is None:
            raise ValueError(f"No configuration found for bank_code='{bank_code}'")

        self._bank_config = bank_config
        self._feature_config = bank_config.get_feature_config(card_url)

    # ------------------------------------------------------------------
    # Scrapy callbacks
    # ------------------------------------------------------------------

    async def start(self):
        """
        Start with a Playwright browser request directly, bypassing the plain
        HTTP hop that would be rejected with 403 by bot-detection systems.
        """
        for url in self.start_urls:
            yield scrapy.Request(
                url=url,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                },
                callback=self.parse_dynamic_page,
                errback=self.errback_httpbin,
            )

    async def parse_dynamic_page(self, response: HtmlResponse):
        """
        Playwright callback: delegates all page interaction to PageInteractor
        and yields FeatureItems for every captured screenshot.
        """
        page: Page = response.meta.get("playwright_page")
        if not page:
            self.logger.error("Playwright page object not found in response meta.")
            return

        if self._feature_config is None:
            self.logger.error(
                f"No feature config matched URL '{response.url}' "
                f"for bank_code='{self.bank_code}'."
            )
            await page.close()
            return

        interactor = PageInteractor(
            page=page,
            feature_config=self._feature_config,
            bank_config=self._bank_config,
            image_dir=self._image_dir,
            logger=self.logger,
        )

        try:
            await interactor.handle_cookie_banner()
            yield await interactor.capture_main_page()
            async for item in interactor.process_all_focus_areas():
                yield item
        except Exception as exc:
            self.logger.error(f"Unhandled error during feature crawl: {exc}")
        finally:
            await page.close()

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def errback_httpbin(self, failure: Failure):
        self.logger.error(f"{failure.getErrorMessage()} <GET {failure.request.url}>")
