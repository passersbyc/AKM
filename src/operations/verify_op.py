"""verify 操作 — 文件完整性校验入口。"""

from pathlib import Path

from src.core.work_manager import WorkManager

# 常见扩展名的文件头 magic（魔数）
_MAGIC = {
    ".epub": (b"PK\x03\x04", "EPUB/ZIP"),
    ".zip": (b"PK\x03\x04", "ZIP"),
    ".docx": (b"PK\x03\x04", "DOCX/ZIP"),
    ".pdf": (b"%PDF", "PDF"),
    ".gif": (b"GIF8", "GIF"),
    ".jpg": (b"\xff\xd8\xff", "JPEG"),
    ".jpeg": (b"\xff\xd8\xff", "JPEG"),
    ".png": (b"\x89PNG", "PNG"),
    ".doc": (b"\xd0\xcf\x11\xe0", "DOC/OLE"),
    ".flac": (b"fLaC", "FLAC"),
    ".wav": (b"RIFF", "WAV"),
    ".avi": (b"RIFF", "AVI"),
    ".mkv": (b"\x1a\x45\xdf\xa3", "MKV"),
}


def _check_structure(file_path: Path) -> tuple[bool, str]:
    """文件结构/可读性检查：非零大小 + 文件头 magic + 压缩包/PDF 深度解析。

    返回 (是否完好, 失败原因)。
    """
    try:
        size = file_path.stat().st_size
        if size == 0:
            return False, "空文件"

        suffix = file_path.suffix.lower()
        magic, label = _MAGIC.get(suffix, (b"", ""))
        if magic:
            with open(file_path, "rb") as f:
                head = f.read(len(magic))
            if not head.startswith(magic):
                return False, f"文件头不匹配（{label}）"

        if suffix in (".epub", ".zip", ".docx"):
            import zipfile
            try:
                with zipfile.ZipFile(file_path) as zf:
                    if not zf.namelist():
                        return False, "压缩包为空"
            except zipfile.BadZipFile:
                return False, "压缩包损坏（BadZipFile）"
            except Exception as e:
                return False, f"压缩包解析失败（{type(e).__name__}）"
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                if len(reader.pages) == 0:
                    return False, "PDF 无页面"
            except Exception:
                return False, "PDF 解析失败"

        return True, ""
    except OSError:
        return False, "文件不可读"
    except Exception as e:
        return False, f"结构检查异常（{type(e).__name__}）"


def verify_integrity(book_id: str | None = None) -> dict:
    return WorkManager.verify_integrity(book_id)


def check_integrity(progress_callback=None) -> dict:
    """完整性检查：存在性 → MD5 → 文件结构/可读性，失败的入队或删除，清理孤立文件。

    progress_callback(event, **kwargs):
      - "start": total=N（开始时）
      - "progress": work_id, status, msg（每个作品处理完）
    返回 {ok, corrupt, queued, deleted, cleaned, total}。
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
        return {"ok": 0, "corrupt": 0, "queued": 0, "deleted": 0, "cleaned": 0, "total": 0}

    lib_path = get_library_path()
    db = get_db()
    ok_count = corrupt_count = queued_count = deleted_count = 0
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
            # 第 1 层：MD5 字节校验（无 MD5 记录则跳过字节校验）
            md5_ok = True
            if md5_db:
                try:
                    current_md5 = generate_file_md5(file_path)
                except Exception:
                    current_md5 = ""
                md5_ok = bool(current_md5) and current_md5 == md5_db

            if md5_ok:
                # 第 2 层：文件结构/可读性检查（文件头 magic + 压缩包/PDF 解析）
                struct_ok, why = _check_structure(file_path)
                if struct_ok:
                    ok_count += 1
                    if progress_callback:
                        progress_callback("progress", work_id=work_id, status="ok", msg="")
                    continue
                corrupt_count += 1
                status = "corrupt"
                msg = f"(｡•́︿•̀｡) 损坏: {work_id} ({why})"
            else:
                corrupt_count += 1
                status = "corrupt"
                msg = f"(｡•́︿•̀｡) 损坏: {work_id} (MD5 不匹配)"
        else:
            corrupt_count += 1
            status = "corrupt"
            msg = f"(｡•́︿•̀｡) 损坏: {work_id} (文件缺失)"

        queue_entry = get_by_url(source_url) if source_url else None
        if source_url and "pixiv" in source_url.lower():
            # 文件损坏/丢失：先删残留文件再重新入队。
            # 否则重下时 target 仍存在，_pipeline_move_file 报"目标已存在"，
            # 连续失败 3 次会被拉黑，作品永远无法修复。
            if file_path and file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass
            if queue_entry:
                if queue_entry.get("is_valid", 1):
                    mark_not_in_db(source_url)
                    queued_count += 1
                    status = "queued"
                    msg = f"(◕‿◕) 入队: {work_id} → {source_url}"
                else:
                    deleted_count += 1
                    status = "deleted"
                    msg = f"(｡•́︿•̀｡) 删除: {work_id} (来源已无效)"
            else:
                append_or_update([{"url": source_url, "is_in_db": 0}])
                queued_count += 1
                status = "queued"
                msg = f"(◕‿◕) 入队: {work_id} → {source_url}"
            with db:
                db.execute("DELETE FROM works WHERE id = ?", (work_id,))
        else:
            with db:
                db.execute("DELETE FROM works WHERE id = ?", (work_id,))
            deleted_count += 1
            status = "deleted"
            msg = f"(｡•́︿•̀｡) 删除: {work_id} (文件缺失且无来源)"
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

    # 兜底：扫描 download_queue 中 is_in_db=1 但 works 表无记录的 stale 行
    stale_reset = 0
    with db:
        result = db.execute(
            "UPDATE download_queue SET is_in_db=0, is_valid=1, fail_count=0 "
            "WHERE is_in_db=1 "
            "AND NOT EXISTS (SELECT 1 FROM works w WHERE w.source = download_queue.url)"
        )
        stale_reset = result.rowcount

    return {"ok": ok_count, "corrupt": corrupt_count, "queued": queued_count,
            "deleted": deleted_count, "cleaned": cleaned_count,
            "stale_reset": stale_reset, "total": len(rows)}
