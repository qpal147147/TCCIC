import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logger(name: str, log_file: str, level=logging.DEBUG, when='midnight', interval=1, backup_count=7) -> logging.Logger:
    Path("logs").mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = TimedRotatingFileHandler(
            filename=f"logs/{log_file}",
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding='utf-8',       
            utc=False
        )
        formatter = logging.Formatter("--------------[%(asctime)s] - [%(name)s] - [%(levelname)s]--------------\n%(message)s\n\n")
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger
