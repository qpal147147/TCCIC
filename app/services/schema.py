from typing import Literal
from pydantic import BaseModel

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
