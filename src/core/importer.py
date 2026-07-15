import re
import time
import shutil
import tempfile
from pathlib import Path

from src.core.registry import generate_id, _flush_id_registry
from src.core.logging import logger
from src.core.utils import strip_tag_prefix
from src.core.hashing import generate_file_md5, check_duplicate_by_md5
from src.core.filetype import determine_file_type
from src.core.paths import build_import_target
from src.core.work_repository import append_one
from src.domain.cdbook import normalize_series_name
from src.core.converter import (
    convert_to_txt, convert_to_epub,
    is_traditional_chinese, convert_to_simplified, convert_file_to_simplified,
)


class ImportResult:
    def __init__(self, success: bool, file_name: str = "", book_id: str = "",
                 file_type: str = "", file_size_kb: float = 0, storage_path: str = "",
                 md5: str = "", error: str = "", duplicate_of: str = ""):
        self.success = success
        self.file_name = file_name
        self.book_id = book_id
        self.file_type = file_type
        self.file_size_kb = file_size_kb
        self.storage_path = storage_path
        self.md5 = md5
        self.error = error
        self.duplicate_of = duplicate_of


def import_one(file_path: str, author: str = "", series: str = "",
               tags: str = "", source: str = "", favorited: bool = False,
               rating: float = 0.0, description: str = "",
               like_count: int = 0, create_date: str = "",
               source_status: str = "ok",
               convert_doc: bool = True, convert_traditional: bool = False,
               title: str = "",
               user_id: str = "",
               target_format: str = "epub") -> ImportResult:
    fp = Path(file_path)
    original_fp = fp
    temp_files_to_clean = []

    if not fp.exists():
        return ImportResult(success=False, error=f"文件不存在: {file_path}")
    if not fp.is_file():
        return ImportResult(success=False, error=f"不是文件: {file_path}")

    original_title = strip_tag_prefix(Path(file_path).stem)

    if convert_doc and fp.suffix.lower() in ('.doc', '.docx'):
        try:
            doc_title = title or original_title
            if target_format == "epub":
                tmp_dir = tempfile.mkdtemp()
                tmp_epub = Path(tmp_dir) / (fp.stem + ".epub")
                fp = convert_to_epub(fp, output_path=tmp_epub, title=doc_title, author=author)
                temp_files_to_clean.append(fp)
            else:
                text = convert_to_txt(fp)
                with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8') as tf:
                    tf.write(text)
                    fp = Path(tf.name)
                    temp_files_to_clean.append(fp)
        except Exception as e:
            for tf in temp_files_to_clean:
                try: tf.unlink()
                except: pass
            return ImportResult(success=False, error=f"文档转换失败: {e}", file_name=original_fp.name)

    try:
        source_md5 = generate_file_md5(original_fp)
        is_dup, dup_name = check_duplicate_by_md5(source_md5)
        if is_dup:
            for tf in temp_files_to_clean:
                try: tf.unlink()
                except: pass
            return ImportResult(success=False, error=f"MD5重复", file_name=original_fp.name, duplicate_of=dup_name)

        file_type = determine_file_type(str(fp))
        if file_type == "unknown":
            for tf in temp_files_to_clean:
                try: tf.unlink()
                except: pass
            return ImportResult(success=False, error=f"无法识别的文件类型: {fp.suffix}")

        book_id = generate_id(file_type, author, series)
        target = build_import_target(fp, author, series, book_id=book_id)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            for tf in temp_files_to_clean:
                try: tf.unlink()
                except: pass
            return ImportResult(success=False, error=f"目标已存在", file_name=original_fp.name)

        shutil.copy2(fp, target)
        file_size_kb = round(target.stat().st_size / 1024, 2)

        final_title = title or original_title
        final_author = author or "佚名"
        final_series = normalize_series_name(series or "")
        final_description = description

        if convert_traditional:
            if is_traditional_chinese(final_title):
                logger.info(f"检测到繁体标题: {final_title}，将转换为简体")
                convert_file_to_simplified(target)
                final_title = convert_to_simplified(final_title)
                simplified_name = convert_to_simplified(target.name)
                if simplified_name != target.name:
                    new_target = target.parent / simplified_name
                    target.rename(new_target)
                    target = new_target

            if is_traditional_chinese(final_author):
                final_author = convert_to_simplified(final_author)
            if is_traditional_chinese(final_series):
                final_series = convert_to_simplified(final_series)
            if is_traditional_chinese(final_description):
                final_description = convert_to_simplified(final_description)
            if is_traditional_chinese(tags):
                tags = convert_to_simplified(tags)

        final_create_date = create_date
        if create_date and "T" in create_date:
            normalized = create_date.split("+")[0].split("Z")[0].replace("T", " ")
            if len(normalized) >= 10:
                final_create_date = normalized

        entry = {
            "ID": book_id,
            "标题": final_title,
            "作者": final_author,
            "系列": final_series,
            "标签": tags,
            "来源": source or "local",
            "源状态": source_status,
            "后缀": target.suffix.lower(),
            "分类": file_type,
            "导入时间": final_create_date or time.strftime("%Y-%m-%d %H:%M:%S"),
            "文件大小(KB)": str(file_size_kb),
            "MD5": source_md5,
            "文件路径": str(target.absolute()),
            "收藏": "是" if favorited else "否",
            "评分": str(rating) if 0.0 < rating <= 10.0 else "",
            "简介": final_description,
            "点赞": str(like_count),
        }
        append_one(entry)

        if final_author:
            try:
                from src.core.author_manager import register
                register(name=final_author, uid=user_id or "", homepage="")
            except Exception:
                pass

        for tf in temp_files_to_clean:
            try: tf.unlink()
            except: pass
        return ImportResult(
            success=True, file_name=target.name, book_id=book_id,
            file_type=file_type, file_size_kb=file_size_kb,
            storage_path=str(target.absolute()), md5=source_md5
        )
    except Exception as e:
        for tf in temp_files_to_clean:
            try: tf.unlink()
            except: pass
        return ImportResult(success=False, error=str(e), file_name=original_fp.name)


def import_batch(files: list[str], author: str = "", series: str = "",
                 tags: str = "", source: str = "", favorited: bool = False,
                 rating: float = 0.0, description: str = "",
                 source_status: str = "ok",
                 convert_doc: bool = True, convert_traditional: bool = False,
                 title: str = "",
                 user_id: str = "",
                 target_format: str = "epub") -> list[ImportResult]:
    results = []
    for f in files:
        try:
            results.append(import_one(f, author, series, tags, source, favorited,
                                      rating, description, source_status=source_status,
                                      convert_doc=convert_doc,
                                      convert_traditional=convert_traditional,
                                      title=title, user_id=user_id,
                                      target_format=target_format))
        except Exception as e:
            results.append(ImportResult(success=False, error=str(e)))

    _flush_id_registry()

    return results
