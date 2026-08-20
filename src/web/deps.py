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


def kid_mode() -> bool:
    """儿童模式开关（读设置）。"""
    cfg = load_config().get("project_settings", {}) or {}
    return bool(cfg.get("kid_mode", False))


def safe_search(**kw):
    """按当前儿童模式状态过滤的搜索（跨 router 共享）。"""
    from src.operations import search_works
    return search_works(**kw, safe_mode=kid_mode())
