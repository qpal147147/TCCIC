import re
from pydantic import BaseModel, field_validator
from pathlib import Path


def _validate_bank_code(v: str) -> str:
    """Reject bank_code values that could cause path traversal (e.g. '../../etc')."""
    if not re.match(r'^[a-z0-9_-]+$', v):
        raise ValueError("bank_code must contain only lowercase letters, digits, hyphens, or underscores")
    return v


class CardListRequest(BaseModel):
    bank_code: str
    url: str

    @field_validator('bank_code')
    @classmethod
    def validate_bank_code(cls, v: str) -> str:
        return _validate_bank_code(v)


class CardFeatureRequest(BaseModel):
    bank_code: str
    card_name: str
    card_url: str

    @field_validator('bank_code')
    @classmethod
    def validate_bank_code(cls, v: str) -> str:
        return _validate_bank_code(v)


class CardFeatureResponse(BaseModel):
    job_status: bool = False


class CardListSpiderData(BaseModel):
    """Data class for CardListSpider

    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        url: The URL the spider should start crawling.
        file_name: The name of the file to write the results to.
        job_id: The ID of the job.
    """
    config_path: str | Path
    bank_code: str
    url: str
    file_name: str
    job_id: str


class CardFeatureSpiderData(BaseModel):
    """Data class for CardFeatureSpider

    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        card_name: The name of the card to be crawled.
        card_url: The URL the spider should start crawling.
        file_name: The name of the file to write the results to.
        job_id: The ID of the job.
        job_status_txt_path: The path to the job status text file.
    """
    config_path: str | Path
    bank_code: str
    card_name: str
    card_url: str
    file_name: str
    job_id: str
    job_status_txt_path: str | Path
