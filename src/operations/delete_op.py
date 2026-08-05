"""delete 操作 — 编排层：过滤 + 删除。数据操作委托 WorkManager。"""
from src.core.work_manager import WorkManager
from src.core.author_manager import delete_by_id as _delete_author_by_id
from src.core.series_manager import delete as _delete_series_by_name

def delete_book(ids: set[str], *, keep_file: bool = False,
                clear_tables: bool = False) -> dict:
    deleted = WorkManager.delete_and_reindex(
        ids, keep_file=keep_file, clear_tables=clear_tables)
    return {"deleted": len(deleted), "ids": [d.get("ID") for d in deleted]}


def filter_rows(
    author: str = "",
    series: str = "",
    book_type: str = "",
    tag: str = "",
    favorite: bool = False,
    no_favorite: bool = False,
) -> list[dict]:
    favorited = ""
    if favorite:
        favorited = "yes"
    elif no_favorite:
        favorited = "no"
    return WorkManager.search(
        author=author, series=series,
        file_type=book_type, tags=tag,
        favorited=favorited,
    )


def delete_by_ids(target_ids: list[str], by_name: bool = False,
                  keep_file: bool = False) -> dict:
    rows = WorkManager.read()
    if by_name:
        matched = []
        for t in target_ids:
            kl = t.lower()
            matched.extend([r for r in rows if kl in (r.get("标题", "") or "").lower()])
    else:
        expanded = set()
        for t in target_ids:
            for r in _parse_range(t):
                expanded.add(WorkManager.normalize_id(r))
        matched = [r for r in rows if r.get("ID") in expanded]
    ids = {r.get("ID") for r in matched}
    return delete_book(ids, keep_file=keep_file)


def _parse_range(range_str: str) -> list[str]:
    from src.core.registry import to_full_id
    if "," in range_str:
        result = []
        for part in range_str.split(","):
            result.extend(_parse_range(part.strip()))
        return result
    if "-" in range_str and not range_str.startswith("-"):
        parts = range_str.split("-", 1)
        start = to_full_id(parts[0].strip())
        end = to_full_id(parts[1].strip())
        if len(start) == len(end) and len(start) >= 7:
            try:
                t = start[0]
                a = start[1:4]
                s1, w1 = start[4:6], int(start[6:], 36)
                s2, w2 = end[4:6], int(end[6:], 36)
                import string
                b36 = string.digits + string.ascii_lowercase

                def _enc_series(s: int) -> str:
                    # 2 位 base36（00~zz），s 可达 1295，不能直接用 b36[s]
                    return b36[s // 36] + b36[s % 36]

                result = []
                for s in range(int(s1, 36), int(s2, 36) + 1):
                    ws = w1 if s == int(s1, 36) else 0
                    we = w2 if s == int(s2, 36) else len(b36) ** 4 - 1
                    for w in range(ws, we + 1):
                        val = w
                        wid = ""
                        for _ in range(4):
                            wid = b36[val % 36] + wid
                            val //= 36
                        result.append(f"{t}{a}{_enc_series(s)}{wid}")
                return result
            except (ValueError, IndexError):
                pass
    return [to_full_id(range_str)]


def resolve_author_targets(targets: list[str]) -> list[dict]:
    """将用户输入（ID/name/UID）解析为作者 dict 列表。"""
    from src.core.author_manager import resolve
    matched = []
    for t in targets:
        a = resolve(t)
        if a:
            matched.append(a)
    return matched


def delete_authors(author_ids: list[str]) -> tuple[int, list[str]]:
    deleted = 0
    ids = []
    for lid in author_ids:
        if _delete_author_by_id(lid):
            deleted += 1
            ids.append(lid)
    return deleted, ids


def delete_series(series_targets: list[str], author: str = "",
                  force: bool = False) -> tuple[int, int]:
    deleted = 0
    unlinked = 0
    for name in series_targets:
        count, was_force = _delete_series_by_name(name, author, force=force)
        if count:
            deleted += 1
            if was_force:
                unlinked += 1
    return deleted, unlinked


def delete_all_works(keep_file: bool = False, clear_tables: bool = True) -> dict:
    """清空所有作品，返回 {deleted, ids}。

    "清空整个库"语义：同步清空下载队列。
    否则 delete_entries 的单作品联动逻辑会把全部队列记录重置为待下载，
    pull 会把刚删掉的作品全部重新下载回来（delete all 形同虚设）。
    """
    from src.core.database import get_db
    db = get_db()
    with db:
        db.execute("DELETE FROM download_queue")
    rows = db.execute("SELECT id FROM works").fetchall()
    ids = {r["id"] for r in rows}
    return delete_book(ids, keep_file=keep_file, clear_tables=clear_tables)
