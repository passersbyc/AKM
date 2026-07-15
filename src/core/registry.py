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


def _get_author_id(author: str) -> str:
    if not author or author == "佚名":
        return "000"
    db = get_db()
    cur = db.execute("SELECT id FROM authors WHERE name = ?", (author,))
    row = cur.fetchone()
    if row:
        return row[0]
    new_id = next_author_id()
    while True:
        conflict = db.execute("SELECT 1 FROM authors WHERE id = ?", (new_id,)).fetchone()
        if not conflict:
            break
        new_id = next_author_id()
    db.execute(
        "INSERT INTO authors (id, name, source) VALUES (?, ?, 'local')",
        (new_id, author),
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


def generate_id(file_type: str = "", author: str = "", series: str = "") -> str:
    author_id = _get_author_id(author) if author else "000"
    series_id = _get_series_id(author, series) if series else "00"
    return _make_work_id(file_type, author_id, series_id)


def short_id(book_id: str) -> str:
    return db_short_id(book_id)


def to_full_id(short: str) -> str:
    return db_to_full_id(short)


def author_folder_name(author: str) -> str:
    if not author:
        return author
    lid = _get_author_id(author)
    return f"{lid}_{author}" if lid else author


def series_folder_name(author: str, series: str) -> str:
    if not series:
        return series
    sid = _get_series_id(author, series)
    return f"{sid}_{series}"


def work_file_prefix(book_id: str) -> str:
    return db_work_file_prefix(book_id)
