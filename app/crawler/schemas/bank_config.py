from typing import Optional
from pydantic import BaseModel

class CardItemXPath(BaseModel):
    """
    Card item xpath schema
    """
    title: str
    url: str

class PageXPaths(BaseModel):
    """
    Bank page xpaths schema
    """
    tab_link: Optional[str]
    division: Optional[str]
    card: CardItemXPath

class FeatureXpaths(BaseModel):
    """
    Feature xpaths schema
    """
    card_code: str
    cookie_button: Optional[str]
    focus_content: Optional[list[str]]
    link_button: Optional[str]
    sub_focus_content: Optional[list[str]]
    close_button: Optional[str]

class BankConfig(BaseModel):
    """
    Bank schema
    """
    bank_code: str
    bank_name: str
    is_dynamic: bool
    xpaths: PageXPaths
    features: list[FeatureXpaths]

    def get_feature_config(self, card_url: str) -> Optional[FeatureXpaths]:
        """
        Get feature config by card code
        """
        for feature in self.features:
            if feature.card_code in card_url:
                return feature
        return None

class BankCrawlerConfig(BaseModel):
    """
    Banks config schema
    """
    banks: list[BankConfig]

    def get_bank_config(self, bank_code: str) -> Optional[BankConfig]:
        """
        Get bank config by bank code
        """
        for bank_config in self.banks:
            if bank_config.bank_code == bank_code:
                return bank_config
        return None