import yaml

from pathlib import Path

def get_config(config_path: str) -> dict:
    """
    Read yaml file and return a dict.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config