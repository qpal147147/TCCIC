from typing import List, Optional
from pydantic import BaseModel

class CardItemXPath(BaseModel):
    """
    Card item xpath schema
    """
    title: str
    url: str
    content: List[str]

class PageXPaths(BaseModel):
    """
    Bank page xpaths schema
    """
    tab_link: Optional[str]
    division: Optional[str]
    card: CardItemXPath

class BankConfig(BaseModel):
    """
    Bank schema
    """
    bank_code: str
    bank_name: str
    is_dynamic: bool
    xpaths: PageXPaths

class BankCrawlerConfig(BaseModel):
    """
    Banks config schema
    """
    banks: List[BankConfig]

    def get_bank_config(self, bank_code: str) -> Optional[BankConfig]:
        """
        Get bank config by bank code
        """
        for bank_config in self.banks:
            if bank_config.bank_code == bank_code:
                return bank_config
        return None