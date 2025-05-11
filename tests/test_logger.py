import logging
from app.utils.logger_setup import setup_app_logger

setup_app_logger()
logger = logging.getLogger(__name__)

def test_logger():
    logger.info("This is a test message.")