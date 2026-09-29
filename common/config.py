"""config.yaml 로더."""
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def mock_base_url(cfg: dict) -> str:
    return f"http://127.0.0.1:{cfg['server']['mock_port']}"


def gateway_base_url(cfg: dict) -> str:
    return f"http://127.0.0.1:{cfg['server']['gateway_port']}"
