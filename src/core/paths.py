import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from src.core.config import get_project_root, load_config
from src.core.logging import get_logger
from src.core.registry import author_folder_name, series_folder_name, work_file_prefix
from src.core.filetype import determine_file_type
from src.domain.cdbook import normalize_series_name
from src.core.utils import strip_tag_prefix


def get_library_path() -> Path:
    root = get_project_root()
    cfg = load_config()
    path_str = cfg.get("project_settings", {}).get("library_path")
    if path_str:
        p = Path(path_str)
        return p if p.is_absolute() else (root / p).absolute()
    default_path = root / "library"
    default_path.mkdir(exist_ok=True)
    return default_path


def build_import_target(file: Path, author: str = "", series: str = "", book_id: str = "") -> Path:
    file_type = determine_file_type(str(file))
    if file_type == "unknown":
        raise ValueError(f"无法识别文件类型: {file}")
    base = get_library_path() / file_type
    a = author.strip() if author else ""
    s = series.strip() if series else ""
    if a and s:
        base = base / author_folder_name(a) / series_folder_name(a, normalize_series_name(s))
    elif a and not s:
        base = base / author_folder_name(a)
    elif not a and s:
        base = base / "unsort"
    base.mkdir(parents=True, exist_ok=True)

    clean_name = strip_tag_prefix(file.name)
    clean_name = re.sub(r'\s*\(\d+\)(\.[^.]+)$', r'\1', clean_name)

    if book_id:
        clean_name = f"{work_file_prefix(book_id)}_{clean_name}"
    return base / clean_name


def determine_storage_path(base_path: Path, author: str = "", series: str = "") -> Path:
    a = author.strip() if author else ""
    s = series.strip() if series else ""
    target = base_path
    if a and s:
        target = target / author_folder_name(a) / series_folder_name(a, normalize_series_name(s))
    elif a and not s:
        target = target / author_folder_name(a)
    elif not a and s:
        target = target / "unsort"
    target.mkdir(parents=True, exist_ok=True)
    return target


def delete_downloads_file(downloads_path: str = None) -> None:
    if downloads_path is None:
        root = get_project_root()
        cfg = load_config()
        downloads_path = cfg.get("download_file_path", "downloads")
    dp = Path(downloads_path)
    if not dp.is_absolute():
        dp = get_project_root() / dp
    if dp.exists():
        try:
            shutil.rmtree(dp, ignore_errors=True)
        except Exception:
            pass

def extract_pdf_cover(file_path: Path, output_path: Path = None) -> Optional[bytes]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        if len(reader.pages) == 0:
            return None
        page = reader.pages[0]
        for image_file in page.images:
            img_data = image_file.data
            if output_path:
                output_path.write_bytes(img_data)
            return img_data
    except Exception:
        get_logger("akm.paths").debug("PDF 封面提取方式1失败，尝试方式2", exc_info=True)

    try:
        from PIL import Image
        from pypdf import PdfReader
        reader = PdfReader(str(file_path))
        page = reader.pages[0]
        if '/XObject' in page['/Resources']:
            xObject = page['/Resources']['/XObject'].get_object()
            for obj in xObject:
                if xObject[obj]['/Subtype'] == '/Image':
                    data = xObject[obj]._data
                    try:
                        img = Image.open(io.BytesIO(data))
                        buf = io.BytesIO()
                        img.save(buf, format='PNG')
                        result = buf.getvalue()
                        if output_path:
                            output_path.write_bytes(result)
                        return result
                    except Exception:
                        continue
    except Exception:
        pass
    return None


def extract_epub_cover(file_path: Path, output_path: Path = None) -> Optional[bytes]:
    try:
        import ebooklib
        from ebooklib import epub
        book = epub.read_epub(str(file_path))
        cover_id = None
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content = item.get_content().decode('utf-8', errors='ignore')
            for img_id in re.findall(r'<img[^>]+src="([^"]+)"', content):
                cover_id = img_id.split('/')[-1] if '/' in img_id else img_id
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            item_id = item.get_id()
            file_name = item.get_name()
            if (cover_id and (item_id == cover_id or file_name == cover_id)) or 'cover' in file_name.lower():
                data = item.get_content()
                if output_path:
                    output_path.write_bytes(data)
                return data
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            data = item.get_content()
            if output_path:
                output_path.write_bytes(data)
            return data
    except Exception:
        pass

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            for name in zf.namelist():
                lower = name.lower()
                if 'cover' in lower and any(lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    data = zf.read(name)
                    if output_path:
                        output_path.write_bytes(data)
                    return data
    except Exception:
        pass
    return None
