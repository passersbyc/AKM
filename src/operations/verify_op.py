"""verify 操作 — 文件完整性校验入口。"""

from src.core.work_manager import WorkManager


def verify_integrity(book_id: str | None = None) -> dict:
    return WorkManager.verify_integrity(book_id)


def check_integrity(progress_callback=None) -> dict:
    """完整性检查：遍历作品检查文件/MD5，失败的入队或删除，清理孤立文件。

    progress_callback(event, **kwargs):
      - "start": total=N（开始时）
      - "progress": work_id, status, msg（每个作品处理完）
    返回 {ok, queued, deleted, cleaned, total}。
    """
    from pathlib import Path
    from src.core.hashing import generate_file_md5
    from src.core.download import append_or_update, mark_not_in_db, get_by_url
    from src.core.database import get_db
    from src.core.config import get_library_path

    rows = WorkManager.read()
    if progress_callback:
        progress_callback("start", total=len(rows))
    if not rows:
        return {"ok": 0, "queued": 0, "deleted": 0, "cleaned": 0, "total": 0}

    lib_path = get_library_path()
    db = get_db()
    ok_count = queued_count = deleted_count = 0
    existing_paths: set[str] = set()

    for row in rows:
        work_id = row.get("ID", "")
        file_path_str = row.get("文件路径", "")
        source_url = row.get("来源", "").strip()
        md5_db = row.get("MD5", "").strip()
        file_path = Path(file_path_str) if file_path_str else None

        if file_path and file_path_str:
            existing_paths.add(file_path_str)

        status = ""
        msg = ""

        if file_path and file_path.exists():
            if md5_db:
                try:
                    current_md5 = generate_file_md5(file_path)
                except Exception:
                    current_md5 = ""
                if current_md5 and current_md5 == md5_db:
                    ok_count += 1
                    if progress_callback:
                        progress_callback("progress", work_id=work_id, status="ok", msg="")
                    continue
            else:
                ok_count += 1
                if progress_callback:
                    progress_callback("progress", work_id=work_id, status="ok", msg="")
                continue

        queue_entry = get_by_url(source_url) if source_url else None
        if source_url and "pixiv" in source_url.lower():
            if queue_entry:
                if queue_entry.get("is_valid", 1):
                    mark_not_in_db(source_url)
                    queued_count += 1
                    status = "queued"
                    msg = f"⚡ 入队: {work_id} → {source_url}"
                else:
                    deleted_count += 1
                    status = "deleted"
                    msg = f"🗑 删除: {work_id} (来源已无效)"
            else:
                append_or_update([{"url": source_url, "is_in_db": 0}])
                queued_count += 1
                status = "queued"
                msg = f"⚡ 入队: {work_id} → {source_url}"
            with db:
                db.execute("DELETE FROM works WHERE id = ?", (work_id,))
        else:
            with db:
                db.execute("DELETE FROM works WHERE id = ?", (work_id,))
            deleted_count += 1
            status = "deleted"
            msg = f"🗑 删除: {work_id} (文件缺失且无来源)"

        if progress_callback:
            progress_callback("progress", work_id=work_id, status=status, msg=msg)

    cleaned_count = 0
    if lib_path.exists():
        for f in lib_path.rglob("*"):
            if f.is_file() and str(f.absolute()) not in existing_paths:
                try:
                    f.unlink()
                    cleaned_count += 1
                except Exception:
                    pass
        for d in sorted(lib_path.rglob("*"), key=lambda x: -len(str(x))):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except Exception:
                    pass

    return {"ok": ok_count, "queued": queued_count, "deleted": deleted_count,
            "cleaned": cleaned_count, "total": len(rows)}
