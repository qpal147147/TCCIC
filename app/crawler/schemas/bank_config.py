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
    tab_link: Optional[str] = None         # Locates tab links that categorize cards; null if no tabs
    skip_card_tabs: list[dict[str, str]] = []  # {tab_text: card_url} — tabs whose destination is a
                                           # single-card intro page rather than a list. A CardItem
                                           # is emitted directly from config; the page is not crawled.
    division: Optional[str] = None         # Locates the container element for each individual card
    card: CardItemXPath


class PopupConfig(BaseModel):
    """Selectors for capturing and dismissing a popup triggered by clicking a focus-area link."""
    content: Optional[str] = None       # XPath of the popup region to screenshot
    close_button: Optional[str] = None  # Selector to close the popup after screenshotting


class FocusItem(BaseModel):
    """A single focus area and its clickable link selector for the card-feature spider."""
    content: Optional[str] = None        # XPath of the region to screenshot / interact with
    link: Optional[str] = None           # XPath of links inside that region to click through
    popup: Optional[PopupConfig] = None  # Set only if clicking links in this area opens a popup


class FeatureConfig(BaseModel):
    """
    Interaction rules for one card-feature URL pattern.
    card_code is matched as a substring of the card URL to select the correct rule set.
    """
    card_code: str
    cookie_button: Optional[str] = None  # Per-card override; falls back to bank-level if None
    focus: Optional[list[FocusItem]] = None

    def effective_cookie_button(self, bank_config: 'BankConfig') -> Optional[str]:
        """Return per-card cookie_button if set, otherwise fall back to the bank-level default."""
        return self.cookie_button or bank_config.cookie_button


class BankConfig(BaseModel):
    """Configuration for a single bank: crawl selectors, feature rules, and timing policy."""
    bank_code: str
    bank_name: str
    is_dynamic: bool
    xpaths: PageXPaths
    cookie_button: Optional[str] = None   # Bank-level default; overridable per-card in FeatureConfig
    features: list[FeatureConfig] = []
    crawl_policy: CrawlPolicy = CrawlPolicy()

    def get_feature_config(self, card_url: str) -> Optional[FeatureConfig]:
        """Return the first FeatureConfig whose card_code appears in card_url, or None."""
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
