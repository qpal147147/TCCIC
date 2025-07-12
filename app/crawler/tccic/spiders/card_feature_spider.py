import asyncio
from pathlib import Path

import scrapy
from scrapy.http.response.html import HtmlResponse
from playwright.async_api import Page, TimeoutError ,Error as PlaywrightError
from twisted.python.failure import Failure

from app.utils.config_utils import get_config
from app.crawler.schemas.bank_config import BankCrawlerConfig
from app.configs.global_settings import global_settings

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
        if self.bank_config is None:
            self.logger.error(f"No bank config found for bank code: {self.bank_code}")
            return
        
        yield scrapy.Request(
            url=response.url,
            meta={
                "playwright": True,
                "playwright_include_page": True,
            },
            callback=self.parse_dynamic_page,
            errback=self.errback_httpbin,
            dont_filter=True
        )
    
    async def parse_dynamic_page(self, response: HtmlResponse):
        page: Page = response.meta.get("playwright_page")
        if not page:
            self.logger.error("Playwright page object not found in meta!")
            return
        
        image_dir = Path(global_settings.CRAWLER_DATA_DIR) / f"{self.bank_code}" / "card_feature" / self.file_name
        try:
            # detect cookie button and click
            cookie_button = page.locator("xpath=//button[contains(@class, 'cookie')]")
            if await cookie_button.is_visible(timeout=1000):
                await cookie_button.click(timeout=1000)
                await page.wait_for_timeout(500) 

            # screenshot the main page
            await page.screenshot(path=(image_dir / f"main.png"), full_page=True)

            for i, card_content_xpath in enumerate(self.bank_config.xpaths.card.content):
                all_content_locators = page.locator(card_content_xpath)

                if await all_content_locators.count() == 0:
                    self.logger.error(f"The content xpath: {card_content_xpath} does not exist in page: {response.url}.")
                    return

                for j, content_locator in enumerate(await all_content_locators.all()):
                    # get all links in the content
                    all_link_locators = await content_locator.locator("xpath=.//a[@href and not(contains(@href, 'mailto:'))]").all()
                    self.logger.info(f"Found {len(all_link_locators)} links in content: {card_content_xpath}, {j+1}th.")

                    for k, link_locator in enumerate(all_link_locators):
                        self.logger.info(f"Processing link {k}...")
                        
                        if not await link_locator.is_enabled(timeout=1000):
                            self.logger.warning(f"The link {k} is disabled, skipping click.")
                            continue

                        if not await link_locator.is_visible(timeout=1000):
                            self.logger.warning(f"The link {k} is hidden, skipping click.")
                            continue

                        original_url = page.url
                        new_page = None
                        try:
                            async with page.context.expect_page(timeout=3000) as new_page_info:
                                # await link_locator.scroll_into_view_if_needed(timeout=2000)
                                # await content_locator.wait_for(timeout=500)
                                await link_locator.highlight()
                                await link_locator.click(force=True, timeout=3000)
                        
                            # Case 1: Open a new page
                            new_page = await new_page_info.value
                            self.logger.info(f"catching new page: {new_page.url}.")
                            await new_page.wait_for_load_state("load")
                            await new_page.screenshot(path=(image_dir / f"{i}{j}{k}.png"), full_page=True)
                        
                        except TimeoutError:
                            # process the current page
                            self.logger.info("New page not found, process the current page.")
                            await page.wait_for_load_state("load")
                            
                            if page.url != original_url:
                                # Case 2: Current page redirection
                                self.logger.info(f"Redirect to new URL: {page.url}.")
                                await page.screenshot(path=(image_dir / f"{i}{j}{k}.png"), full_page=True)

                                await page.go_back(wait_until="load")

                                self.logger.info("Retrieve links from the page...")
                                content_locator = page.locator(card_content_xpath)
                                all_link_locators = await content_locator.locator("xpath=.//a[@href and not(contains(@href, 'mailto:'))]").all()
                                self.logger.info(f"Reacquired {len(all_link_locators)} links.")
                        
                            else:
                                # Case 3: Current page update
                                self.logger.info(f"The page is currently updated, but the URL has not changed.")
                                await content_locator.screenshot(path=(image_dir / f"{i}{j}{k}.png"))
                                
                        except PlaywrightError as e:
                            self.logger.error(f"A playwright error occurred while processing link {i+1}: {e}")

                            # Try refreshing the page
                            await page.reload(wait_until="load")
                            content_locator = page.locator(card_content_xpath)
                            all_link_locators = await content_locator.locator("xpath=.//a[@href and not(contains(@href, 'mailto:'))]").all()

                        finally:
                            if new_page:
                                await new_page.close()

        except Exception as e:
            self.logger.error(f"Error occurred while running the playwright: {e}.")

        finally:
            await page.close()


    def errback_httpbin(self, failure: Failure):
        url = failure.request.url
        err_msg = failure.getErrorMessage()

        self.logger.error(f"{err_msg} <GET {url}>")