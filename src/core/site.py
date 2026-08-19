"""站点定义与推断 — 多站点分库的基础。

站点是数据隔离的一等维度：每个站点独立一个 SQLite 库文件，
主库 meta.db 只存站点注册表与全局元数据（recent_opens / settings）。
"""
from pathlib import Path

# 已知站点标识（与下载器 name 一致），local 为本地导入（无来源站点）
SITES = ["pixiv", "pawchive", "biquge", "asmrmoon", "local"]

# 站点短前缀（用于 ID 展示与解析，如 p.n.1.0.1 = pixiv 小说）
SITE_PREFIX = {
    "pixiv": "p",
    "pawchive": "w",
    "asmrmoon": "a",
    "biquge": "b",
    "local": "l",
}


def site_prefix(site: str) -> str:
    """站点 → 短前缀；未知返回空串。"""
    return SITE_PREFIX.get(site, "")


def prefix_to_site(prefix: str) -> str | None:
    """短前缀 → 站点；未知返回 None。"""
    for s, p in SITE_PREFIX.items():
        if p == prefix:
            return s
    return None


def infer_site(source: str) -> str:
    """从来源 URL 推断站点；空值 / 无法识别归为 local。"""
    s = (source or "").lower()
    if "pixiv.net" in s:
        return "pixiv"
    if "pawchive" in s:
        return "pawchive"
    if "asmrmoon" in s:
        return "asmrmoon"
    if "biquge" in s:
        return "biquge"
    return "local"


def site_db_path(site: str) -> Path:
    """站点库文件路径：data/db/{site}.db。"""
    from src.core.config import get_data_dir
    return get_data_dir() / "db" / f"{site}.db"


def meta_db_path() -> Path:
    """主库文件路径：data/meta.db。"""
    from src.core.config import get_data_dir
    return get_data_dir() / "meta.db"
