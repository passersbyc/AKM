"""模糊匹配工具 — ID 精确匹配 → 标题包含匹配 → 多结果选择。"""
from src.core.database import get_db, short_id, to_full_id


def resolve_work(target: str, output=None) -> dict | None:
    """解析作品：精确 ID → 短 ID → 标题包含匹配 → 多结果选择。

    返回 work dict（含 id, title, author_id, tags, series_id, file_type,
    favorite, rating, description, source, file_path, imported_at）或 None。
    """
    db = get_db()

    # 1. 精确全 ID 匹配
    row = db.execute(
        "SELECT * FROM works WHERE id = ?", (target,)
    ).fetchone()
    if row:
        return dict(row)

    # 2. 短 ID 匹配
    full_id = to_full_id(target)
    if full_id != target:
        row = db.execute(
            "SELECT * FROM works WHERE id = ?", (full_id,)
        ).fetchone()
        if row:
            return dict(row)

    # 3. 标题包含匹配
    rows = db.execute(
        "SELECT * FROM works WHERE title LIKE ? ORDER BY imported_at DESC",
        (f"%{target}%",),
    ).fetchall()
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
            output.info(f"  [{i}] [cyan]{short_id(r['id'])}[/cyan] {r['title']}")
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

    返回 author dict（含 id, name, source, homepage, favorite, note,
    pixiv_uid, follow_status）或 None。
    """
    db = get_db()

    # 1. 精确 ID 匹配
    row = db.execute(
        "SELECT a.*, pt.pixiv_uid, pt.homepage, pt.follow_status "
        "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
        "WHERE a.id = ?", (target,)
    ).fetchone()
    if row:
        return dict(row)

    # 2. 名称包含匹配
    rows = db.execute(
        "SELECT a.*, pt.pixiv_uid, pt.homepage, pt.follow_status "
        "FROM authors a LEFT JOIN pixiv_trackings pt ON a.id = pt.author_id "
        "WHERE a.name LIKE ? ORDER BY a.favorite DESC, a.name",
        (f"%{target}%",),
    ).fetchall()
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
            fav = " ♥" if r["favorite"] else ""
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
    db = get_db()
    if prefix:
        rows = db.execute(
            "SELECT id, title FROM works WHERE title LIKE ? ORDER BY imported_at DESC LIMIT ?",
            (f"%{prefix}%", limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, title FROM works ORDER BY imported_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [(r["id"], r["title"]) for r in rows]


def list_author_names(prefix: str = "", limit: int = 20) -> list[tuple[str, str]]:
    """查询作者名称前缀匹配，返回 [(id, name), ...] 供补全器使用。"""
    db = get_db()
    if prefix:
        rows = db.execute(
            "SELECT id, name FROM authors WHERE name LIKE ? ORDER BY favorite DESC, name LIMIT ?",
            (f"%{prefix}%", limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, name FROM authors ORDER BY favorite DESC, name LIMIT ?", (limit,)
        ).fetchall()
    return [(r["id"], r["name"]) for r in rows]
