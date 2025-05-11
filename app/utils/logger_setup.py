import sys
import logging
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

from app.configs.settings import global_settings

# default logger arguments
LOG_FORMAT = "%(asctime)s - %(name)s - [%(levelname)s] - [%(module)s:%(funcName)s:%(lineno)d]: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_LEVEL_STR = getattr(global_settings, 'LOG_LEVEL', 'INFO').upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

LOG_DIR = getattr(global_settings, 'LOG_DIR', 'logs')
LOG_FILENAME = getattr(global_settings, 'LOG_FILENAME', 'app.log')

LOG_WHEN = getattr(global_settings, 'LOG_WHEN', 'midnight')
LOG_INTERVAL = getattr(global_settings, 'LOG_INTERVAL', 1)
LOG_BACKUP_COUNT = getattr(global_settings, 'LOG_BACKUP_COUNT', 30)
LOG_UTC = getattr(global_settings, 'LOG_UTC', False)


def setup_app_logger():
    """
    Configure and return a timed rotating application logger.
    If no parameters are provided, use the module-defined defaults.
    In real applications, these parameters should come from global settings.
    """

    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    if logger.hasHandlers():
        logger.handlers.clear()

    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        filename= f"{LOG_DIR}/{LOG_FILENAME}",
        when=LOG_WHEN,
        interval=LOG_INTERVAL,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8',
        utc=LOG_UTC
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info(f"Logger initialized. Logging to {LOG_DIR} and console. Level: {LOG_LEVEL_STR}")