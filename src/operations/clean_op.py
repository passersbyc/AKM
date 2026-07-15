"""clean 操作 - 清单读取和数据清理。"""
from src.core.work_manager import WorkManager


def read_all_entries() -> list[dict]:
    return WorkManager.read()


def delete_entries(ids: set[str]) -> list[dict]:
    return WorkManager.delete_entries(ids)


def source_set() -> set[str]:
    return WorkManager.source_set()


def get_pixiv_entries() -> list[dict]:
    rows = WorkManager.read()
    return [row for row in rows if "pixiv" in (row.get("来源", "") or "").lower()]
