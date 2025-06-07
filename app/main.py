import logging
import multiprocessing
from fastapi import FastAPI

from app.api_service.routers.v1.api import router as v1_router
from app.utils.logger_setup import setup_app_logger

multiprocessing.set_start_method("spawn")

app = FastAPI()
app.include_router(v1_router, prefix="/api/v1")


if __name__ == "__main__":
    setup_app_logger()
    logger = logging.getLogger(__name__)
    logger.info("Starting app.")
    
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=1108, reload=False)