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
capture_region()     -- screenshot + fingerprint of an element or a whole page, free of
                        overlays and inner scrollbars; every capture goes through it
_click_button()      -- utility: click the first visible element from a Locator set
"""

import logging
import math
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

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


# Captures a page a link opened, in place of its full-page screenshot (page_focus).
OpenedPageCapture = Callable[[Page], Awaitable[list[ClickResult]]]


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

async def _click_button(locator: Locator) -> None:
    """Click the first visible element matched by locator; silently skip if none found."""
    for btn in await locator.all():
        if await btn.is_visible(timeout=1000):
            await btn.click(timeout=1000)
            break

# Prepares the page for one capture; `target` is the element, or null for the whole page.
#   - Hides fixed elements (site headers, chat widgets, cookie bars) that would
#     cover the capture. An element capture also hides sticky ones, which stick
#     over whatever the element was scrolled to. Anything containing the target
#     or inside it is kept, so a modal stays visible.
#   - Element captures only: lifts the height limit of scroll boxes inside the
#     target, so content behind an inner scrollbar is painted too.
# The original style attributes are kept on window for _RESTORE_JS.
_PREPARE_JS = """
target => {
  const changed = [];
  const save = el => { if (!changed.some(c => c[0] === el)) changed.push([el, el.getAttribute("style")]); };
  for (const el of document.querySelectorAll("body *")) {
    const position = getComputedStyle(el).position;
    if (position !== "fixed" && !(target && position === "sticky")) continue;
    if (target && (el.contains(target) || target.contains(el))) continue;
    save(el);
    // visibility keeps its text out of the fingerprint; opacity stops a child
    // that sets visibility: visible from still being painted.
    el.style.setProperty("visibility", "hidden", "important");
    el.style.setProperty("opacity", "0", "important");
  }
  if (target) {
    for (const el of [target, ...target.querySelectorAll("*")]) {
      if (el.scrollHeight > el.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(el).overflowY)) {
        save(el);
        el.style.setProperty("max-height", "none", "important");
        el.style.setProperty("height", "auto", "important");
        el.style.setProperty("overflow", "visible", "important");
      }
    }
  }
  window.__tccicRestore = changed;
}
""".strip()

_RESTORE_JS = """
() => {
  for (const [el, style] of (window.__tccicRestore || []).reverse()) {
    if (style === null) el.removeAttribute("style"); else el.setAttribute("style", style);
  }
  window.__tccicRestore = [];
}
""".strip()



# Room for the element's own offset, e.g. a centered dialog's margins.



async def capture_region(
    page: Page, locator: Optional[Locator], image_path: str, logger: logging.Logger
) -> Optional[Fingerprint]:
    """
    Screenshot an element in full, or the whole page when locator is None, and
    fingerprint exactly what the screenshot shows.

    A fixed modal only paints within the viewport, so an element taller than the
    viewport is captured with the viewport temporarily grown to fit it. Every
    change to the page is undone afterwards, so one capture cannot affect the next.
    """
    max_capture_height = 16000  # Upper limit for the enlarged viewport height, in px.
    viewport_margin = 100 # Extra px added to the viewport height as a buffer against rounding and layout shifts.
    
    viewport = page.viewport_size
    resized = False
    try:
        if locator is None:
            # From the top, a sticky bar sits in its own place instead of over content.
            await page.evaluate("window.scrollTo(0, 0)")
            await page.evaluate(_PREPARE_JS, None)
            await page.screenshot(path=image_path, full_page=True)
            # Fingerprint while prepared: hidden overlays are not part of the capture.
            return await fingerprint_page(page, logger)

        await locator.evaluate(_PREPARE_JS)
        # The box is relative to the viewport, so measure it once it is in view;
        # otherwise an element far down the page reads as needing a huge viewport.
        await locator.scroll_into_view_if_needed()
        box = await locator.bounding_box()
        if viewport and box and box["height"] > viewport["height"]:
            height = math.ceil(box["height"] + 2 * max(box["y"], 0)) + viewport_margin
            if height > max_capture_height:
                logger.warning(
                    f"Element is {round(box['height'])}px tall; capturing only the first "
                    f"{max_capture_height}px."
                )
                height = max_capture_height
            await page.set_viewport_size({"width": viewport["width"], "height": height})
            resized = True
            await page.wait_for_timeout(300)  # let the page re-lay out at the new size
        await locator.screenshot(path=image_path)
        # Fingerprint while scroll boxes are lifted, or text behind them is missed.
        return await fingerprint_locator(locator, logger)
    finally:
        try:
            await page.evaluate(_RESTORE_JS)
        except PlaywrightError as e:
            logger.debug(f"Could not restore the page after a capture: {e}")
        if resized:
            await page.set_viewport_size(viewport)
            await page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Outcome handlers
# ---------------------------------------------------------------------------

class NewTabHandler:
    """
    Case 1: clicking a link opens a new browser tab.

    Waits for the tab to finish loading, then takes a full-page screenshot, or
    hands the tab to capture_opened_page when page_focus is configured.
    The caller is responsible for closing the new tab.
    """

    async def handle(
        self,
        new_page: Page,
        image_path: str,
        logger: logging.Logger,
        capture_opened_page: Optional[OpenedPageCapture] = None,
    ) -> list[ClickResult]:
        await new_page.wait_for_load_state("load")
        # The new tab is a page in its own right and needs the same treatment as
        # the one we started from.
        await freeze_animations(new_page, logger)
        if capture_opened_page:
            return await capture_opened_page(new_page)
        fingerprint = await capture_region(new_page, None, image_path, logger)
        return [ClickResult(page_url=new_page.url, image_path=image_path, fingerprint=fingerprint)]


class RedirectHandler:
    """
    Case 2: clicking a link navigates the current page to a new URL.

    Captures the redirected page (full page, or page_focus when configured),
    then navigates back so subsequent links in the same focus area can still
    be reached.
    """

    async def handle(
        self,
        page: Page,
        image_path: str,
        logger: logging.Logger,
        capture_opened_page: Optional[OpenedPageCapture] = None,
    ) -> list[ClickResult]:
        # Capture before navigating back, while the redirected page is still loaded.
        if capture_opened_page:
            await freeze_animations(page, logger)  # a new document has none of our CSS
            results = await capture_opened_page(page)
        else:
            fingerprint = await capture_region(page, None, image_path, logger)
            results = [ClickResult(page_url=page.url, image_path=image_path, fingerprint=fingerprint)]
        await page.go_back(wait_until="load")
        await freeze_animations(page, logger)  # Going back reloads the page, which drops the CSS that froze animations.
        return results


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
        popup = await self._find_popup(page, focus_item)
        if popup is None:
            if focus_item.popup and focus_item.popup.content:
                logger.warning(
                    "Popup content locator matched nothing visible; "
                    "fell back to focus-area screenshot."
                )
            else:
                # No popup configured: capturing the focus area is the intent, e.g. a tab switch.
                logger.info("No popup configured; captured the focus area.")

        # Capture before the popup is dismissed.
        fingerprint = await capture_region(page, popup or focus_content_locator, image_path, logger)

        await self._close_popup(page, focus_item)
        return ClickResult(
            page_url=page.url,
            image_path=image_path,
            fingerprint=fingerprint,
        )

    async def _find_popup(self, page: Page, focus_item: FocusItem) -> Optional[Locator]:
        """Return the first visible element matching focus_item.popup.content, or None."""
        if focus_item.popup and focus_item.popup.content:
            for locator in await page.locator(f"xpath={focus_item.popup.content}").all():
                if await locator.is_visible():
                    return locator
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
    capture_opened_page: Optional[OpenedPageCapture] = None,
) -> list[ClickResult]:
    """
    Click a link and capture the resulting outcome as screenshots.

    Attempts to detect which of the three click outcomes occurred by watching
    for a new page event. Delegates screenshot logic to the matching handler.
    Returns an empty list if an unrecoverable Playwright error occurs.

    Parameters
    ----------
    page                  : The active Playwright page.
    link_locator          : The specific link element to click.
    focus_item            : Config for this focus area (used by PopupHandler).
    focus_content_locator : The focus-area locator (PopupHandler fallback screenshot).
    image_path            : Destination path for the screenshot file.
    logger                : Logger from the calling spider.
    capture_opened_page   : Captures a page the click opened (new tab or redirect)
                            in place of its full-page screenshot; set for page_focus.
    """
    original_url = page.url.split("#")[0]
    new_page = None

    # Click and wait to see whether a new tab opens. Only this step's timeout
    # means "no new tab"; a timeout while capturing must not be read as one.
    try:
        async with page.context.expect_page(timeout=3000) as new_page_info:
            # await link_locator.highlight()
            await link_locator.evaluate("el => el.click()")
        new_page = await new_page_info.value
    except TimeoutError:
        pass
    except PlaywrightError as e:
        logger.error(f"Playwright error during click: {e}")
        return []

    try:
        if new_page:
            # Case 1: a new tab opened
            logger.info(f"Case 1 (new tab): {new_page.url}")
            return await NewTabHandler().handle(new_page, image_path, logger, capture_opened_page)

        await page.wait_for_load_state("load")

        if page.url.split("#")[0] != original_url:
            # Case 2: current page redirected to a new URL
            logger.info(f"Case 2 (redirect): {page.url}")
            return await RedirectHandler().handle(page, image_path, logger, capture_opened_page)
        else:
            # Case 3: URL unchanged — an in-page popup likely appeared
            logger.info("Case 3 (popup): URL unchanged, capturing popup content.")
            if capture_opened_page:
                logger.warning("page_focus is set but the click opened no page; captured in place.")
            return [await PopupHandler().handle(
                page, focus_item, focus_content_locator, image_path, logger
            )]

    except PlaywrightError as e:
        logger.error(f"Playwright error while capturing the click outcome: {e}")
        return []

    finally:
        if new_page:
            await new_page.close()
