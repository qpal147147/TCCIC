from pydantic import BaseModel

class VectorDatabaseData(BaseModel):
    text: str
    vector: list[float]
    url: str
    card_id: str
    card_name: str
    bank_code: str

class SourceData(BaseModel):
    text: str
    url: str
    card_id: str
    bank_code: str

class LLMResponse(BaseModel):
    response: str
    sources: list[SourceData]