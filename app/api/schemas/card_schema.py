from typing import Optional

from pydantic import BaseModel


class QARequest(BaseModel):
    question: str
    card_key: Optional[str] = None
    bank_code: Optional[str] = None

class QAResponse(BaseModel):
    answer: str