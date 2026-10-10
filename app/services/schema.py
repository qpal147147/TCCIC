from pydantic import BaseModel

class VectorDatabaseData(BaseModel):
    """
    Data that needs to be stored in the vector database
    """
    text: str
    vector: list[float]
    url: str
    card_id: str
    card_name: str
    bank_code: str

class SourceData(BaseModel):
    """
    Raw data retrieved from vector data
    """
    text: str
    url: str
    card_id: str
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
    card_id: str
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
    vectorized: int   # records written to Milvus (cached + summarized)