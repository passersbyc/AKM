"""verify 操作 — 文件完整性校验入口。"""

from src.core.work_manager import WorkManager


def verify_integrity(book_id: str | None = None) -> dict:
    return WorkManager.verify_integrity(book_id)
