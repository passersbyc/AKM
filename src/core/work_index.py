"""作品重索引 — ID 重新编号、文件操作和数据库清理。"""
import shutil
from collections import defaultdict
from pathlib import Path

from src.core.config import get_library_path
from src.core.database import (
    get_db, _to_base36, _get_type_char,
    next_counter, reset_counter, init_db,
)
from src.core.filetype import determine_file_type
from src.core.registry import _get_author_id, _get_series_id, work_file_prefix, _reset_id_registry
from src.core.logging import get_logger
from src.core.work_repository import read_all, write_all, delete_entries, normalize_id

_log = get_logger("akm.work_index")


def _remove_files(ids: set[str]) -> None:
    """删除指定作品的文件。若删除全部则直接清空书库目录。"""
    rows = read_all()
    all_books = len(ids) == len(rows)
    if not all_books:
        for row in rows:
            if row.get("ID") in ids:
                fp = Path(row.get("文件路径", ""))
                if fp.exists():
                    try:
                        fp.unlink()
                    except Exception:
                        _log.debug("删除文件失败", exc_info=True)
    else:
        lib = get_library_path()
        if lib.exists():
            try:
                shutil.rmtree(lib)
                lib.mkdir(parents=True, exist_ok=True)
            except Exception:
                _log.debug("清空书库失败", exc_info=True)


def _reset_tables() -> None:
    """清空 authors(除佚名)/series/pixiv_trackings/id_counters。"""
    db = get_db()
    for sql, desc in [
        ("DELETE FROM pixiv_trackings WHERE author_id != '000'", "tracking"),
        ("DELETE FROM series", "series"),
        ("DELETE FROM authors WHERE id != '000'", "authors"),
        ("DELETE FROM id_counters", "counters"),
    ]:
        try:
            db.execute(sql)
        except Exception as e:
            _log.warning("reset_tables: %s 删除失败 — %s", desc, e)
    try:
        db.commit()
    except Exception as e:
        _log.warning("reset_tables: commit 失败 — %s", e)


def _update_file_prefix(row: dict, new_id: str) -> None:
    _logger = get_logger("akm")

    old_path_str = row.get("文件路径", "") or row.get("file_path", "")
    if not old_path_str:
        return
    old_path = Path(old_path_str)

    new_prefix = work_file_prefix(new_id)
    old_name = old_path.name
    if '_' not in old_name:
        return

    old_prefix, rest = old_name.split('_', 1)
    if old_prefix == new_prefix:
        return

    new_name = f"{new_prefix}_{rest}"
    new_path = old_path.parent / new_name

    if not old_path.exists():
        row["文件路径"] = str(new_path.absolute())
        _logger.debug(f"reindex: 文件不在磁盘上，仅更新路径: {old_path} -> {new_path}")
        return

    if new_path.exists():
        _logger.warning(f"reindex: 无法重命名，目标已存在: {new_path}")
        return

    try:
        old_path.rename(new_path)
        row["文件路径"] = str(new_path.absolute())
    except OSError as e:
        _logger.warning(f"reindex: 重命名失败: {old_path} -> {new_path}: {e}")


def reindex_groups(rows: list[dict], sort_key=None) -> list[dict]:
    if not rows:
        return rows

    groups = defaultdict(list)
    for row in rows:
        file_type = row.get("分类", "") or determine_file_type(row.get("文件路径", ""))
        author = row.get("作者", "")
        series = row.get("系列", "")
        key = f"{file_type}||{author}||{series or ''}"
        groups[key].append(row)

    init_db()
    for key, group_rows in groups.items():
        group_rows.sort(key=sort_key or (lambda r: r.get("ID", "")))
        parts = key.split("||")
        file_type = parts[0] if len(parts) > 0 else ""
        author = parts[1] if len(parts) > 1 else ""
        series = parts[2] if len(parts) > 2 else ""
        type_char = _get_type_char(file_type) if file_type else "0"
        author_id = _get_author_id(author) if author else "000"
        series_id = _get_series_id(author, series)

        counter_key = f"work:{type_char}:{author_id}:{series_id}"
        reset_counter(counter_key)
        for row in group_rows:
            seq = next_counter(counter_key)
            work_id = _to_base36(seq, 4)
            row["ID"] = f"{type_char}{author_id}{series_id}{work_id}"

        # Phase 1: rename files to temp names to avoid collisions
        for row in group_rows:
            old_path_str = row.get("文件路径", "") or row.get("file_path", "")
            if not old_path_str:
                continue
            old_path = Path(old_path_str)
            if not old_path.exists():
                continue
            old_name = old_path.name
            if '_' not in old_name:
                continue
            old_prefix, rest = old_name.split('_', 1)
            new_prefix = work_file_prefix(row["ID"])
            if old_prefix == new_prefix:
                continue
            tmp_name = f".tmp_{new_prefix}_{rest}"
            tmp_path = old_path.parent / tmp_name
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            try:
                old_path.rename(tmp_path)
                row["_tmp_path"] = str(tmp_path.absolute())
            except OSError as e:
                _log.debug("reindex phase1: %s -> %s: %s", old_path, tmp_path, e)

        # Phase 2: rename from temp to final names, update paths
        for row in group_rows:
            tmp_path_str = row.pop("_tmp_path", None)
            old_path_str = row.get("文件路径", "") or row.get("file_path", "")
            new_prefix = work_file_prefix(row["ID"])

            if tmp_path_str:
                tmp_path = Path(tmp_path_str)
                _, final_name = tmp_path.name.split('_', 1)
                final_path = tmp_path.parent / final_name
                try:
                    tmp_path.rename(final_path)
                    row["文件路径"] = str(final_path.absolute())
                except OSError as e:
                    _log.warning("reindex: 重命名失败: %s -> %s: %s", tmp_path, final_path, e)
            elif old_path_str:
                old_path = Path(old_path_str)
                if '_' in old_path.name:
                    _, rest = old_path.name.split('_', 1)
                else:
                    rest = old_path.name
                new_name = f"{new_prefix}_{rest}"
                row["文件路径"] = str((old_path.parent / new_name).absolute())

    return rows


def reindex_all(sort_key=None) -> None:
    rows = read_all()
    if not rows:
        _reset_id_registry()
        return
    reindex_groups(rows, sort_key)
    write_all(rows)


def delete_and_reindex(ids: set[str], *, keep_file: bool = False,
                       clear_tables: bool = False) -> list[dict]:
    """删除作品并重排剩余。keep_file 保留文件，clear_tables 清空关联表。"""
    ids = {normalize_id(i) for i in ids}

    if not keep_file:
        _remove_files(ids)

    deleted = delete_entries(ids)
    if not deleted:
        return []

    rows = read_all()
    if not rows:
        _reset_id_registry()
        if clear_tables:
            _reset_tables()
        return deleted

    reindex_groups(rows)
    write_all(rows)
    return deleted
