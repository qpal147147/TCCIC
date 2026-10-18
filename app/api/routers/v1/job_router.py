"""
Job status and result endpoints.

Everything a caller can ask about a crawl is keyed by job_id, for both spider
types. Submission lives in crawler_router; querying lives here.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.schemas.base_schema import BaseResponse
from app.api.schemas.job_schema import CardFeatureResult, JobStatusResponse
from app.crawler.schemas.card_list import BankCardListPageData, CardItem, CardPagesItem
from app.services.store import Store

logger = logging.getLogger(__name__)
router = APIRouter()



def _read_card_list(jsonl_path: Path) -> BankCardListPageData:
    """
    Turn a card-list crawl's raw JSONL into the grouped response.

    Cards are de-duplicated because tabs on a bank's site often repeat the same
    card, then grouped by the page they were found on.
    """
    seen: set[tuple[str, str]] = set()
    page_map: dict[str, CardPagesItem] = {}
    bank_code = bank_name = ""

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            identity = (item["card_url"], item["card_title"])
            if identity in seen:
                continue
            seen.add(identity)

            bank_code = item["bank_code"]
            bank_name = item["bank_name"]
            page_url = item["page_url"]
            card = CardItem(title=item["card_title"], url=item["card_url"])

            if page_url not in page_map:
                page_map[page_url] = CardPagesItem(page_url=page_url, cards=[card])
            else:
                page_map[page_url].cards.append(card)

    return BankCardListPageData(
        bank_code=bank_code,
        bank_name=bank_name,
        pages=list(page_map.values()),
    )


def _not_found(job_id: str) -> JSONResponse:
    response = BaseResponse(
        status="fail",
        message="Job not found.",
        error=f"No job with job_id='{job_id}'.",
    )
    return JSONResponse(content=response.model_dump(), status_code=404)


@router.get("/{job_id}")
async def job_status(request: Request, job_id: str):
    """Current state of a crawl job, for either spider type."""
    store: Store = request.state.store
    job = store.jobs.get(job_id)

    if job is None:
        return _not_found(job_id)

    response = BaseResponse[JobStatusResponse](
        status="success",
        message="Query job status successfully.",
        data=JobStatusResponse.from_job(job),
    )
    return JSONResponse(content=response.model_dump(mode="json"), status_code=200)


@router.get("/{job_id}/result")
async def job_result(request: Request, job_id: str):
    """
    Result of a finished crawl job.

    Unfinished and failed jobs are answered with distinct status codes so a
    caller can tell "keep waiting" apart from "give up".
    """
    store: Store = request.state.store
    job = store.jobs.get(job_id)

    if job is None:
        return _not_found(job_id)

    if job.status in ("queued", "running"):
        response = BaseResponse(
            status="fail",
            message="The crawl has not finished yet.",
            error=f"Job is '{job.status}'.",
        )
        return JSONResponse(content=response.model_dump(), status_code=409, headers={"Retry-After": "30"})

    if job.status != "completed":
        response = BaseResponse(
            status="fail",
            message="The crawl did not complete successfully.",
            error=job.error or f"Job is '{job.status}'.",
        )
        return JSONResponse(content=response.model_dump(), status_code=400)

    try:
        if job.job_type == "card_list":
            data = _read_card_list(Path(job.artifact_dir))
            response = BaseResponse[BankCardListPageData](
                status="success",
                message="Successfully crawled all card information.",
                data=data,
            )
        else:
            card = store.cards.get(job.card_key) if job.card_key else None
            response = BaseResponse[CardFeatureResult](
                status="success",
                message="Card feature crawl completed and vectorized.",
                data=CardFeatureResult(
                    card_key=job.card_key,
                    card_name=card.card_name if card else None,
                    bank_code=job.bank_code,
                    stats=job.stats_json,
                ),
            )
        return JSONResponse(content=response.model_dump(mode="json"), status_code=200)
    except FileNotFoundError as e:
        logger.error(f"Artifact missing for job {job_id}: {e}")
        response = BaseResponse(
            status="fail",
            message="The job completed but its result file is no longer available.",
            error=str(e),
        )
        return JSONResponse(content=response.model_dump(), status_code=410)
    except Exception as e:
        logger.error(f"Unexpected error reading result for job {job_id}: {e}")
        response = BaseResponse(
            status="fail",
            message="Error occurred while reading the job result.",
            error=str(e),
        )
        return JSONResponse(content=response.model_dump(), status_code=500)
