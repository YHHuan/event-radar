"""路徑與設定載入。全部相對 / 環境變數,不寫死絕對路徑 (AGENTS §6)。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# project root = 此檔往上三層 (code/event_radar/config.py -> event-radar/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = Path(os.environ.get("EVENT_RADAR_DATA", PROJECT_ROOT / "data"))
DB_PATH = Path(os.environ.get("EVENT_RADAR_DB", DATA_DIR / "events.db"))


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def profile() -> dict:
    return load_yaml("profile.yaml")


def sources() -> dict:
    return load_yaml("sources.yaml")


def taste() -> dict:
    return load_yaml("taste.yaml")
