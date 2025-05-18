from typing import List, Optional
from pydantic import BaseModel

class CardItemXPath(BaseModel):
    title: str
    url: str
    content: List[str]

class PageXPaths(BaseModel):
    tab_links: str
    card: CardItemXPath

class BankConfig(BaseModel):
    bank_code: str
    bank_name: str
    xpaths: PageXPaths

class BankCrawlerConfig(BaseModel):
    banks: List[BankConfig]