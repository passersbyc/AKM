"""系列管理模块 — series 表唯一读写入口。"""
from src.core.database import get_db, init_db, next_series_id, dict_from_row, dicts_from_rows
from src.core.registry import _get_author_id


def _init() -> None:
    init_db()


def list_all() -> list[dict]:
    _init()
    db = get_db()
    rows = db.execute("""
        SELECT s.id, s.author_id, s.name, a.name AS author_name,
               COUNT(w.id) AS work_count,
               COALESCE(SUM(w.likes), 0) AS total_likes
        FROM series s
        JOIN authors a ON s.author_id = a.id
          LEFT JOIN works w ON w.series_id = s.id AND w.author_id = s.author_id
        GROUP BY s.id, s.author_id
         ORDER BY s.author_id, s.id
    """).fetchall()
    return dicts_from_rows(rows)


def get(series_name: str, author_id: str = "") -> dict | None:
    db = get_db()
    if author_id:
        row = db.execute(
            "SELECT * FROM series WHERE name = ? AND author_id = ?",
            (series_name.strip(), author_id),
        ).fetchone()
        return dict_from_row(row)
    row = db.execute(
        "SELECT * FROM series WHERE name = ?", (series_name.strip(),)
    ).fetchone()
    return dict_from_row(row)


def get_by_id(series_id: str, author_id: str) -> dict | None:
    db = get_db()
    row = db.execute(
        "SELECT * FROM series WHERE id = ? AND author_id = ?",
        (series_id, author_id),
    ).fetchone()
    return dict_from_row(row)


def resolve(target: str, author_id: str = "") -> dict | None:
    target = target.strip()
    if author_id:
        row = get_by_id(target, author_id)
        if row:
            return row
    return get(target, author_id)


def get_or_create(name: str, author_name: str = "", author_id: str = "") -> tuple[str, str]:
    """返回 (series_id, author_id)。series 不存在则创建。"""
    if not name:
        return "", ""
    from src.domain.cdbook import normalize_series_name
    name = normalize_series_name(name)
    if not author_id and author_name:
        author_id = _get_author_id(author_name)
    if not author_id:
        return "", ""

    existing = get(name, author_id)
    if existing:
        if existing["name"] != name:
            db = get_db()
            db.execute("UPDATE series SET name = ? WHERE id = ? AND author_id = ?", (name, existing["id"], author_id))
            db.commit()
        return existing["id"], author_id

    new_id = next_series_id(author_id)
    db = get_db()
    while True:
        conflict = db.execute(
            "SELECT 1 FROM series WHERE id = ? AND author_id = ?",
            (new_id, author_id),
        ).fetchone()
        if not conflict:
            break
        new_id = next_series_id(author_id)

    db.execute(
        "INSERT INTO series (id, author_id, name) VALUES (?, ?, ?)",
        (new_id, author_id, name),
    )
    db.commit()
    return new_id, author_id


def rename(old_name: str, author_name: str, new_name: str) -> int:
    author_id = _get_author_id(author_name)
    db = get_db()
    with db:
        cur = db.execute(
            "UPDATE series SET name = ? WHERE name = ? AND author_id = ?",
            (new_name.strip(), old_name.strip(), author_id),
        )
        return cur.rowcount


def delete(series_name: str, author_name: str = "", force: bool = False) -> tuple[int, bool]:
    """返回 (删除行数, 是否有作品被取消关联)。force=True 才能删除有关联作品的系列。"""
    if not author_name:
        return 0, False
    author_id = _get_author_id(author_name)
    db = get_db()

    if not force:
        count = db.execute(
            "SELECT COUNT(*) FROM works WHERE series_id = (SELECT id FROM series WHERE name = ? AND author_id = ?)",
            (series_name.strip(), author_id),
        ).fetchone()[0]
        if count > 0:
            return 0, False

    with db:
        sid = db.execute(
            "SELECT id FROM series WHERE name = ? AND author_id = ?",
            (series_name.strip(), author_id),
        ).fetchone()
        if not sid:
            return 0, False
        sid = sid[0]
        if force:
            db.execute(
                "UPDATE works SET series_id = '' WHERE series_id = ? AND author_id = ?",
                (sid, author_id),
            )
        cur = db.execute(
            "DELETE FROM series WHERE id = ? AND author_id = ?", (sid, author_id)
        )
        return cur.rowcount, force


def get_works(series_name: str, author_name: str = "", exclude_id: str = "") -> list[dict]:
    from src.core.work_repository import get_by_series, read_all
    if not author_name:
        return get_by_series(series_name, exclude_id=exclude_id)

    author_id = _get_author_id(author_name)
    sr = get(series_name, author_id)
    if not sr:
        return []

    rows = [w for w in read_all()
            if w.get("作者", "") == author_name and w.get("系列", "") == series_name
            and (not exclude_id or w.get("ID", "") != exclude_id)]
    rows.sort(key=lambda r: r.get("ID", ""))
    return rows
