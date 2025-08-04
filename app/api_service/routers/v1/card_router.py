import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.delete("/{card_id}")
async def delete_card_info(card_id: str):
    pass

@router.post("/{card_id}/qa")
async def card_qa(card_id: str):
    pass