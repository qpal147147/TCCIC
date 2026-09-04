import re
from typing import Literal
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

    @field_validator('card_url')
    @classmethod
    def validate_card_url(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError("card_url must be an HTTP or HTTPS URL")
        return v


class CardListSpiderData(BaseModel):
    """Data class for CardListSpider

    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        url: The URL the spider should start crawling.
        job_id: The ID of the job; also names the output file, since a card list
            is a snapshot of one execution and needs no separate identity.
    """
    config_path: str | Path
    bank_code: str
    url: str
    job_id: str


class CardFeatureSpiderData(BaseModel):
    """Data class for CardFeatureSpider

    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        card_name: The name of the card to be crawled.
        card_url: The URL the spider should start crawling.
        card_key: Stable identity of the card; names the artifact directory and
            scopes the card's vectors, so a re-crawl replaces the previous one.
        job_id: The ID of the job.
    """
    config_path: str | Path
    bank_code: str
    card_name: str
    card_url: str
    card_key: str
    job_id: str
