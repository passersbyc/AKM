import sqlite3
import threading
from pathlib import Path
from src.core.config import get_data_dir
from src.core.logging import get_logger

_log = get_logger("akm.database")

_db_connection: sqlite3.Connection | None = None
_db_lock = threading.Lock()
_db_path_cache: str = ""

TYPE_CHAR_MAP = {"小说": "n", "漫画": "c", "音乐": "m", "电影": "f", "图片": "i", "美图集": "i"}
BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(num: int, length: int) -> str:
    if num == 0:
        return BASE36[0] * length
    result = ""
    while num > 0:
        num, rem = divmod(num, 36)
        result = BASE36[rem] + result
    return result.zfill(length)


def _get_db_path() -> Path:
    from src.core.config import load_config, get_data_dir
    cfg = load_config()
    db_path_str = cfg.get("project_settings", {}).get("db_path")
    if db_path_str:
        p = Path(db_path_str)
        if not p.is_absolute():
            from src.core.config import get_project_root
            p = (get_project_root() / p).absolute()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return get_data_dir() / "library.db"


def get_db() -> sqlite3.Connection:
    global _db_connection, _db_path_cache
    db_path_str = str(_get_db_path())
    if _db_connection is not None and db_path_str == _db_path_cache:
        return _db_connection
    with _db_lock:
        if _db_connection is not None:
            try:
                _db_connection.close()
            except Exception:
                _log.debug("关闭旧数据库连接失败", exc_info=True)
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db_connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _db_connection.execute("PRAGMA journal_mode=WAL")
        _db_connection.execute("PRAGMA foreign_keys=ON")
        _db_connection.row_factory = sqlite3.Row
        _db_path_cache = str(db_path)
    return _db_connection


def dict_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def dicts_from_rows(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def init_db() -> None:
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS authors (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL DEFAULT '',
            aliases         TEXT DEFAULT '',
            source          TEXT DEFAULT 'local',
            note            TEXT DEFAULT '',
            favorite        INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pixiv_trackings (
            author_id       TEXT PRIMARY KEY REFERENCES authors(id),
            pixiv_uid       TEXT NOT NULL UNIQUE,
            homepage        TEXT DEFAULT '',
            follow_status   TEXT DEFAULT 'active',
            latest_work_id  TEXT DEFAULT '',
            last_checked    TEXT DEFAULT '',
            note            TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pixiv_trackings_uid ON pixiv_trackings(pixiv_uid);

        CREATE TABLE IF NOT EXISTS series (
            id          TEXT NOT NULL,
            author_id   TEXT NOT NULL REFERENCES authors(id),
            name        TEXT NOT NULL,
            PRIMARY KEY (id, author_id),
            UNIQUE(author_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_series_author ON series(author_id);

        CREATE TABLE IF NOT EXISTS works (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL DEFAULT '',
            author_id       TEXT NOT NULL DEFAULT '' REFERENCES authors(id),
            series_id       TEXT DEFAULT '',
            tags            TEXT DEFAULT '',
            source          TEXT DEFAULT '',
            source_status   TEXT DEFAULT 'ok',
            file_ext        TEXT DEFAULT '',
            file_type       TEXT DEFAULT '',
            imported_at     TEXT DEFAULT '',
            published_at    TEXT DEFAULT '',
            file_size_kb    REAL DEFAULT 0,
            md5             TEXT DEFAULT '',
            file_path       TEXT DEFAULT '',
            favorite        INTEGER DEFAULT 0,
            rating          REAL DEFAULT 0,
            description     TEXT DEFAULT '',
            likes           INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_works_author ON works(author_id);
        CREATE INDEX IF NOT EXISTS idx_works_series ON works(series_id);
        CREATE INDEX IF NOT EXISTS idx_works_md5 ON works(md5);
        CREATE INDEX IF NOT EXISTS idx_works_source ON works(source);

        CREATE TABLE IF NOT EXISTS download_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT NOT NULL UNIQUE,
            author_id   TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',
            added_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS id_counters (
            name    TEXT PRIMARY KEY,
            value   INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS pixiv_likes (
            work_id     TEXT PRIMARY KEY,
            like_count  INTEGER DEFAULT 0,
            title       TEXT DEFAULT '',
            author      TEXT DEFAULT '',
            updated_at  REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pixiv_blacklist (
            work_id TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recent_opens (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id     TEXT NOT NULL,
            title       TEXT DEFAULT '',
            opened_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_recent_opens_time ON recent_opens(opened_at DESC);
    """)
    try:
        db.execute("ALTER TABLE authors ADD COLUMN favorite INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE pixiv_trackings DROP COLUMN is_active")
    except sqlite3.OperationalError:
        pass


def next_counter(name: str) -> int:
    db = get_db()
    with db:
        cur = db.execute("SELECT value FROM id_counters WHERE name = ?", (name,))
        row = cur.fetchone()
        if row is None:
            db.execute("INSERT INTO id_counters (name, value) VALUES (?, 1)", (name,))
            return 1
        new_val = row[0] + 1
        db.execute("UPDATE id_counters SET value = ? WHERE name = ?", (new_val, name))
        return new_val


def get_counter(name: str) -> int:
    cur = get_db().execute("SELECT value FROM id_counters WHERE name = ?", (name,))
    row = cur.fetchone()
    return row[0] if row else 0


def reset_counter(name: str) -> None:
    db = get_db()
    with db:
        db.execute("DELETE FROM id_counters WHERE name = ?", (name,))


def reset_all_counters() -> None:
    get_db().execute("DELETE FROM id_counters")


def _get_type_char(file_type: str) -> str:
    return TYPE_CHAR_MAP.get(file_type, "0")


def _make_work_id(file_type: str, author_id: str, series_id: str = "") -> str:
    type_char = _get_type_char(file_type) if file_type else "0"
    author_id = author_id or "000"
    series_part = series_id or "00"
    counter_key = f"work:{type_char}:{author_id}:{series_part}"
    seq = next_counter(counter_key)
    work_id = _to_base36(seq, 4)
    return f"{type_char}{author_id}{series_part}{work_id}"


def next_author_id() -> str:
    seq = next_counter("author_seq")
    return _to_base36(seq, 3)


def next_series_id(author_id: str) -> str:
    seq = next_counter(f"series:{author_id}")
    return _to_base36(seq, 2)


def short_id(book_id: str) -> str:
    if not book_id:
        return book_id
    if len(book_id) < 10:
        return book_id
    t, a, s, w = book_id[0], book_id[1:4], book_id[4:6], book_id[6:]
    return f"{t}.{a.lstrip('0') or '0'}.{s.lstrip('0') or '0'}.{w.lstrip('0') or '0'}"


def to_full_id(short: str) -> str:
    if "." in short:
        parts = short.split(".")
        if len(parts) == 4:
            t, a, s, w = parts
            return f"{t}{a.zfill(3)}{s.zfill(2)}{w.zfill(4)}"
        return short
    if short and len(short) < 10 and not short.startswith(("-", ".")):
        t = short[0]
        rest = short[1:]
        padded = rest.zfill(9)
        return t + padded
    return short


def author_folder_name(author_id: str, author_name: str) -> str:
    return f"{author_id}_{author_name}" if author_id else author_name


def series_folder_name(series_id: str, series_name: str) -> str:
    if not series_name:
        return series_name
    return f"{series_id}_{series_name}"


def work_file_prefix(book_id: str) -> str:
    return book_id[-4:] if len(book_id) >= 4 else book_id
