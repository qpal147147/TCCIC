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
from dataclasses import dataclass

from playwright.async_api import Page, Locator, TimeoutError, Error as PlaywrightError

from app.crawler.schemas.bank_config import FocusItem


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ClickResult:
    """The page URL and saved image path produced by a single link click."""
    page_url: str
    image_path: str


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

async def _click_button(locator: Locator) -> None:
    """Click the first visible element matched by locator; silently skip if none found."""
    for btn in await locator.all():
        if await btn.is_visible(timeout=1000):
            await btn.click(timeout=1000)
            break


# ---------------------------------------------------------------------------
# Outcome handlers
# ---------------------------------------------------------------------------

class NewTabHandler:
    """
    Case 1: clicking a link opens a new browser tab.

    Waits for the tab to finish loading, takes a full-page screenshot,
    then returns. The caller is responsible for closing the new tab.
    """

    async def handle(self, new_page: Page, image_path: str) -> ClickResult:
        await new_page.wait_for_load_state("load")
        await new_page.screenshot(path=image_path, full_page=True)
        return ClickResult(page_url=new_page.url, image_path=image_path)


class RedirectHandler:
    """
    Case 2: clicking a link navigates the current page to a new URL.

    Screenshots the redirected page, then navigates back so subsequent
    links in the same focus area can still be reached.
    """

    async def handle(self, page: Page, image_path: str) -> ClickResult:
        await page.screenshot(path=image_path, full_page=True)
        result = ClickResult(page_url=page.url, image_path=image_path)
        await page.go_back(wait_until="load")
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
            page, focus_item, focus_content_locator, image_path
        )
        if not captured:
            logger.warning(
                "Popup content locator matched nothing visible; "
                "fell back to focus-area screenshot."
            )
        await self._close_popup(page, focus_item)
        return ClickResult(page_url=page.url, image_path=image_path)

    async def _screenshot_popup(
        self,
        page: Page,
        focus_item: FocusItem,
        focus_content_locator: Locator,
        image_path: str,
    ) -> bool:
        """
        Try to screenshot the popup region defined in focus_item.popup.content.
        Falls back to the focus area if the popup element is not visible.
        Returns True if the popup was captured, False if the fallback was used.
        """
        if focus_item.popup and focus_item.popup.content:
            popup_locators = await page.locator(
                f"xpath={focus_item.popup.content}"
            ).all()
            for locator in popup_locators:
                if await locator.is_visible():
                    await locator.screenshot(path=image_path)
                    return True

        # Fallback: screenshot the focus area itself
        await focus_content_locator.screenshot(path=image_path)
        return False

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
        return await NewTabHandler().handle(new_page, image_path)

    except TimeoutError:
        await page.wait_for_load_state("load")

        if page.url.split("#")[0] != original_url:
            # Case 2: current page redirected to a new URL
            logger.info(f"Case 2 (redirect): {page.url}")
            return await RedirectHandler().handle(page, image_path)
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
