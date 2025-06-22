import re
import scrapy
from scrapy.http.response.html import HtmlResponse
from scrapy_playwright.page import PageMethod
from playwright.async_api import Page
from twisted.python.failure import Failure

from app.crawler.tccic.items import CardsItem
from app.utils.config_utils import get_config
from app.crawler.schemas.bank_config import BankCrawlerConfig

class CardListSpider(scrapy.Spider):
    name = "card_list_spider"

    def __init__(self, config_path: str, bank_code: str, url: str, file_name: str, *args, **kwargs):
        super(CardListSpider, self).__init__(*args, **kwargs)
        self.start_urls = [url]
        self.bank_code = bank_code
        self.file_name = file_name
        self.bank_config = BankCrawlerConfig(**get_config(config_path)).get_bank_config(bank_code)

    def parse(self, response: HtmlResponse):
        if self.bank_config is None:
            self.logger.error(f"No bank config found for bank code: {self.bank_code}")
            return
        
        # get the tab URL from the page
        tab_links = []
        if self.bank_config.xpaths.tab_link is None:
            tab_links = [response.url]
            self.logger.warning(f"No tab xpath is set, so the initial page will be crawled.")
        elif not self.bank_config.is_dynamic:
            tab_links = response.xpath(self.bank_config.xpaths.tab_link).getall()
            self.logger.info(f"Found {len(tab_links)} tabs.")

        if len(tab_links) == 0 and not self.bank_config.is_dynamic:
            self.logger.error(f"No tab links found for url: {response.url}")
            return

        # get the card list from the page
        if self.bank_config.is_dynamic:
            self.logger.info("Current crawler mode is dynamic.")

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
        else:
            self.logger.info("Current crawler mode is static.")

            if self.bank_code == "yuantabank":
                # simulate a post request, since javascript doesn't work
                total_pages = response.css('form#form4paging input#pA::attr(value)').get()

                for i in range(int(total_pages)):
                    yield scrapy.FormRequest(
                        url=response.url,
                        formdata={
                            'pN': f"{i+1}",
                            'pA': total_pages,
                            'iA': response.css('form#form4paging input#iA::attr(value)').get(),
                            'creditcard_type': "",
                        },
                        callback=self.parse_static_page,
                        errback=self.errback_httpbin,
                    )
            else:
                for tab_link in tab_links:
                    yield response.follow(
                        url=tab_link,
                        callback=self.parse_static_page,
                        errback=self.errback_httpbin,
                        dont_filter=True
                    )

    async def parse_dynamic_page(self, response: HtmlResponse):
        page: Page = response.meta.get("playwright_page")
        if not page:
            self.logger.error("Playwright page object not found in meta!")
            return
        
        self.logger.info(f"Initial page loaded: {response.url}")
        try:
            await page.wait_for_timeout(10000)  # waiting for the page to load

            if self.bank_config.xpaths.tab_link:
                self.logger.info("Find all the tab elements...")
                tab_elements = []

                self.logger.info("Look for the `iframe` tag...")
                frame_element = await page.query_selector("iframe")
                if frame_element:
                    frame = await frame_element.content_frame()
                    if frame:
                        # await frame.wait_for_selector(self.bank_config.xpaths.tab_link, state='visible')
                        tab_elements = await frame.query_selector_all(self.bank_config.xpaths.tab_link)
                        self.logger.info(f"Found {len(tab_elements)} tabs in frame.")
                
                if not tab_elements:
                    self.logger.info("Look for the `xpath` from html...")
                    frame = page
                    tab_elements = await page.query_selector_all(self.bank_config.xpaths.tab_link)
                    self.logger.info(f"Found {len(tab_elements)} tabs in page.")

                # get the list of cards from each tab
                for i, tab in enumerate(tab_elements):
                    # Re-crawl elements to avoid invalid DOM caused by page jumps
                    tab = (await frame.query_selector_all(self.bank_config.xpaths.tab_link))[i]

                    button_text = (await tab.text_content()).strip()
                    self.logger.info(f"Clicking tag in iframe: '{button_text}'")

                    # await page.wait_for_load_state("networkidle", timeout=20000)
                    await tab.click(timeout=20000, force=True)
                    await page.wait_for_timeout(2000)

                    html = await frame.content()
                    mock_response_for_iframe = HtmlResponse(
                        url=frame.url,
                        body=html,
                        encoding='utf-8',
                        request=response.request
                    )

                    parsed_results = self.parse_static_page(mock_response_for_iframe)
                    if parsed_results:
                        for yielded_value in parsed_results:
                            yield yielded_value
            else:
                self.logger.info("No tabs is provided. Search cards directly from the current page.")

                html = await page.content()
                mock_response_for_page = HtmlResponse(
                    url=response.url,
                    body=html,
                    encoding='utf-8',
                    request=response.request
                )

                parsed_results = self.parse_static_page(mock_response_for_page)
                if parsed_results:
                        for yielded_value in parsed_results:
                            yield yielded_value

        except Exception as e:            
            webdriver_flag = await page.evaluate("navigator.webdriver")
            self.logger.debug(f"Is Robot: {webdriver_flag}")
            self.logger.error(f"{e}")
        finally:
            await page.close()
            return

    def parse_static_page(self, response: HtmlResponse):
        # get the card division from the list
        card_divisions = response.xpath(self.bank_config.xpaths.division)
        self.logger.info(f"Found {len(card_divisions)} card divisions from url: {response.url}")

        if len(card_divisions) == 0:
            self.logger.error(f"No card divisions found from url: {response.url}")
            return
        
        for card_div in card_divisions:
            card_title = card_div.xpath(f"{self.bank_config.xpaths.card.title}").get().strip()
            card_url = card_div.xpath(f"{self.bank_config.xpaths.card.url}").get()
            
            if self.bank_config.xpaths.card.url == "tab_url":
                card_url = response.url

            if card_url is None:
                self.logger.warning(f"The `{card_title}` card have no url and will be automatically skipped.")
                continue

            self.logger.info(f"Found card: {card_title}")
            yield CardsItem(
                bank_name = self.bank_config.bank_name,
                bank_code = self.bank_config.bank_code,
                page_url = response.url,
                card_title = card_title,
                card_url = response.urljoin(card_url)
            )

    def errback_httpbin(self, failure: Failure):
        url = failure.request.url
        err_msg = failure.getErrorMessage()

        self.logger.error(f"{err_msg} <GET {url}>")