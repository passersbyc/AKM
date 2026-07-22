"""search 操作 — 作品搜索入口。"""

from src.core.work_search import search as _search


def search_works(
    query: str = "",
    author: str = "",
    series: str = "",
    file_type: str = "",
    tags: str = "",
    source: str = "",
    keyword: str = "",
    regex: bool = False,
    limit: int = 0,
    favorited: str = "",
    id_prefix: str = "",
    liked: str = "",
) -> list[dict]:
    items = _search(
        query=query,
        author=author,
        series=series,
        file_type=file_type,
        tags=tags,
        source=source,
        keyword=keyword,
        regex=regex,
        limit=limit,
        favorited=favorited,
    )

    if id_prefix:
        items = [item for item in items if item.get("ID", "").startswith(id_prefix)]

    if liked:
        if liked == "yes":
            items = [item for item in items if int(item.get("点赞", "0") or "0") > 0]
        else:
            items = [item for item in items if int(item.get("点赞", "0") or "0") == 0]

    return items


def search_by_label(query: str, limit: int = 50) -> list[dict]:
    """按标签搜索作品，返回 [{id, title, tags, file_type, favorite, rating, author_name}, ...]。"""
    from src.core.database import get_db
    db = get_db()
    rows = db.execute(
        "SELECT id, title, tags, file_type, favorite, rating, "
        "(SELECT a.name FROM authors a WHERE a.id = works.author_id) as author_name "
        "FROM works WHERE tags LIKE ? "
        "ORDER BY favorite DESC, rating DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def search_authors(query: str, limit: int = 0) -> list[dict]:
    """按名称搜索作者，返回 [{id, name, favorite, source, work_count}, ...]。limit<=0 表示全部。"""
    from src.core.database import get_db
    db = get_db()
    rows = db.execute(
        "SELECT a.id, a.name, a.favorite, a.source, "
        "COUNT(w.id) as work_count "
        "FROM authors a LEFT JOIN works w ON a.id = w.author_id "
        "WHERE a.name LIKE ? "
        "GROUP BY a.id ORDER BY a.favorite DESC, a.name",
        (f"%{query}%",),
    ).fetchall()
    if limit > 0:
        rows = rows[:limit]
    return [dict(r) for r in rows]
