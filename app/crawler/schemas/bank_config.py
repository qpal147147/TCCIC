from typing import Optional
from pydantic import BaseModel


class CrawlPolicy(BaseModel):
    """Per-bank crawl timing policy. All values are in milliseconds."""
    initial_wait_ms: int = 10000  # Time to wait for the initial page load before interacting
    tab_wait_ms: int = 2000       # Time to wait after clicking a tab before reading content


class CardItemXPath(BaseModel):
    """XPath selectors for extracting title and URL from a single card element."""
    title: str
    url: str


class PageXPaths(BaseModel):
    """XPath selectors used by the card-list spider to discover cards on a listing page."""
    tab_link: Optional[str]   # Locates tab links that categorize cards; null if no tabs
    division: Optional[str]   # Locates the container element for each individual card
    card: CardItemXPath


class ContentXpath(BaseModel):
    """A single focus area and its clickable link selector for the card-feature spider."""
    content: Optional[str]    # XPath of the region to screenshot / interact with
    link: Optional[str]       # XPath of links inside that region to click through


class FeatureXpaths(BaseModel):
    """
    Interaction rules for one card-feature URL pattern.
    card_code is matched as a substring of the card URL to select the correct rule set.
    """
    card_code: str
    cookie_button: Optional[str]          # Selector for the cookie-consent button, if any
    focus: Optional[list[ContentXpath]]   # Ordered list of regions to interact with
    sub_focus_content: Optional[list[str]]  # XPath(s) of popup content to screenshot
    close_button: Optional[str]           # Selector to close a popup after screenshotting


class BankConfig(BaseModel):
    """Configuration for a single bank: crawl selectors, feature rules, and timing policy."""
    bank_code: str
    bank_name: str
    is_dynamic: bool
    xpaths: PageXPaths
    features: list[FeatureXpaths]
    crawl_policy: CrawlPolicy = CrawlPolicy()  # Falls back to defaults if not set in YAML

    def get_feature_config(self, card_url: str) -> Optional[FeatureXpaths]:
        """Return the first FeatureXpaths whose card_code appears in card_url, or None."""
        for feature in self.features:
            if feature.card_code in card_url:
                return feature
        return None


class BankCrawlerConfig(BaseModel):
    """Root config object that holds the full list of bank configurations."""
    banks: list[BankConfig]

    def get_bank_config(self, bank_code: str) -> Optional[BankConfig]:
        """Return the BankConfig matching bank_code, or None if not found."""
        for bank_config in self.banks:
            if bank_config.bank_code == bank_code:
                return bank_config
        return None