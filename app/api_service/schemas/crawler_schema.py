from pydantic import BaseModel
from pathlib import Path

class CardListRequest(BaseModel):
    bank_code: str
    url: str

class CardFeatureRequest(BaseModel):
    bank_code: str
    card_name: str
    card_url: str

class CardFeatureResponse(BaseModel):
    job_status: bool = False

class CardFeatureSpiderData(BaseModel):
    """
    Data class for CardFeatureSpider
    Args:
        config_path: Path to the configuration file (e.g., banks.yaml) to be used by the spider.
        bank_code: The code of the bank to be crawled.
        card_name: The name of the card to be crawled.
        card_url: The URL the spider should start crawling.
        file_name: The name of the file to write the results to.
        job_id: The ID of the job.
        job_status_txt_path: The path to the job status text file.
    """
    config_path: str|Path
    bank_code: str
    card_name: str
    card_url: str
    file_name: str
    job_id: str
    job_status_txt_path: str|Path