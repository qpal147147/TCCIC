"""
PageInteractor: encapsulates all Playwright interactions for the card-feature spider.

Responsibilities
----------------
- Cookie banner dismissal
- Full-page scrolling and main-page screenshot
- Focus-area iteration and per-link click orchestration

All click-outcome detection and screenshot logic is delegated to click_handlers.py.
The spider itself is reduced to a thin Scrapy lifecycle wrapper around this class.
"""

import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

from playwright.async_api import Locator, Page, TimeoutError, Error as PlaywrightError

from app.crawler.content_hash import freeze_animations
from app.crawler.tccic.items import FeatureItem
from app.crawler.schemas.bank_config import BankConfig, FeatureConfig, FocusItem
from app.crawler.click_handlers import (
    ClickResult,
    capture_region,
    click_and_capture,
    _click_button,
)


def _feature_item(result: ClickResult) -> FeatureItem:
    """Build a FeatureItem, leaving the fingerprint fields empty if it could not be taken."""
    fingerprint = result.fingerprint
    return FeatureItem(
        page_url=result.page_url,
        image_path=result.image_path,
        content_hash=fingerprint.content_hash if fingerprint else None,
        text_len=fingerprint.text_len if fingerprint else None,
        img_count=fingerprint.img_count if fingerprint else None,
    )


class PageInteractor:
    """
    Orchestrates all Playwright page interactions for a single card-feature crawl.

    Parameters
    ----------
    page           : Active Playwright page opened at the card URL.
    feature_config : Crawl rules matched to this card (via card_code substring).
    bank_config    : Parent bank config; used for cookie_button fallback resolution.
    image_dir      : Directory where screenshot files will be saved.
                     Created by CardFeaturePipeline.open_spider() before this runs.
    logger         : Logger forwarded from the calling spider.
    """

    def __init__(
        self,
        page: Page,
        feature_config: FeatureConfig,
        bank_config: BankConfig,
        image_dir: Path,
        logger: logging.Logger,
    ):
        self._page = page
        self._feature_config = feature_config
        self._bank_config = bank_config
        self._image_dir = image_dir
        self._logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_cookie_banner(self) -> None:
        """
        Dismiss the cookie-consent banner if a selector is configured.
        Resolves the selector via per-card override → bank-level default fallback.
        """
        selector = self._feature_config.effective_cookie_button(self._bank_config)
        if not selector:
            return
        self._logger.info("Clicking cookie banner.")
        cookie_btn = self._page.locator(f"xpath={selector}")
        await _click_button(cookie_btn)

    async def freeze_animations(self) -> None:
        """
        Stop animations and transitions before anything is captured, so a
        screenshot shows the page at rest rather than mid-slide.
        """
        await freeze_animations(self._page, self._logger)

    async def capture_main_page(self) -> FeatureItem:
        """
        Scroll to the bottom to trigger lazy-loaded content, then take a
        full-page screenshot saved as 'main.png' in the image directory.
        """
        await self._scroll_to_bottom(self._page)
        image_path = str(self._image_dir / "main.png")
        fingerprint = await capture_region(self._page, None, image_path, self._logger)
        self._logger.info(f"Main page captured: {image_path} (fingerprint: {fingerprint}).")
        return _feature_item(ClickResult(self._page.url, image_path, fingerprint))

    async def process_all_focus_areas(self) -> AsyncGenerator[FeatureItem, None]:
        """
        Iterate over every focus area defined in feature_config and yield
        a FeatureItem for each successfully captured screenshot.
        """
        if not self._feature_config.focus:
            self._logger.warning("No focus areas configured; only main page was captured.")
            return

        for focus_index, focus_item in enumerate(self._feature_config.focus):
            async for result in self._process_focus_area(self._page, focus_item, str(focus_index)):
                yield _feature_item(result)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _process_focus_area(
        self,
        page: Page,
        focus_item: FocusItem,
        label: str,
    ) -> AsyncGenerator[ClickResult, None]:
        """
        For one focus area on `page`: locate all content elements, then click
        every configured link within each element and capture the outcome. With
        no link configured, each content element is captured as it is.

        Image naming: {label}_{content_idx}_{link_idx}.png, or {label}_{content_idx}.png
        without a link. label is the focus index, prefixed with the opening link's
        label inside page_focus (e.g. 1_0_0-2). Underscores prevent collisions
        (e.g. i=1,j=0 vs i=10).

        Error recovery: if a Playwright error occurs mid-loop the page is
        reloaded and the remaining links in that content element are skipped,
        because all existing locators are stale after a reload.
        """
        if not focus_item.content:
            self._logger.warning(f"Focus[{label}]: content XPath is empty, skipping.")
            return

        content_locators = await page.locator(f"xpath={focus_item.content}").all()
        if not content_locators:
            self._logger.warning(
                f"Focus[{label}]: XPath '{focus_item.content}' matched nothing on {page.url}."
            )
            return

        self._logger.info(f"Focus[{label}]: found {len(content_locators)} content element(s).")

        for content_idx, content_locator in enumerate(content_locators):
            if not focus_item.link:
                result = await self._capture_content(page, content_locator, f"{label}_{content_idx}")
                if result:
                    yield result
                continue

            link_locators = await content_locator.locator(f"xpath={focus_item.link}").all()
            self._logger.info(
                f"Focus[{label}][{content_idx}]: found {len(link_locators)} link(s)."
            )

            for link_idx, link_locator in enumerate(link_locators):
                link_label = f"{label}_{content_idx}_{link_idx}"
                image_path = str(self._image_dir / f"{link_label}.png")

                if not await link_locator.is_enabled(timeout=1000):
                    self._logger.warning(f"Focus[{link_label}] link is disabled — skipping.")
                    continue

                if not await link_locator.is_visible(timeout=1000):
                    self._logger.warning(f"Focus[{link_label}] link is hidden — skipping.")
                    continue

                capture_opened_page = None
                if focus_item.page_focus:
                    async def capture_opened_page(opened, items=focus_item.page_focus, at=link_label):
                        return await self._capture_opened_page(opened, items, at)

                try:
                    for result in await click_and_capture(
                        page,
                        link_locator,
                        focus_item,
                        content_locator,
                        image_path,
                        self._logger,
                        capture_opened_page,
                    ):
                        yield result

                except PlaywrightError as e:
                    self._logger.error(
                        f"Focus[{link_label}] raised a Playwright error: {e}. Reloading page "
                        "and skipping remaining links in this content block."
                    )
                    await page.reload(wait_until="load")
                    await freeze_animations(page, self._logger)  # a reload drops the frozen-animation CSS
                    await self._scroll_to_bottom(page)
                    break  # All locators are stale after reload

    async def _capture_content(self, page: Page, locator: Locator, label: str) -> Optional[ClickResult]:
        """Capture one content element as it is (a focus area without a link)."""
        image_path = str(self._image_dir / f"{label}.png")
        try:
            if not await locator.is_visible(timeout=1000):
                self._logger.warning(f"Focus[{label}] content is hidden — skipping.")
                return None
            fingerprint = await capture_region(page, locator, image_path, self._logger)
        except PlaywrightError as e:
            self._logger.error(f"Focus[{label}] could not be captured: {e}")
            return None
        return ClickResult(page.url, image_path, fingerprint)

    async def _capture_opened_page(
        self, page: Page, focus_items: list[FocusItem], label: str
    ) -> list[ClickResult]:
        """
        Apply page_focus to a page a link opened, in place of its full-page
        screenshot. Falls back to the full page if page_focus captured nothing,
        so a changed page is never silently lost.
        """
        self._logger.info(f"Focus[{label}]: applying page_focus to {page.url}.")
        await self._scroll_to_bottom(page)

        results = []
        for index, focus_item in enumerate(focus_items):
            async for result in self._process_focus_area(page, focus_item, f"{label}-{index}"):
                results.append(result)

        if not results:
            self._logger.warning(
                f"Focus[{label}]: page_focus captured nothing on {page.url}; "
                "falling back to a full-page screenshot."
            )
            image_path = str(self._image_dir / f"{label}.png")
            fingerprint = await capture_region(page, None, image_path, self._logger)
            results.append(ClickResult(page.url, image_path, fingerprint))
        return results

    async def _scroll_to_bottom(self, page: Page) -> None:
        """
        Incrementally scroll to the page bottom so lazy-loaded content renders
        before a screenshot is taken. Waits briefly at each step.
        """
        viewport_height = await page.evaluate("window.innerHeight")
        total_height = await page.evaluate("document.body.scrollHeight")
        step = int(viewport_height * 0.8)

        for y_pos in range(0, total_height, step):
            await page.evaluate(f"window.scrollTo(0, {y_pos})")
            await page.wait_for_timeout(500)

        try:
            await page.wait_for_load_state("load", timeout=3000)
        except TimeoutError:
            self._logger.debug("Page load timed out after scrolling; continuing anyway.")

        # Lazy-loaded images finish arriving after 'load', and an image still in
        # flight is both a worse screenshot and a different fingerprint. Pages
        # that poll in the background never go idle, so this is best-effort.
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except TimeoutError:
            self._logger.debug("Network did not go idle after scrolling; continuing anyway.")
