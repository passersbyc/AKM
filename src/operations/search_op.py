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
