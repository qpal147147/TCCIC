import yaml

from pathlib import Path

def get_config(config_path: str | Path) -> dict:
    """
    Read yaml config and return a dict.
    Accepts either a single YAML file or a directory of per-bank YAML files.
    When a directory is given, each *.yaml file is treated as one bank entry
    and the result is merged into {"banks": [...]}.
    """
    path = Path(config_path)
    if path.is_dir():
        banks = []
        for f in sorted(path.glob("*.yaml")):
            with open(f, "r", encoding="utf-8") as fp:
                banks.append(yaml.safe_load(fp))
        return {"banks": banks}

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)