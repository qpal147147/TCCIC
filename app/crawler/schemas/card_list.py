from typing import Literal, Optional
from pydantic import BaseModel, HttpUrl

class CardItem(BaseModel):
    """
    Card item schema
    """
    title: str
    url: str

class CardPagesItem(BaseModel):
    """
    Card pages data schema
    """
    page_url: str
    cards: list[CardItem]

class BankCardListPageData(BaseModel):
    """
    Bank card list page data schema
    """
    bank_code: str
    bank_name: str
    pages: list[CardPagesItem]