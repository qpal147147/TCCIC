import asyncio
from pathlib import Path

import scrapy
from scrapy.http.response.html import HtmlResponse
from playwright.async_api import Page, Locator, TimeoutError ,Error as PlaywrightError
from twisted.python.failure import Failure

from app.crawler.tccic.items import FeatureItem
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
        self.feature_config = BankCrawlerConfig(**get_config(config_path)).get_bank_config(bank_code).get_feature_config(card_url)

    def parse(self, response: HtmlResponse):
        if self.feature_config is None:
            self.logger.error(f"No bank config found for bank code: {self.bank_code}")
            return
        
        self.logger.info(f"Card code: {self.feature_config.card_code}")

        yield scrapy.Request(
            url=response.url,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                # "playwright_context_kwargs": {
                #     "viewport": {
                #         "width": 1280,
                #         "height": 1080,
                #     }
                # }
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
            if self.feature_config.cookie_button is not None:
                cookie_button = page.locator(f"xpath={self.feature_config.cookie_button}")
                await self.click_button(cookie_button)

            # scroll to the bottom to avoid missing content
            await self.scroll_to_bottom(page)
            
            # screenshot the main page
            await page.screenshot(path=(image_dir / f"main.png"), full_page=True)
            yield FeatureItem(page_url=response.url, image_path=str(image_dir / f"main.png"))

            if self.feature_config.focus is None:
                self.logger.warning(f"No focus config found for bank code: {self.bank_code}")
                return
            
            for i, focus_item in enumerate(self.feature_config.focus):
                all_focus_content_locators = page.locator(f"xpath={focus_item.content}")

                if await all_focus_content_locators.count() == 0:
                    self.logger.warning(f"The content xpath: {focus_item.content} does not exist in page: {response.url}.")
                    continue

                for j, focus_content_locator in enumerate(await all_focus_content_locators.all()):
                    # get all links in the content
                    all_link_locators = await focus_content_locator.locator(f"xpath={focus_item.link}").all()

                    self.logger.info(f"Found {len(all_link_locators)} links in content: {focus_item.content}, {j+1}th.")

                    for k, link_locator in enumerate(all_link_locators):
                        image_path = str(image_dir / f"{i}{j}{k}.png")
                        self.logger.info(f"Processing link {k+1}...")
                        
                        if not await link_locator.is_enabled(timeout=1000):
                            self.logger.warning(f"The link {k} is disabled, skipping click.")
                            continue

                        if not await link_locator.is_visible(timeout=1000):
                            self.logger.warning(f"The link {k} is hidden, skipping click.")
                            continue

                        original_url = page.url.split("#")[0]
                        new_page = None
                        try:
                            async with page.context.expect_page(timeout=3000) as new_page_info:
                                # await focus_content_locator.wait_for(timeout=500)
                                await link_locator.highlight()
                                await link_locator.evaluate("el => el.click()")
                                # await link_locator.click(force=True, timeout=3000)
                        
                            # Case 1: Open a new page
                            new_page = await new_page_info.value
                            self.logger.info(f"catching new page: {new_page.url}.")
                            await new_page.wait_for_load_state("load")

                            await new_page.screenshot(path=image_path, full_page=True)
                            yield FeatureItem(page_url=new_page.url, image_path=image_path)

                        except TimeoutError:
                            # process the current page
                            self.logger.info("New page not found, process the current page.")
                            await page.wait_for_load_state("load")
                            
                            if page.url.split("#")[0] != original_url:
                                # Case 2: Current page redirection
                                self.logger.info(f"Redirect to new URL: {page.url}.")
                                await page.screenshot(path=image_path, full_page=True)
                                yield FeatureItem(page_url=page.url, image_path=image_path)

                                await page.go_back(wait_until="load")

                                # self.logger.info("Retrieve links from the page...")
                                # focus_content_locator = page.locator(f"xpath={focus_content_locator}")
                                # all_link_locators = await focus_content_locator.locator(f"xpath={self.feature_config.link_button}").all()
                                # self.logger.info(f"Reacquired {len(all_link_locators)} links.")
                            else:
                                # Case 3: Current page update
                                self.logger.info(f"The page is currently updated, but the URL has not changed.")
                                screenshot_flag = False

                                if self.feature_config.sub_focus_content is not None:
                                    for sub_focus_content_xpath in self.feature_config.sub_focus_content:
                                        all_sub_focus_content_locator = page.locator(f"xpath={sub_focus_content_xpath}")

                                        for sub_focus_content_locator in await all_sub_focus_content_locator.all():
                                            if await sub_focus_content_locator.is_visible():
                                                await sub_focus_content_locator.screenshot(path=image_path)
                                                screenshot_flag = True
                                                break

                                        if screenshot_flag:
                                            break
                                
                                if not screenshot_flag:
                                    await focus_content_locator.screenshot(path=image_path)
                                
                                if self.feature_config.close_button is not None:
                                    close_button = page.locator(f"xpath={self.feature_config.close_button}")
                                    await self.click_button(close_button)
                                    await page.wait_for_timeout(500)

                                yield FeatureItem(page_url=page.url, image_path=image_path)
                                
                        except PlaywrightError as e:
                            self.logger.error(f"A playwright error occurred while processing link {i+1}: {e}")

                            # Try refreshing the page
                            await page.reload(wait_until="load")

                            await self.scroll_to_bottom(page)
                            focus_content_locator = page.locator(f"xpath={focus_item.content}")
                            all_link_locators = await focus_content_locator.locator(f"xpath={focus_item.link}").all()

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

    
    async def scroll_to_bottom(self, page: Page) -> None:
        viewport_height = await page.evaluate("window.innerHeight")
        self.logger.debug(f"Viewport height: {viewport_height}px")

        total_height = await page.evaluate("document.body.scrollHeight")
        self.logger.debug(f"Total height: {total_height}px")

        step = int(viewport_height * 0.8) 
        for y_pos in range(0, total_height, step):
            self.logger.debug(f"Scrolling to Y position: {y_pos}")
            await page.evaluate(f"window.scrollTo(0, {y_pos})")
            await page.wait_for_timeout(500)

        try:
            await page.wait_for_load_state("load", timeout=3000)
        except TimeoutError:
            self.logger.debug("Network is idle within 3 seconds, but scrolling is complete. Continuing operation.")


    async def click_button(self, locator: Locator) -> None:
        for locator in await locator.all():
            if await locator.is_visible(timeout=1000):
                await locator.click(timeout=1000)
                break