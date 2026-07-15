"""作者活跃度计算 — 基于作品 published_at 判定活跃/正常/停更/注销。"""
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

from src.core.author_manager import get_by_id
from src.core.work_repository import read_all
from src.core.config import load_config

_STATUS_SYMBOLS = {
    "活跃":     "✿ 活跃",
    "正常":     "◎ 正常",
    "停更":     "· 停更",
    "注销":     "✕ 注销",
    "停止追更": "⊘ 停止追更",
}


def _decorate_status(raw: str) -> str:
    return _STATUS_SYMBOLS.get(raw, raw)


def _get_thresholds() -> dict:
    cfg = load_config()
    return cfg.get("author_activity", {
        "active": 20,
        "normal": 1,
        "inactive_days": 60,
    })


def compute_status(author_id: str, source: str, tracking_status: str,
                   last_checked: str = "",
                   stats: Optional[dict] = None) -> str:
    """返回: ✿ 活跃 | ◎ 正常 | · 停更 | ✕ 注销 | ⊘ 停止追更"""
    if source == "pixiv" and tracking_status == "dead":
        return _decorate_status("注销")
    if source == "pixiv" and tracking_status == "paused":
        return _decorate_status("停止追更")

    thresholds = _get_thresholds()
    now = datetime.now()
    cutoff_30d = now - timedelta(days=30)
    cutoff_inactive = now - timedelta(days=thresholds["inactive_days"])

    if stats:
        count_30d = stats.get("count_30d", 0)
        latest_pub = stats.get("latest_pub")
    else:
        count_30d = 0
        latest_pub = None
        for w in read_all():
            if w.get("作者_id", "") == author_id or w.get("作者", "") == _get_author_name(author_id):
                pub = w.get("published_at") or w.get("导入时间", "")
                if pub:
                    try:
                        dt = datetime.strptime(pub[:10], "%Y-%m-%d")
                        if dt >= cutoff_30d:
                            count_30d += 1
                        if latest_pub is None or dt > latest_pub:
                            latest_pub = dt
                    except ValueError:
                        pass

    if latest_pub is None:
        if source == "pixiv" and last_checked:
            try:
                dt = datetime.strptime(last_checked[:10], "%Y-%m-%d")
                if dt < cutoff_inactive:
                    return _decorate_status("停更")
            except ValueError:
                pass
        return _decorate_status("正常")

    if latest_pub < cutoff_inactive:
        return _decorate_status("停更")
    if count_30d >= thresholds["active"]:
        return _decorate_status("活跃")
    if count_30d >= thresholds["normal"]:
        return _decorate_status("正常")
    return _decorate_status("正常")


def _get_author_name(author_id: str) -> str:
    a = get_by_id(author_id)
    return a["name"] if a else author_id


def build_author_stats() -> dict[str, dict]:
    """一次扫描全表，返回 {author_name_or_id: {count_30d, latest_pub}} 供 compute_status 批量使用。"""
    thresholds = _get_thresholds()
    now = datetime.now()
    cutoff_30d = now - timedelta(days=30)

    stats: dict[str, dict] = {}
    for w in read_all():
        for key in (w.get("作者_id", ""), w.get("作者", "")):
            if not key:
                continue
            entry = stats.setdefault(key, {"count_30d": 0, "latest_pub": None})
            pub = w.get("published_at") or w.get("导入时间", "")
            if pub:
                try:
                    dt = datetime.strptime(pub[:10], "%Y-%m-%d")
                    if dt >= cutoff_30d:
                        entry["count_30d"] += 1
                    if entry["latest_pub"] is None or dt > entry["latest_pub"]:
                        entry["latest_pub"] = dt
                except ValueError:
                    pass
    return stats
