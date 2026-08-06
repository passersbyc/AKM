from src.core.database import (
    get_db, reset_all_counters,
    _get_type_char as _db_get_type_char, _make_work_id,
    short_id as db_short_id, to_full_id as db_to_full_id,
    next_author_id, next_series_id,
    work_file_prefix as db_work_file_prefix,
)


def _flush_id_registry():
    pass


def _reset_id_registry():
    reset_all_counters()


def _get_type_char(file_type: str) -> str:
    return _db_get_type_char(file_type)


def _get_author_id(author: str, uid: str = "") -> str:
    if not author or author == "佚名":
        return "000"
    db = get_db()
    if uid and uid != "local":
        cur = db.execute(
            "SELECT a.id FROM authors a "
            "JOIN pixiv_trackings p ON p.author_id = a.id "
            "WHERE p.pixiv_uid = ?",
            (uid,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
    cur = db.execute(
        "SELECT a.id, p.pixiv_uid FROM authors a "
        "LEFT JOIN pixiv_trackings p ON p.author_id = a.id "
        "WHERE a.name = ?",
        (author,),
    )
    row = cur.fetchone()
    if row:
        row_uid = row["pixiv_uid"] if "pixiv_uid" in row.keys() else (row[1] if len(row) > 1 else "")
        # 名字兜底：命中行无 pixiv 身份（本地作者）才复用；有且 uid 不同 → 重名作者，新建
        if not uid or not row_uid or row_uid == uid:
            return row[0]
    new_id = next_author_id()
    while True:
        conflict = db.execute("SELECT 1 FROM authors WHERE id = ?", (new_id,)).fetchone()
        if not conflict:
            break
        new_id = next_author_id()
    db.execute(
        "INSERT INTO authors (id, name, source) VALUES (?, ?, ?)",
        (new_id, author, "pixiv" if uid else "local"),
    )
    if uid and uid != "local":
        import time as _time
        db.execute(
            "INSERT OR IGNORE INTO pixiv_trackings "
            "(author_id, pixiv_uid, follow_status, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?)",
            (new_id, uid, _time.strftime("%Y-%m-%d %H:%M:%S"),
             _time.strftime("%Y-%m-%d %H:%M:%S")),
        )
    return new_id


def _get_series_id(author: str, series: str) -> str:
    if not series:
        return "00"
    from src.domain.cdbook import normalize_series_name
    series = normalize_series_name(series)
    author_id = _get_author_id(author)
    db = get_db()
    cur = db.execute(
        "SELECT id FROM series WHERE author_id = ? AND name = ?",
        (author_id, series),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    new_id = next_series_id(author_id)
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
        (new_id, author_id, series),
    )
    return new_id


def generate_id(file_type: str = "", author: str = "", series: str = "",
                uid: str = "") -> str:
    # 带 uid 解析作者：避免同名变体（如改名）时新建分裂作者行/目录
    author_id = _get_author_id(author, uid) if author else "000"
    series_id = _get_series_id(author, series) if series else "00"
    return _make_work_id(file_type, author_id, series_id)


def short_id(book_id: str) -> str:
    return db_short_id(book_id)


def to_full_id(short: str) -> str:
    return db_to_full_id(short)


def author_folder_name(author: str, uid: str = "") -> str:
    if not author:
        return author
    lid = _get_author_id(author, uid)
    return f"{lid}_{author}" if lid else author


def series_folder_name(author: str, series: str, uid: str = "") -> str:
    if not series:
        return series
    sid = _get_series_id(author, series)
    return f"{sid}_{series}"


def work_file_prefix(book_id: str) -> str:
    return db_work_file_prefix(book_id)
