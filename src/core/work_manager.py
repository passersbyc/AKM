"""WorkManager — 薄 facade，委托到各个子模块。

保留对外 API 兼容性；仅保留实际被调用的方法。
"""
from pathlib import Path

from src.core.manifest import check_file_integrity
from src.core.work_repository import (
    read_all, write_all, append_one,
    get_by_id, get_by_author_local_id, get_by_series, get_by_source,
    update_entry, update_entry_full, delete_entries, rename_author,
    normalize_id,
)
from src.core.work_search import search
from src.core.work_stats import get_stats, aggregate
from src.core.work_index import (
    reindex_groups, reindex_all, delete_and_reindex,
    _update_file_prefix,
)
from src.core.work_source import (
    source_set, is_source_imported, mark_deleted,
)


class WorkManager:

    @classmethod
    def normalize_id(cls, id_str: str) -> str:
        return normalize_id(id_str)

    # ── CRUD ──

    @classmethod
    def read(cls) -> list[dict]:
        return read_all()

    @classmethod
    def write(cls, rows: list[dict]) -> None:
        write_all(rows)

    @classmethod
    def append(cls, entry: dict) -> None:
        append_one(entry)

    @classmethod
    def get_by_id(cls, book_id: str):
        return get_by_id(book_id)

    @classmethod
    def get_by_author_local_id(cls, local_id: str) -> list[dict]:
        return get_by_author_local_id(local_id)

    @classmethod
    def get_by_series(cls, series: str, exclude_id: str = "") -> list[dict]:
        return get_by_series(series, exclude_id)

    @classmethod
    def update_entry(cls, book_id: str, changes: dict) -> bool:
        return update_entry(book_id, changes)

    @classmethod
    def update_entry_full(cls, book_id: str, field_updates: dict,
                          new_author: str = "", new_series: str = ""):
        return update_entry_full(book_id, field_updates, new_author, new_series)

    @classmethod
    def delete_entries(cls, ids: set[str]) -> list[dict]:
        return delete_entries(ids)

    # ── 搜索 ──

    @classmethod
    def search(cls, query: str = "", author: str = "", series: str = "",
               file_type: str = "", tags: str = "", source: str = "",
               keyword: str = "", regex: bool = False, limit: int = 0,
               favorited: str = "") -> list[dict]:
        return search(query=query, author=author, series=series,
                      file_type=file_type, tags=tags, source=source,
                      keyword=keyword, regex=regex, limit=limit,
                      favorited=favorited)

    # ── 统计 ──

    @classmethod
    def get_stats(cls) -> dict:
        return get_stats()

    @classmethod
    def aggregate(cls, works: bool = False, authors: bool = False,
                  series: bool = False, types: bool = False) -> dict:
        return aggregate(works=works, authors=authors, series=series, types=types)

    # ── 重索引 ──

    @classmethod
    def reindex_groups(cls, rows: list[dict], sort_key=None) -> list[dict]:
        return reindex_groups(rows, sort_key)

    @classmethod
    def delete_and_reindex(cls, ids: set[str], keep_file: bool = False,
                           clear_tables: bool = False) -> list[dict]:
        return delete_and_reindex(ids, keep_file=keep_file, clear_tables=clear_tables)

    # ── 来源追踪 ──

    @classmethod
    def source_set(cls) -> set[str]:
        return source_set()

    @classmethod
    def mark_deleted(cls, source_urls: set[str]) -> int:
        return mark_deleted(source_urls)

    # ── 校验 ──

    @classmethod
    def verify_integrity(cls, book_id: str = None) -> dict:
        if book_id:
            row = cls.get_by_id(book_id)
            if not row:
                return {"id": book_id, "valid": False, "exists": False, "error": "未找到"}
            fp = Path(row.get("文件路径", ""))
            ok = check_file_integrity(fp) if fp.exists() else False
            return {"id": book_id, "name": row.get("标题"), "valid": ok, "exists": fp.exists()}

        results = []
        for row in cls.read():
            fp = Path(row.get("文件路径", ""))
            ok = check_file_integrity(fp) if fp.exists() else False
            results.append({"id": row.get("ID"), "name": row.get("标题"), "valid": ok, "exists": fp.exists()})
        return {"items": results, "total": len(results),
                "valid_count": sum(1 for r in results if r["valid"])}
