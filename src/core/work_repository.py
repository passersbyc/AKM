"""作品数据访问层 — 所有 works 表的 CRUD 操作。"""
import threading
import shutil
from pathlib import Path, PurePath

from src.core.config import MANIFEST_FIELDS
from src.core.database import (
    get_db, init_db,
    dict_from_row,
    _make_work_id,
)
from src.core.registry import _get_author_id, _get_series_id, to_full_id, _flush_id_registry
from src.core.resolvers import resolve_author_id, resolve_series_id
from src.core.filetype import determine_file_type
from src.core.paths import build_import_target
from src.core.queries import JOIN_SQL, row_to_manifest
from src.core.author_manager import rename as _rename
from src.domain.cdbook import normalize_series_name

_lock = threading.Lock()


def normalize_id(id_str: str) -> str:
    return to_full_id(id_str.strip())


def read_all() -> list[dict]:
    init_db()
    db = get_db()
    rows = db.execute(JOIN_SQL + " ORDER BY w.id").fetchall()
    return [row_to_manifest(dict(r)) for r in rows]


def write_all(rows: list[dict]) -> None:
    db = get_db()
    with db:
        db.execute("DELETE FROM works")
        for entry in rows:
            _append_raw(db, entry)


def append_one(entry: dict) -> None:
    db = get_db()
    with db:
        _append_raw(db, entry)


def _append_raw(db, entry: dict) -> None:
    author_name = entry.get("作者", "")
    author_id = resolve_author_id(author_name)
    series_name = entry.get("系列", "")
    series_id = resolve_series_id(author_id, series_name) if series_name else ""
    db.execute(
        """INSERT INTO works (id, title, author_id, series_id, tags, source,
           source_status, file_ext, file_type, imported_at, file_size_kb,
           md5, file_path, favorite, rating, description, likes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.get("ID", ""),
            entry.get("标题", ""),
            author_id,
            series_id,
            entry.get("标签", ""),
            entry.get("来源", ""),
            entry.get("源状态", "ok"),
            entry.get("后缀", ""),
            entry.get("分类", ""),
            entry.get("导入时间", ""),
            float(entry.get("文件大小(KB)", 0) or 0),
            entry.get("MD5", ""),
            entry.get("文件路径", ""),
            1 if entry.get("收藏", "否") == "是" else 0,
            float(entry.get("评分", 0) or 0),
            entry.get("简介", ""),
            int(entry.get("点赞", 0) or 0),
        ),
    )


def get_by_id(book_id: str) -> dict | None:
    book_id = normalize_id(book_id)
    db = get_db()
    row = db.execute(
        JOIN_SQL + " WHERE w.id = ?", (book_id,)
    ).fetchone()
    if row:
        return row_to_manifest(dict(row))
    return None


def get_by_author_local_id(local_id: str) -> list[dict]:
    db = get_db()
    rows = db.execute(
        JOIN_SQL + " WHERE w.author_id = ? ORDER BY w.id",
        (local_id,),
    ).fetchall()
    return [row_to_manifest(dict(r)) for r in rows]


def get_by_series(series: str, exclude_id: str = "") -> list[dict]:
    db = get_db()
    rows = db.execute(
        JOIN_SQL + " WHERE s.name = ? AND w.id != ? ORDER BY w.id",
        (series.strip(), exclude_id),
    ).fetchall()
    return [row_to_manifest(dict(r)) for r in rows]


def get_by_source(url: str) -> dict | None:
    db = get_db()
    row = db.execute(
        JOIN_SQL + " WHERE w.source = ?", (url.strip(),)
    ).fetchone()
    if row:
        return row_to_manifest(dict(row))
    return None


def update_entry(book_id: str, changes: dict) -> bool:
    book_id = normalize_id(book_id)
    db = get_db()
    valid = {k: v for k, v in changes.items() if k in MANIFEST_FIELDS}
    if not valid:
        return False
    field_map = {
        "标题": "title", "作者": "author_id", "系列": "series_id",
        "标签": "tags", "来源": "source", "源状态": "source_status",
        "后缀": "file_ext", "分类": "file_type", "导入时间": "imported_at",
        "文件大小(KB)": "file_size_kb", "MD5": "md5", "文件路径": "file_path",
        "收藏": "favorite", "评分": "rating", "简介": "description", "点赞": "likes",
    }
    set_parts = []
    values = []
    for k, v in valid.items():
        col = field_map.get(k, k)
        if col == "favorite":
            values.append(1 if v == "是" else 0)
        elif col == "author_id":
            values.append(resolve_author_id(str(v)))
        elif col == "series_id":
            author_name = changes.get("作者", "")
            aid = resolve_author_id(author_name) if author_name else ""
            values.append(resolve_series_id(aid, str(v)) if v else "")
        else:
            values.append(str(v) if v is not None else "")
        set_parts.append(f"{col} = ?")
    values.append(book_id)
    with db:
        cur = db.execute(
            f"UPDATE works SET {', '.join(set_parts)} WHERE id = ?", values
        )
        return cur.rowcount > 0


def update_entry_full(book_id: str, field_updates: dict,
                      new_author: str = "", new_series: str = "") -> dict | None:
    book_id = normalize_id(book_id)

    db = get_db()
    row = db.execute(JOIN_SQL + " WHERE w.id = ?", (book_id,)).fetchone()
    if not row:
        return None
    row_dict = dict(row)

    old_author_name = row_dict.get("_author_name", "")
    old_series_name = row_dict.get("_series_name", "")

    final_author_name = new_author or old_author_name
    final_series_name = new_series or old_series_name
    if new_series:
        final_series_name = normalize_series_name(new_series)

    final_author_id = resolve_author_id(final_author_name)
    final_series_id = resolve_series_id(final_author_id, final_series_name) if final_series_name else ""

    need_move = False
    if new_author and new_author != old_author_name:
        need_move = True
    if new_series and final_series_name != old_series_name:
        need_move = True

    old_path = Path(row_dict.get("file_path", ""))
    new_id = book_id

    if need_move and old_path.exists():
        try:
            file_type = determine_file_type(str(old_path))
            new_id = _make_work_id(file_type, final_author_id, final_series_id)
            old_stem = old_path.stem
            if '_' in old_stem:
                rest = old_stem.split('_', 1)[1]
                clean_path = Path(rest + old_path.suffix)
            else:
                clean_path = Path(old_path.name)
            new_target = build_import_target(clean_path, final_author_name,
                                             final_series_name, book_id=new_id)
            new_target.parent.mkdir(parents=True, exist_ok=True)
            if not new_target.exists():
                shutil.move(str(old_path), str(new_target))
                row_dict["file_path"] = str(new_target.absolute())
        except Exception:
            pass

    favorite_val = int(row_dict.get("favorite", 0))
    rating_val = float(row_dict.get("rating", 0) or 0)
    likes_val = int(row_dict.get("likes", 0) or 0)

    for k, v in field_updates.items():
        if k == "标题":
            row_dict["title"] = str(v)
        elif k == "收藏":
            favorite_val = 1 if v == "是" else 0
        elif k == "评分":
            rating_val = float(v) if v else 0
        elif k == "点赞":
            likes_val = int(v) if v else 0
        elif k == "标签":
            row_dict["tags"] = str(v)
        elif k == "简介":
            row_dict["description"] = str(v)
        elif k == "来源":
            row_dict["source"] = str(v)

    row_dict["id"] = new_id
    row_dict["author_id"] = final_author_id
    row_dict["series_id"] = final_series_id
    row_dict["favorite"] = favorite_val
    row_dict["rating"] = rating_val
    row_dict["likes"] = likes_val

    with db:
        if new_id != book_id:
            db.execute("DELETE FROM works WHERE id = ?", (book_id,))
        db.execute(
            """INSERT OR REPLACE INTO works (id, title, author_id, series_id,
               tags, source, source_status, file_ext, file_type, imported_at,
               file_size_kb, md5, file_path, favorite, rating, description, likes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id,
                row_dict.get("title", ""),
                final_author_id,
                final_series_id,
                row_dict.get("tags", ""),
                row_dict.get("source", ""),
                row_dict.get("source_status", "ok"),
                row_dict.get("file_ext", ""),
                row_dict.get("file_type", ""),
                row_dict.get("imported_at", ""),
                float(row_dict.get("file_size_kb", 0) or 0),
                row_dict.get("md5", ""),
                row_dict.get("file_path", ""),
                favorite_val,
                rating_val,
                row_dict.get("description", ""),
                likes_val,
            ),
        )

    _flush_id_registry()
    return get_by_id(new_id)


def delete_entries(ids: set[str]) -> list[dict]:
    deleted = []
    for bid in ids:
        row = get_by_id(bid)
        if row:
            deleted.append(row)
    if deleted:
        db = get_db()
        with db:
            placeholders = ",".join("?" for _ in ids)
            db.execute(f"DELETE FROM works WHERE id IN ({placeholders})", list(ids))
    return deleted


def rename_author(local_id: str, old_name: str, new_name: str) -> int:
    return _rename(local_id, new_name)
