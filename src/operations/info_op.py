"""info 操作 - 按资源类型分发。"""
from src.core.work_manager import WorkManager
from src.core.author_manager import resolve as author_resolve, get_by_id as author_by_id, compute_author_top_tags
from src.core.series_manager import get as series_get, get_works as series_works
from src.core.database import get_db


def get_info(target: str, target_type: str = "book") -> dict | None:
    if target_type == "book":
        return WorkManager.get_by_id(target)
    if target_type == "author":
        author = author_resolve(target)
        if not author:
            return None
        works = WorkManager.get_by_author_local_id(author["id"])
        top_tags = compute_author_top_tags(author["id"])
        return {"author": author, "works": works, "top_tags": top_tags}
    if target_type == "series":
        series = series_get(target)
        if not series:
            series = _series_by_name(target)
        if not series:
            return None
        author_name = _author_name(series.get("author_id", ""))
        works = series_works(target, author_name)
        return {"series": series, "author_name": author_name, "works": works}
    return None


def _series_by_name(name: str) -> dict | None:
    db = get_db()
    from src.core.database import dict_from_row
    row = db.execute("SELECT * FROM series WHERE name = ?", (name.strip(),)).fetchone()
    return dict_from_row(row)


def _author_name(author_id: str) -> str:
    author = author_by_id(author_id)
    return author["name"] if author else author_id


def get_related_works(series: str, exclude_id: str = "") -> list[dict]:
    return WorkManager.get_by_series(series, exclude_id=exclude_id)
