"""
Click outcome handlers for the card-feature spider.

When a link is clicked on a card-feature page, one of three outcomes occurs:

  Case 1 — NewTab   : a new browser tab opens
  Case 2 — Redirect : the current page navigates to a new URL
  Case 3 — Popup    : the page content updates in-place (modal / popup appears)

Each outcome is handled by a dedicated class that can be subclassed per bank
to override specific behaviour without touching the orchestration logic.

Public API
----------
click_and_capture()  -- detects the click outcome and dispatches to the correct handler
_click_button()      -- utility: click the first visible element from a Locator set
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page, Locator, TimeoutError, Error as PlaywrightError

from app.crawler.content_hash import (
    Fingerprint,
    fingerprint_locator,
    fingerprint_page,
    freeze_animations,
)
from app.crawler.schemas.bank_config import FocusItem


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ClickResult:
    """
    What a single link click produced: the page URL, the saved screenshot, and
    the fingerprint of whatever region was captured. The fingerprint is None when
    the region could not be read.
    """
    page_url: str
    image_path: str
    fingerprint: Optional[Fingerprint] = None


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

async def _click_button(locator: Locator) -> None:
    """Click the first visible element matched by locator; silently skip if none found."""
    for btn in await locator.all():
        if await btn.is_visible(timeout=1000):
            await btn.click(timeout=1000)
            break

async def _screenshot_element(
    page: Page, locator: Locator, image_path: str, logger: logging.Logger
) -> None:
    """
    Screenshot an element in full by temporarily growing the viewport to fit it.

    Elements in fixed, internally scrolling containers (e.g. modals) only paint
    within the viewport, so a plain screenshot cuts off after the first screenful.
    The viewport is restored afterwards.
    """
    max_capture_height = 16000  # Upper limit for the enlarged viewport height, in px.
    viewport_margin = 100 # Extra px added to the viewport height as a buffer against rounding and layout shifts.
    viewport = page.viewport_size
    box = await locator.bounding_box()
    if viewport is None or box is None or box["height"] <= viewport["height"]:
        await locator.screenshot(path=image_path)
        return

    height = math.ceil(box["height"] + 2 * max(box["y"], 0)) + viewport_margin
    if height > max_capture_height:
        logger.warning(
            f"Element is {round(box['height'])}px tall; capturing only the first "
            f"{max_capture_height}px."
        )
        height = max_capture_height

    try:
        await page.set_viewport_size({"width": viewport["width"], "height": height})
        await page.wait_for_timeout(300)  # let the page re-lay out at the new size
        await locator.screenshot(path=image_path)
    finally:
        await page.set_viewport_size(viewport)
        await page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Outcome handlers
# ---------------------------------------------------------------------------

class NewTabHandler:
    """
    Case 1: clicking a link opens a new browser tab.

    Waits for the tab to finish loading, takes a full-page screenshot,
    then returns. The caller is responsible for closing the new tab.
    """

    async def handle(self, new_page: Page, image_path: str, logger: logging.Logger) -> ClickResult:
        await new_page.wait_for_load_state("load")
        # The new tab is a page in its own right and needs the same treatment as
        # the one we started from.
        await freeze_animations(new_page, logger)
        await new_page.screenshot(path=image_path, full_page=True)
        return ClickResult(
            page_url=new_page.url,
            image_path=image_path,
            fingerprint=await fingerprint_page(new_page, logger),
        )


class RedirectHandler:
    """
    Case 2: clicking a link navigates the current page to a new URL.

    Screenshots the redirected page, then navigates back so subsequent
    links in the same focus area can still be reached.
    """

    async def handle(self, page: Page, image_path: str, logger: logging.Logger) -> ClickResult:
        await page.screenshot(path=image_path, full_page=True)
        # Fingerprint before navigating back, while the captured page is still loaded.
        result = ClickResult(
            page_url=page.url,
            image_path=image_path,
            fingerprint=await fingerprint_page(page, logger),
        )
        await page.go_back(wait_until="load")
        await freeze_animations(page, logger) # # Going back reloads the page, which drops the CSS that froze animations.
        return result


class PopupHandler:
    """
    Case 3: clicking a link triggers an in-page popup without changing the URL.

    Screenshot priority:
      1. If focus_item.popup.content is set — find the first visible popup
         element and screenshot it.
      2. Fallback — screenshot the entire focus-area locator.

    After screenshotting, clicks the close button (focus_item.popup.close_button)
    if one is configured, then waits briefly for the DOM to settle.
    """

    async def handle(
        self,
        page: Page,
        focus_item: FocusItem,
        focus_content_locator: Locator,
        image_path: str,
        logger: logging.Logger,
    ) -> ClickResult:
        captured = await self._screenshot_popup(
            page, focus_item, focus_content_locator, image_path, logger
        )
        if captured is None:
            if focus_item.popup and focus_item.popup.content:
                logger.warning(
                    "Popup content locator matched nothing visible; "
                    "fell back to focus-area screenshot."
                )
            else:
                # No popup configured: capturing the focus area is the intent, e.g. a tab switch.
                logger.info("No popup configured; captured the focus area.")

        # Fingerprint exactly the region that was screenshotted, and do it before
        # the popup is dismissed.
        fingerprint = await fingerprint_locator(captured or focus_content_locator, logger)

        await self._close_popup(page, focus_item)
        return ClickResult(
            page_url=page.url,
            image_path=image_path,
            fingerprint=fingerprint,
        )

    async def _screenshot_popup(
        self,
        page: Page,
        focus_item: FocusItem,
        focus_content_locator: Locator,
        image_path: str,
        logger: logging.Logger,
    ) -> Optional[Locator]:
        """
        Try to screenshot the popup region defined in focus_item.popup.content.
        Falls back to the focus area if the popup element is not visible.

        Returns the locator that was captured, or None when the fallback was used
        """
        if focus_item.popup and focus_item.popup.content:
            popup_locators = await page.locator(
                f"xpath={focus_item.popup.content}"
            ).all()
            for locator in popup_locators:
                if await locator.is_visible():
                    await _screenshot_element(page, locator, image_path, logger)
                    return locator

        # Fallback: screenshot the focus area itself
        await _screenshot_element(page, focus_content_locator, image_path, logger)
        return None

    async def _close_popup(self, page: Page, focus_item: FocusItem) -> None:
        """Click the configured close button and wait for the DOM to settle."""
        if not (focus_item.popup and focus_item.popup.close_button):
            return
        close_btn = page.locator(f"xpath={focus_item.popup.close_button}")
        await _click_button(close_btn)
        await page.wait_for_timeout(500)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def click_and_capture(
    page: Page,
    link_locator: Locator,
    focus_item: FocusItem,
    focus_content_locator: Locator,
    image_path: str,
    logger: logging.Logger,
) -> ClickResult | None:
    """
    Click a link and capture the resulting outcome as a screenshot.

    Attempts to detect which of the three click outcomes occurred by watching
    for a new page event. Delegates screenshot logic to the matching handler.
    Returns None if an unrecoverable Playwright error occurs.

    Parameters
    ----------
    page                  : The active Playwright page.
    link_locator          : The specific link element to click.
    focus_item            : Config for this focus area (used by PopupHandler).
    focus_content_locator : The focus-area locator (PopupHandler fallback screenshot).
    image_path            : Destination path for the screenshot file.
    logger                : Logger from the calling spider.
    """
    original_url = page.url.split("#")[0]
    new_page = None

    try:
        async with page.context.expect_page(timeout=3000) as new_page_info:
            await link_locator.highlight()
            await link_locator.evaluate("el => el.click()")

        # Case 1: a new tab opened
        new_page = await new_page_info.value
        logger.info(f"Case 1 (new tab): {new_page.url}")
        return await NewTabHandler().handle(new_page, image_path, logger)

    except TimeoutError:
        await page.wait_for_load_state("load")

        if page.url.split("#")[0] != original_url:
            # Case 2: current page redirected to a new URL
            logger.info(f"Case 2 (redirect): {page.url}")
            return await RedirectHandler().handle(page, image_path, logger)
        else:
            # Case 3: URL unchanged — an in-page popup likely appeared
            logger.info("Case 3 (popup): URL unchanged, capturing popup content.")
            return await PopupHandler().handle(
                page, focus_item, focus_content_locator, image_path, logger
            )

    except PlaywrightError as e:
        logger.error(f"Playwright error during click: {e}")
        return None

    finally:
        if new_page:
            await new_page.close()
