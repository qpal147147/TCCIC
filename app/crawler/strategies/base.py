"""
Default crawl strategy for card-list spiders.

BankStrategy provides a config-driven implementation that covers the majority of
Taiwanese bank websites. Banks with exceptional behaviour (e.g. non-standard pagination)
should subclass BankStrategy and override only the methods that differ.
"""

import logging
from typing import Generator, AsyncGenerator

import scrapy
from scrapy.http import HtmlResponse, Request
from playwright.async_api import Page, Frame

from app.crawler.schemas.bank_config import BankConfig
from app.crawler.tccic.items import CardItem


class BankStrategy:
    """
    Config-driven crawl strategy for card-list pages.

    Methods
    -------
    get_tab_requests   -- Yield Scrapy Requests for each tab on a static listing page.
    parse_cards        -- Parse CardItems from an HTML response using XPath selectors.
    navigate_dynamic_page -- Async-generator that clicks through tabs on a JS-rendered
                             page and yields a mock HtmlResponse for each tab's content.
    """

    def __init__(self, bank_config: BankConfig, logger: logging.Logger | None = None):
        self.config = bank_config
        self.logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Static page helpers
    # ------------------------------------------------------------------

    def get_tab_requests(
        self,
        response: HtmlResponse,
        callback,
        errback,
    ) -> Generator[Request, None, None]:
        """
        Yield one Scrapy Request per tab link found via the configured XPath.
        If no tab_link XPath is configured, yield a single request for the
        current URL so the listing page itself is parsed as a tab.
        """
        if not self.config.xpaths.tab_link:
            # No tab structure — treat the current page as the only "tab".
            self.logger.warning("No tab_link XPath configured; crawling the initial page directly.")
            yield response.follow(
                url=response.url,
                callback=callback,
                errback=errback,
                dont_filter=True,
            )
            return

        tab_links = response.xpath(self.config.xpaths.tab_link).getall()
        if not tab_links:
            self.logger.error(
                f"tab_link XPath '{self.config.xpaths.tab_link}' matched nothing on {response.url}"
            )
            return

        self.logger.info(f"Found {len(tab_links)} tab(s) on {response.url}")
        for link in tab_links:
            yield response.follow(
                url=link,
                callback=callback,
                errback=errback,
                dont_filter=True,
            )

    def parse_cards(self, response: HtmlResponse) -> Generator[CardItem, None, None]:
        """
        Extract CardItems from an HTML response using the bank's XPath selectors.
        Cards without a resolvable URL are skipped with a warning.
        """
        divisions = response.xpath(self.config.xpaths.division)
        if not divisions:
            self.logger.error(
                f"division XPath '{self.config.xpaths.division}' matched nothing on {response.url}"
            )
            return

        self.logger.info(f"Found {len(divisions)} card division(s) on {response.url}")
        for division in divisions:
            title = division.xpath(self.config.xpaths.card.title).get()
            if not title:
                continue
            title = title.strip()

            # Special sentinel: use the current tab URL as the card URL.
            if self.config.xpaths.card.url == "tab_url":
                url = response.url
            else:
                url = division.xpath(self.config.xpaths.card.url).get()

            if not url:
                self.logger.warning(f"Card '{title}' has no URL — skipping.")
                continue

            self.logger.info(f"Found card: {title}")
            yield CardItem(
                bank_name=self.config.bank_name,
                bank_code=self.config.bank_code,
                page_url=response.url,
                card_title=title,
                card_url=response.urljoin(url),
            )

    # ------------------------------------------------------------------
    # Dynamic page helper
    # ------------------------------------------------------------------

    async def navigate_dynamic_page(
        self,
        page: Page,
        response: HtmlResponse,
    ) -> AsyncGenerator[HtmlResponse, None]:
        """
        Async generator for JS-rendered listing pages.

        Waits for the page to settle, then iterates through tab elements by
        clicking each one and yielding a mock HtmlResponse built from the
        resulting DOM. If no tab_link XPath is configured, the current page
        content is yielded once without any clicking.

        Tabs are re-queried before each click to guard against stale DOM
        references caused by Playwright's dynamic rendering.
        """
        await page.wait_for_timeout(self.config.crawl_policy.initial_wait_ms)

        if not self.config.xpaths.tab_link:
            # No tab structure — yield the current page content directly.
            self.logger.info("No tab_link XPath configured; reading current page content.")
            html = await page.content()
            yield HtmlResponse(
                url=page.url,
                body=html,
                encoding="utf-8",
                request=response.request,
            )
            return

        # Resolve the correct frame: check for an iframe first, then fall
        # back to the top-level page.
        frame: Page | Frame = page
        tab_elements = []

        self.logger.info("Checking for an <iframe> element...")
        frame_element = await page.query_selector("iframe")
        if frame_element:
            inner_frame = await frame_element.content_frame()
            if inner_frame:
                tab_elements = await inner_frame.query_selector_all(
                    self.config.xpaths.tab_link
                )
                if tab_elements:
                    self.logger.info(f"Found {len(tab_elements)} tab(s) inside iframe.")
                    frame = inner_frame

        if not tab_elements:
            tab_elements = await page.query_selector_all(self.config.xpaths.tab_link)
            self.logger.info(f"Found {len(tab_elements)} tab(s) in page.")

        for i in range(len(tab_elements)):
            # Re-query every iteration to avoid stale element references after
            # DOM mutations triggered by the previous tab click.
            current_tabs = await frame.query_selector_all(self.config.xpaths.tab_link)
            if i >= len(current_tabs):
                self.logger.warning(f"Tab index {i} no longer exists in DOM — stopping.")
                break

            tab = current_tabs[i]
            tab_text = (await tab.text_content() or "").strip()
            self.logger.info(f"Clicking tab [{i}]: '{tab_text}'")

            await tab.click(timeout=20000, force=True)
            await page.wait_for_timeout(self.config.crawl_policy.tab_wait_ms)

            html = await frame.content()
            yield HtmlResponse(
                url=frame.url,
                body=html,
                encoding="utf-8",
                request=response.request,
            )
