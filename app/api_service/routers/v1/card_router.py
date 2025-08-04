import logging

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.api_service.schemas.card_schema import QARequest
from app.api_service.schemas.base_schema import BaseResponse
from app.services.schema import LLMResponse
from app.services.rag import RAG


logger = logging.getLogger(__name__)
router = APIRouter()


@router.delete("/{card_id}")
async def delete_card(request: Request, card_id: str):
    rag: RAG = request.state.rag

    try:
        await rag.delete_card(card_id=card_id)

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"An error occurred while deleting card: {e}")

        response = BaseResponse(
            status="fail",
            message="Error occurred while deleting card.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)


@router.post("/qa")
async def card_qa(request: Request, qa_request : QARequest):
    rag: RAG = request.state.rag

    try:
        result = await rag.chat(
            query=qa_request.question,
            card_id=qa_request.card_id,
            bank_code=qa_request.bank_id,
        )

        response = BaseResponse[LLMResponse](
            status="success",
            message="Query successfully.",
            data=result
        )
        return JSONResponse(content=response.model_dump(), status_code=200)
    except Exception as e:
        logger.error(f"An error occurred while chatting: {e}")

        response = BaseResponse(
            status="fail",
            message="Error occurred while chatting.",
            error=str(e)
        )
        return JSONResponse(content=response.model_dump(), status_code=400)



