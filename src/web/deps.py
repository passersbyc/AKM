"""Web 层依赖注入：配置/路径注入。"""
from __future__ import annotations

from pathlib import Path

from src.core.config import load_config, get_library_path


def get_config() -> dict:
    """返回当前 config.json 全量配置。"""
    return load_config()


def get_library_dir() -> Path:
    """返回作品库目录路径。"""
    return Path(get_library_path())
