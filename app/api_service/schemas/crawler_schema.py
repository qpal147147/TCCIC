from pydantic import BaseModel

class CardListRequest(BaseModel):
    bank_code: str
    url: str

class CardFeatureRequest(BaseModel):
    bank_code: str
    card_name: str
    card_url: str

class CardFeatureResponse(BaseModel):
    job_status: bool = False