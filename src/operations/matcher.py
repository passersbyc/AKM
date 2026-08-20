"""模糊匹配工具 — ID 精确匹配 → 标题包含匹配 → 多结果选择。"""
from src.core.database import short_id, to_full_id, query_all_sites, get_site_db, BASE36
from src.core.site import prefix_to_site, site_prefix, SITES


def _parse_site_prefix(target: str) -> tuple[str | None, str]:
    """解析站点前缀：p.n.1.0.1 → ('pixiv', 'n.1.0.1')；无前缀返回 (None, target)。"""
    parts = target.split(".")
    if len(parts) == 5:
        site = prefix_to_site(parts[0])
        if site:
            return site, ".".join(parts[1:])
    return None, target


def _parse_author_prefix(target: str) -> tuple[str | None, str]:
    """解析作者号前缀：p.1 / p.001 → ('pixiv', '1'/'001')；无前缀返回 (None, target)。"""
    parts = target.split(".")
    if len(parts) == 2:
        site = prefix_to_site(parts[0])
        if site:
            return site, parts[1]
    return None, target


def _query_works(site: str | None, sql: str, params=()):
    """站点定位查询：site 已知查该站点库，否则遍历站点库。

    每行结果附加 _site 字段，供跨站点歧义时区分。
    """
    if site:
        rows = [dict(r) for r in get_site_db(site).execute(sql, params).fetchall()]
        for r in rows:
            r["_site"] = site
        return rows
    out: list[dict] = []
    for s in SITES:
        for r in get_site_db(s).execute(sql, params).fetchall():
            d = dict(r)
            d["_site"] = s
            out.append(d)
    return out


def _pick(rows: list[dict], output, kind: str, label_fn) -> dict | None:
    """唯一则返回；多条则交互选择（json 模式或无 output 时返回 None）。"""
    if not rows:
        return None
    if len(rows) == 1:
        return dict(rows[0])
    if output and output.json_mode:
        return None
    if not output:
        return None
    output.info(f"找到 {len(rows)} 个匹配{kind}:")
    for i, r in enumerate(rows[:20]):
        fav = " (◕‿◕)" if r.get("favorite") else ""
        output.info(f"  [{i}] [cyan]{label_fn(r)}[/cyan] {r.get('title', r.get('name', ''))}{fav}")
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


def resolve_work(target: str, output=None) -> dict | None:
    """解析作品：精确 ID → 短 ID → 标题包含匹配 → 多结果选择。

    支持带站点前缀的 ID（如 p.n.1.0.1 = pixiv 小说）。
    返回 work dict（含 id, title, author_id, tags, series_id, file_type,
    favorite, rating, description, source, file_path, imported_at）或 None。
    """
    site, target = _parse_site_prefix(target)

    def _label(r: dict) -> str:
        return short_id(r["id"], r.get("_site") or site)

    # 1. 精确全 ID 匹配
    rows = _query_works(site, "SELECT * FROM works WHERE id = ?", (target,))
    if rows:
        return _pick(rows, output, "作品", _label)

    # 2. 短 ID 匹配
    full_id = to_full_id(target)
    if full_id != target:
        rows = _query_works(site, "SELECT * FROM works WHERE id = ?", (full_id,))
        if rows:
            return _pick(rows, output, "作品", _label)

    # 3. 标题包含匹配
    rows = _query_works(
        site,
        "SELECT * FROM works WHERE title LIKE ? ORDER BY imported_at DESC",
        (f"%{target}%",),
    )
    return _pick(rows, output, "作品", _label)


def resolve_author(target: str, output=None) -> dict | None:
    """解析作者：精确 ID → 名称包含匹配 → 多结果选择。

    支持带站点前缀的 ID。返回 author dict（含 id, name, source, homepage,
    favorite, note, pixiv_uid, follow_status）或 None。
    """
    site, target = _parse_author_prefix(target)

    def _label(r: dict) -> str:
        s = r.get("_site") or site
        prefix = site_prefix(s) if s else ""
        return f"{prefix}.{r['id']}" if prefix else r["id"]

    def _finalize(result: dict | None) -> dict | None:
        """合并主页：优先 authors.homepage，回退 pixiv_trackings.homepage。"""
        if result:
            result["homepage"] = result.get("homepage") or result.get("tracking_homepage") or ""
        return result

    # 1. 精确 ID 匹配
    rows = _query_works(
        site,
        "SELECT a.*, pt.pixiv_uid, pt.homepage AS tracking_homepage, pt.follow_status "
        "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
        "WHERE a.id = ?", (target,)
    )
    if rows:
        return _finalize(_pick(rows, output, "作者", _label))

    # 1.5 短作者号匹配（去前导零，如 1 → 001、a → 00a）
    if target and len(target) < 3 and all(c in BASE36 for c in target.lower()):
        padded = target.lower().zfill(3)
        rows = _query_works(
            site,
            "SELECT a.*, pt.pixiv_uid, pt.homepage AS tracking_homepage, pt.follow_status "
            "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
            "WHERE a.id = ?", (padded,)
        )
        if rows:
            return _finalize(_pick(rows, output, "作者", _label))

    # 2. 名称包含匹配
    rows = _query_works(
        site,
        "SELECT a.*, pt.pixiv_uid, pt.homepage AS tracking_homepage, pt.follow_status "
        "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
        "WHERE a.name LIKE ? ORDER BY a.favorite DESC, a.name",
        (f"%{target}%",),
    )
    return _finalize(_pick(rows, output, "作者", _label))


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

