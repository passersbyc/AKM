"""作品来源追踪 — 源 URL 的去重检测和状态标记。"""
from src.core.database import get_db


def source_set() -> set[str]:
    from src.core.database import query_all_sites
    rows = query_all_sites("SELECT DISTINCT source FROM works")
    return {r["source"] for r in rows if r["source"]}


def is_source_imported(url: str) -> bool:
    if not url:
        return False
    from src.core.database import query_all_sites
    rows = query_all_sites(
        "SELECT 1 FROM works WHERE source = ? LIMIT 1", (url.strip(),))
    return bool(rows)


def mark_deleted(source_urls: set[str]) -> int:
    if not source_urls:
        return 0
    from src.core.site import infer_site
    from src.core.database import get_site_db
    total = 0
    groups: dict[str, list[str]] = {}
    for u in source_urls:
        groups.setdefault(infer_site(u), []).append(u)
    for site, urls in groups.items():
        db = get_site_db(site)
        with db:
            placeholders = ",".join("?" for _ in urls)
            cur = db.execute(
                f"UPDATE works SET source_status = 'deleted' WHERE source IN ({placeholders})",
                urls,
            )
            total += cur.rowcount
    return total
