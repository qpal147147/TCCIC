from typing import Literal
from pydantic import BaseModel, Field

class SummarySection(BaseModel):
    """
    One independent offer, plan or clause transcribed from an image
    """
    section: Literal["產品特色", "回饋", "優惠活動", "年費", "申請資格", "注意事項", "其他"]
    content: str

class ImageSummary(BaseModel):
    """
    What the vision model returns for one image.
    """
    sections: list[SummarySection]


class CardFacts(BaseModel):
    """
    One card's answers to a fixed set of questions, condensed from its summaries.

    Facts are one line each and serve comparison across cards, 
    where every card has to answer the same questions.
    """
    annual_fee: str = Field(description="年費：各卡等的年費金額、首年是否免年費、免年費條件")
    reward_type: str = Field(description="回饋形式：現金回饋、點數（寫出點數名稱）或哩程")
    base_reward: str = Field(description="一般消費回饋：國內一般消費不需條件即可獲得的回饋率")
    max_reward: str = Field(description="最高回饋與條件：頁面宣稱的最高回饋率，以及適用的通路與門檻")
    reward_cap: str = Field(description="回饋上限：每月或每期的回饋上限")
    overseas_reward: str = Field(description="海外消費回饋：海外消費的回饋率與條件")
    featured_channels: str = Field(description="主打通路：有加碼回饋或優惠的通路類別與代表商店")
    welcome_offer: str = Field(description="新戶與首刷禮：新戶或首刷的贈禮與條件")
    travel_benefits: str = Field(description="旅遊權益：機場貴賓室、機場接送、旅遊平安險等")
    eligibility: str = Field(description="申請資格：年齡與財力門檻")

class VectorDatabaseData(BaseModel):
    """
    Data that needs to be stored in the vector database
    """
    text: str
    vector: list[float]
    url: str
    section: str
    card_key: str
    card_name: str
    bank_code: str

class SourceData(BaseModel):
    """
    Raw data retrieved from vector data
    """
    text: str
    url: str
    section: str
    card_key: str
    card_name: str
    bank_code: str

class LLMResponse(BaseModel):
    """
    Data returned by calling the "Chat" method
    """
    response: str
    sources: list[SourceData]

class CardInfo(BaseModel):
    """
    Card information in the vector database
    """
    card_key: str
    card_name: str
    bank_code: str

class VectorizeResult(BaseModel):
    """
    What one vectorization run did.

    `cached` is what the run avoided paying for; recording it is the only way to
    tell whether the fingerprint is actually earning its keep on real bank sites.
    """
    images: int       # rows in the crawl's JSONL
    cached: int       # summaries reused, costing no model call
    summarized: int   # summaries newly generated
    failed: int       # images given up on after retries
    vectorized: int   # records written to Milvus — one per section
    facts_extracted: bool = False      # whether the fact extraction was successful
