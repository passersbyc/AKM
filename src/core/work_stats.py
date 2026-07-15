"""作品统计 — 总量、分类、作者聚合等。"""
from src.core.database import get_db
from src.core.queries import JOIN_SQL, row_to_manifest


def get_stats() -> dict:
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    author_count = db.execute("SELECT COUNT(DISTINCT author_id) FROM works").fetchone()[0]
    series_count = db.execute("SELECT COUNT(DISTINCT series_id) FROM works WHERE series_id != ''").fetchone()[0]
    type_count = db.execute("SELECT COUNT(DISTINCT file_type) FROM works WHERE file_type != ''").fetchone()[0]
    total_size = db.execute("SELECT COALESCE(SUM(file_size_kb), 0) FROM works").fetchone()[0]

    return {
        "total_books": total,
        "total_authors": author_count,
        "total_series": series_count,
        "total_types": type_count,
        "total_size_kb": round(total_size, 2),
        "total_size_mb": round(total_size / 1024, 2),
    }


def aggregate(works: bool = False, authors: bool = False,
              series: bool = False, types: bool = False) -> dict:
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    result = {"total": total}

    if works:
        rows = db.execute(JOIN_SQL + " ORDER BY w.series_id, w.id, w.title").fetchall()
        result["works"] = sorted(
            [row_to_manifest(dict(r)) for r in rows],
            key=lambda r: (r.get("系列", ""), r.get("ID", ""), r.get("标题", "")))

    if authors:
        rows = db.execute("""
            SELECT a.name, COUNT(w.id) as cnt, GROUP_CONCAT(DISTINCT s.name) as series_list,
                   GROUP_CONCAT(DISTINCT w.file_type) as type_list
            FROM works w
            JOIN authors a ON w.author_id = a.id
            LEFT JOIN series s ON w.series_id = s.id AND s.author_id = w.author_id
            GROUP BY a.id, a.name
            ORDER BY cnt DESC
        """).fetchall()
        author_stats = {}
        for r in rows:
            name = r[0] or "未知"
            s_list = [x for x in (r[2] or "").split(",") if x]
            t_list = [x for x in (r[3] or "").split(",") if x]
            author_stats[name] = {"count": r[1], "series": s_list, "types": t_list}
        result["authors"] = author_stats

    if series:
        rows = db.execute("""
            SELECT s.name, COUNT(w.id) as cnt, GROUP_CONCAT(DISTINCT a.name) as author_list
            FROM series s
              JOIN works w ON w.series_id = s.id AND w.author_id = s.author_id
            JOIN authors a ON s.author_id = a.id
            GROUP BY s.id, s.name
            ORDER BY cnt DESC
        """).fetchall()
        series_stats = {}
        for r in rows:
            name = r[0] or ""
            if not name:
                continue
            a_list = [x for x in (r[2] or "").split(",") if x]
            series_stats[name] = {"count": r[1], "authors": a_list}
        result["series"] = series_stats

    if types:
        rows = db.execute(
            "SELECT file_type, COUNT(*) FROM works WHERE file_type != '' GROUP BY file_type ORDER BY COUNT(*) DESC"
        ).fetchall()
        result["types"] = {r[0] or "未知": r[1] for r in rows}

    return result
