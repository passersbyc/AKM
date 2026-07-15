"""作品搜索 — 支持多字段筛选、正则和关键词搜索。"""
import re as re_mod

from src.core.database import get_db
from src.core.queries import JOIN_SQL, row_to_manifest


def search(query: str = "", author: str = "", series: str = "",
           file_type: str = "", tags: str = "", source: str = "",
           keyword: str = "", regex: bool = False, limit: int = 0,
           favorited: str = "") -> list[dict]:
    db = get_db()
    rows = db.execute(JOIN_SQL).fetchall()
    if not rows:
        return []

    manifest_rows = [row_to_manifest(dict(r)) for r in rows]

    def build_matcher(pattern, use_regex):
        if not pattern:
            return None
        if use_regex:
            try:
                r = re_mod.compile(pattern, re_mod.IGNORECASE)
            except re_mod.error:
                return None
            return lambda v: bool(r.search(v or ""))
        lowered = pattern.lower().split()
        return lambda v: all(k in (v or "").lower() for k in lowered)

    matchers = {
        "query": build_matcher(query, regex),
        "author": build_matcher(author, regex),
        "series": build_matcher(series, regex),
        "file_type": build_matcher(file_type, regex),
        "tags": build_matcher(tags, regex),
        "source": build_matcher(source, regex),
        "keyword": build_matcher(keyword, regex),
    }
    field_map = {"query": "标题", "author": "作者", "series": "系列",
                 "file_type": "分类", "tags": "标签", "source": "来源"}
    keyword_fields = ["标题", "作者", "系列", "标签", "来源"]

    results = []
    for row in manifest_rows:
        match = True
        for key, matcher in matchers.items():
            if matcher is None:
                continue
            if key == "keyword":
                if not any(matcher(row.get(f, "")) for f in keyword_fields):
                    match = False
                    break
            else:
                col = field_map.get(key, key)
                if not matcher(row.get(col, "")):
                    match = False
                    break
        if match and favorited:
            fv = row.get("收藏", "").strip()
            if favorited == "yes" and fv != "是":
                continue
            if favorited == "no" and fv == "是":
                continue
        if match:
            results.append(row)
            if limit > 0 and len(results) >= limit:
                break
    return results
