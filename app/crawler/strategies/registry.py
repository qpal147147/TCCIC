"""
Strategy registry for card-list crawling.

get_strategy() resolves the correct BankStrategy subclass for a given bank
configuration. It first attempts to import a bank-specific module from this
package (e.g. strategies.yuantabank → YuantabankStrategy). If no custom
module exists, the default BankStrategy is returned as-is.

Convention
----------
- Module name  : app.crawler.strategies.<bank_code>   (lower-case)
- Class name   : <BankCode capitalised>Strategy        (e.g. YuantabankStrategy)

To add a new custom strategy, create a new module in this package following
the naming convention above and subclass BankStrategy.
"""

import importlib
import logging

from app.crawler.schemas.bank_config import BankConfig
from app.crawler.strategies.base import BankStrategy

logger = logging.getLogger(__name__)


def get_strategy(bank_config: BankConfig, spider_logger: logging.Logger | None = None) -> BankStrategy:
    """
    Return a BankStrategy instance for the given bank configuration.

    Lookup order:
    1. Try to import ``app.crawler.strategies.<bank_code>`` and find a class
       named ``<BankCode>Strategy`` (first letter of bank_code capitalised,
       rest kept as-is).
    2. Fall back to the default BankStrategy if no custom module is found.
    """
    bank_code = bank_config.bank_code
    module_path = f"app.crawler.strategies.{bank_code}"
    class_name = f"{bank_code.capitalize()}Strategy"

    try:
        module = importlib.import_module(module_path)
        strategy_class = getattr(module, class_name)
        logger.debug(f"Loaded custom strategy '{class_name}' for bank '{bank_code}'.")
        return strategy_class(bank_config, spider_logger)
    except ModuleNotFoundError:
        # No custom module for this bank — use the default implementation.
        logger.debug(f"No custom strategy for bank '{bank_code}'; using BankStrategy default.")
        return BankStrategy(bank_config, spider_logger)
    except AttributeError:
        # Module exists but the expected class is missing — warn and fall back.
        logger.warning(
            f"Module '{module_path}' exists but class '{class_name}' was not found. "
            "Falling back to default BankStrategy."
        )
        return BankStrategy(bank_config, spider_logger)
