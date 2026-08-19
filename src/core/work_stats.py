"""作品统计 — 总量、分类、作者聚合等。"""


def get_stats() -> dict:
    from src.core.site import SITES
    from src.core.database import get_site_db
    total = 0
    authors: set[tuple[str, str]] = set()   # (site, author_id) 去重
    series: set[tuple[str, str, str]] = set()  # (site, series_id, author_id) 去重
    types: set[str] = set()
    total_size = 0.0
    for site in SITES:
        db = get_site_db(site)
        total += db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        for r in db.execute("SELECT DISTINCT author_id FROM works").fetchall():
            authors.add((site, r[0]))
        for r in db.execute("SELECT id, author_id FROM series").fetchall():
            series.add((site, r[0], r[1]))
        for r in db.execute("SELECT DISTINCT file_type FROM works WHERE file_type != ''").fetchall():
            types.add(r[0])
        total_size += db.execute("SELECT COALESCE(SUM(file_size_kb), 0) FROM works").fetchone()[0]

    return {
        "total_books": total,
        "total_authors": len(authors),
        "total_series": len(series),
        "total_types": len(types),
        "total_size_kb": round(total_size, 2),
        "total_size_mb": round(total_size / 1024, 2),
    }


def aggregate(works: bool = False, authors: bool = False,
              series: bool = False, types: bool = False) -> dict:
    from src.core.site import SITES
    from src.core.database import get_site_db
    from src.core.work_repository import read_all

    total = 0
    for site in SITES:
        total += get_site_db(site).execute("SELECT COUNT(*) FROM works").fetchone()[0]
    result = {"total": total}

    if works:
        result["works"] = sorted(
            read_all(),
            key=lambda r: (r.get("系列", ""), r.get("ID", ""), r.get("标题", "")))

    if authors:
        author_map: dict[str, dict] = {}
        for site in SITES:
            db = get_site_db(site)
            rows = db.execute("""
                SELECT a.name, COUNT(w.id) as cnt, GROUP_CONCAT(DISTINCT s.name) as series_list,
                       GROUP_CONCAT(DISTINCT w.file_type) as type_list
                FROM works w
                JOIN authors a ON w.author_id = a.id
                LEFT JOIN series s ON w.series_id = s.id AND s.author_id = w.author_id
                GROUP BY a.id, a.name
            """).fetchall()
            for r in rows:
                name = r[0] or "未知"
                d = author_map.setdefault(name, {"count": 0, "series": set(), "types": set()})
                d["count"] += r[1]
                d["series"].update(x for x in (r[2] or "").split(",") if x)
                d["types"].update(x for x in (r[3] or "").split(",") if x)
        result["authors"] = {
            name: {"count": d["count"], "series": sorted(d["series"]), "types": sorted(d["types"])}
            for name, d in sorted(author_map.items(), key=lambda kv: -kv[1]["count"])
        }

    if series:
        series_map: dict[str, dict] = {}
        for site in SITES:
            db = get_site_db(site)
            rows = db.execute("""
                SELECT s.name, COUNT(w.id) as cnt, GROUP_CONCAT(DISTINCT a.name) as author_list
                FROM series s
                  JOIN works w ON w.series_id = s.id AND w.author_id = s.author_id
                JOIN authors a ON s.author_id = a.id
                GROUP BY s.id, s.name
            """).fetchall()
            for r in rows:
                name = r[0] or ""
                if not name:
                    continue
                d = series_map.setdefault(name, {"count": 0, "authors": set()})
                d["count"] += r[1]
                d["authors"].update(x for x in (r[2] or "").split(",") if x)
        result["series"] = {
            name: {"count": d["count"], "authors": sorted(d["authors"])}
            for name, d in sorted(series_map.items(), key=lambda kv: -kv[1]["count"])
        }

    if types:
        type_map: dict[str, int] = {}
        for site in SITES:
            db = get_site_db(site)
            rows = db.execute(
                "SELECT file_type, COUNT(*) FROM works WHERE file_type != '' GROUP BY file_type"
            ).fetchall()
            for r in rows:
                key = r[0] or "未知"
                type_map[key] = type_map.get(key, 0) + r[1]
        result["types"] = dict(sorted(type_map.items(), key=lambda kv: -kv[1]))

    return result
