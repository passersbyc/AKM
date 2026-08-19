"""模糊匹配工具 — ID 精确匹配 → 标题包含匹配 → 多结果选择。"""
from src.core.database import short_id, to_full_id, query_all_sites, get_site_db
from src.core.site import prefix_to_site


def _parse_site_prefix(target: str) -> tuple[str | None, str]:
    """解析站点前缀：p.n.1.0.1 → ('pixiv', 'n.1.0.1')；无前缀返回 (None, target)。"""
    parts = target.split(".")
    if len(parts) == 5:
        site = prefix_to_site(parts[0])
        if site:
            return site, ".".join(parts[1:])
    return None, target


def _query_works(site: str | None, sql: str, params=()):
    """站点定位查询：site 已知查该站点库，否则遍历站点库。返回 list[dict]。"""
    if site:
        return [dict(r) for r in get_site_db(site).execute(sql, params).fetchall()]
    return [dict(r) for r in query_all_sites(sql, params)]


def resolve_work(target: str, output=None) -> dict | None:
    """解析作品：精确 ID → 短 ID → 标题包含匹配 → 多结果选择。

    支持带站点前缀的 ID（如 p.n.1.0.1 = pixiv 小说）。
    返回 work dict（含 id, title, author_id, tags, series_id, file_type,
    favorite, rating, description, source, file_path, imported_at）或 None。
    """
    site, target = _parse_site_prefix(target)

    # 1. 精确全 ID 匹配
    rows = _query_works(site, "SELECT * FROM works WHERE id = ?", (target,))
    if rows:
        return dict(rows[0])

    # 2. 短 ID 匹配
    full_id = to_full_id(target)
    if full_id != target:
        rows = _query_works(site, "SELECT * FROM works WHERE id = ?", (full_id,))
        if rows:
            return dict(rows[0])

    # 3. 标题包含匹配
    rows = _query_works(
        site,
        "SELECT * FROM works WHERE title LIKE ? ORDER BY imported_at DESC",
        (f"%{target}%",),
    )
    if not rows:
        return None
    if len(rows) == 1:
        return dict(rows[0])

    # 4. 多结果选择
    if output and output.json_mode:
        return None  # json 模式不交互
    if output:
        output.info(f"找到 {len(rows)} 个匹配作品:")
        for i, r in enumerate(rows[:20]):
            output.info(f"  [{i}] [cyan]{short_id(r['id'], site)}[/cyan] {r['title']}")
        if len(rows) > 20:
            output.info(f"  ... 还有 {len(rows) - 20} 个")
        try:
            choice = input("输入序号选择 (回车取消): ").strip()
            if not choice:
                return None
            idx = int(choice)
            if 0 <= idx < len(rows):
                return dict(rows[idx])
        except (ValueError, EOFError, KeyboardInterrupt):
            return None
    return None


def resolve_author(target: str, output=None) -> dict | None:
    """解析作者：精确 ID → 名称包含匹配 → 多结果选择。

    支持带站点前缀的 ID。返回 author dict（含 id, name, source, homepage,
    favorite, note, pixiv_uid, follow_status）或 None。
    """
    site, target = _parse_site_prefix(target)

    # 1. 精确 ID 匹配
    rows = _query_works(
        site,
        "SELECT a.*, pt.pixiv_uid, pt.homepage, pt.follow_status "
        "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
        "WHERE a.id = ?", (target,)
    )
    if rows:
        return dict(rows[0])

    # 2. 名称包含匹配
    rows = _query_works(
        site,
        "SELECT a.*, pt.pixiv_uid, pt.homepage, pt.follow_status "
        "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
        "WHERE a.name LIKE ? ORDER BY a.favorite DESC, a.name",
        (f"%{target}%",),
    )
    if not rows:
        return None
    if len(rows) == 1:
        return dict(rows[0])

    # 3. 多结果选择
    if output and output.json_mode:
        return None
    if output:
        output.info(f"找到 {len(rows)} 个匹配作者:")
        for i, r in enumerate(rows[:20]):
            fav = " (◕‿◕)" if r["favorite"] else ""
            output.info(f"  [{i}] [cyan]{r['id']}[/cyan] {r['name']}{fav}")
        if len(rows) > 20:
            output.info(f"  ... 还有 {len(rows) - 20} 个")
        try:
            choice = input("输入序号选择 (回车取消): ").strip()
            if not choice:
                return None
            idx = int(choice)
            if 0 <= idx < len(rows):
                return dict(rows[idx])
        except (ValueError, EOFError, KeyboardInterrupt):
            return None
    return None


def list_work_titles(prefix: str = "", limit: int = 20) -> list[tuple[str, str]]:
    """查询作品标题前缀匹配，返回 [(id, title), ...] 供补全器使用。"""
    if prefix:
        rows = query_all_sites(
            "SELECT id, title FROM works WHERE title LIKE ? ORDER BY imported_at DESC",
            (f"%{prefix}%",),
        )
    else:
        rows = query_all_sites(
            "SELECT id, title FROM works ORDER BY imported_at DESC")
    return [(r["id"], r["title"]) for r in rows][:limit]


def list_author_names(prefix: str = "", limit: int = 20) -> list[tuple[str, str]]:
    """查询作者名称前缀匹配，返回 [(id, name), ...] 供补全器使用。"""
    if prefix:
        rows = query_all_sites(
            "SELECT id, name FROM authors WHERE name LIKE ? ORDER BY favorite DESC, name",
            (f"%{prefix}%",),
        )
    else:
        rows = query_all_sites(
            "SELECT id, name FROM authors ORDER BY favorite DESC, name")
    return [(r["id"], r["name"]) for r in rows][:limit]

