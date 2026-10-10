"""Content fingerprinting for captured card-feature regions.

Purpose:
    Tell whether a captured region still shows the same content as last
    time, so unchanged pages can be served from cache and the crawler
    avoids repeating downstream work.

Status:
    Nothing consumes the fingerprint yet. It is recorded alongside each
    capture so its stability can be measured against real bank sites
    before any caching depends on it.

Source:
    The rendered DOM, not the screenshot. Pixels change with animation
    frames, hover states and font rendering even when the content has not.

Inputs (deliberately only two):
    innerText: Rendered text only, so hidden navigation, scripts and
        bot-detection tokens injected as attributes never reach it.
    <img> src: About 70% of a Taiwanese card page's promotional detail
        lives in images; text alone would miss most changes.

Excluded:
    CSS background images, inline SVG text and natural image dimensions.
    Each narrows a specific gap but adds a mechanism that must keep
    evolving with the web. Detection is best-effort; staleness is bounded
    elsewhere rather than chased here.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from playwright.async_api import Locator, Page, Error as PlaywrightError

# Collects the fingerprint ingredients from one element. Runs inside the page,
# so it sees the DOM as rendered — which for a client-rendered site is the only
# place the content exists at all.
_COLLECT_JS = """
el => {
  const text = (el.innerText || "").replace(/\\s+/g, " ").trim();
  const srcs = [];
  for (const img of el.querySelectorAll("img")) {
    const src = img.currentSrc || img.src;
    if (src) srcs.push(src);
  }
  return { text: text, srcs: srcs };
}
""".strip()  # stripped so Playwright reads it unambiguously as a function expression

# Screenshots and innerText are both layout-dependent, so a running animation
# can change either between two otherwise identical crawls.
FREEZE_CSS = """
*, *::before, *::after {
  animation: none !important;
  transition: none !important;
  scroll-behavior: auto !important;
}
"""


@dataclass(frozen=True)
class Fingerprint:
    """
    A capture's content fingerprint.

    `text_len` and `img_count` carry no meaning to the hash — they are recorded
    so that when two crawls disagree, it is possible to see whether the text or
    the imagery moved, instead of only that something did.
    """

    content_hash: str
    text_len: int
    img_count: int


def digest(text: str, srcs: Iterable[str]) -> str:
    """
    Hash one capture's content.

    Image sources are de-duplicated and sorted so that a carousel reshuffling the
    same images does not read as a content change.
    """
    payload = json.dumps(
        {"text": text, "srcs": sorted(set(srcs))},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build(raw: dict) -> Fingerprint:
    text = raw.get("text") or ""
    srcs = sorted(set(raw.get("srcs") or []))
    return Fingerprint(
        content_hash=digest(text, srcs),
        text_len=len(text),
        img_count=len(srcs),
    )


async def fingerprint_page(page: Page, logger: logging.Logger) -> Optional[Fingerprint]:
    """Fingerprint a whole page. Returns None if the page cannot be read."""
    try:
        raw = await page.evaluate(f"({_COLLECT_JS})(document.body)")
        return _build(raw)
    except PlaywrightError as e:
        logger.warning(f"Could not fingerprint page {page.url}: {e}")
        return None


async def fingerprint_locator(locator: Locator, logger: logging.Logger) -> Optional[Fingerprint]:
    """Fingerprint a single element. Returns None if the element is gone or detached."""
    try:
        raw = await locator.evaluate(_COLLECT_JS)
        return _build(raw)
    except PlaywrightError as e:
        logger.warning(f"Could not fingerprint element: {e}")
        return None


async def freeze_animations(page: Page, logger: logging.Logger) -> None:
    """
    Stop animations and transitions so a capture reflects the page at rest.

    Improves the screenshots in their own right — a carousel caught mid-slide is
    poor input for the summarizer regardless of fingerprinting.
    """
    try:
        await page.add_style_tag(content=FREEZE_CSS)
    except PlaywrightError as e:
        logger.debug(f"Could not freeze animations on {page.url}: {e}")
