"""共享 SQL 片段和 manifest 转换。"""
JOIN_SQL = """
    SELECT w.*, a.name AS _author_name, s.name AS _series_name
    FROM works w
    LEFT JOIN authors a ON w.author_id = a.id
    LEFT JOIN series s ON w.series_id = s.id AND s.author_id = w.author_id
"""


def row_to_manifest(row: dict) -> dict:
    return {
        "ID": row.get("id", ""),
        "标题": row.get("title", ""),
        "作者": row.get("_author_name", "") or "",
        "系列": row.get("_series_name", "") or "",
        "标签": row.get("tags", ""),
        "来源": row.get("source", ""),
        "源状态": row.get("source_status", "ok"),
        "后缀": row.get("file_ext", ""),
        "分类": row.get("file_type", ""),
        "导入时间": row.get("imported_at", ""),
        "文件大小(KB)": str(row.get("file_size_kb", 0)),
        "MD5": row.get("md5", ""),
        "文件路径": row.get("file_path", ""),
        "收藏": "是" if row.get("favorite") else "否",
        "评分": str(row.get("rating", "")) if row.get("rating") else "",
        "简介": row.get("description", ""),
        "点赞": str(row.get("likes", 0)),
    }
