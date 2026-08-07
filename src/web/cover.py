"""封面提取 — EPUB/PDF 封面图提取并缩放为 JPEG，带 LRU 内存缓存。"""
from __future__ import annotations

import io
import zipfile
from collections import OrderedDict
from pathlib import Path

from src.core.logging import logger

# 内存缓存：{file_path: (mtime, cover_bytes)}，LRU 淘汰防止无限增长
_MAX_CACHE_ENTRIES = 500
_cover_cache: "OrderedDict[str, tuple[float, bytes | None]]" = OrderedDict()

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _cached(file_path: str, extractor) -> bytes | None:
    """带 LRU 缓存的封面提取（按文件路径 + mtime 失效）。"""
    path = Path(file_path)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cache_key = str(path)
    if cache_key in _cover_cache:
        cached_mtime, cached_data = _cover_cache[cache_key]
        if cached_mtime == mtime:
            _cover_cache.move_to_end(cache_key)
            return cached_data
    cover_bytes = extractor(path)
    _cover_cache[cache_key] = (mtime, cover_bytes)
    _cover_cache.move_to_end(cache_key)
    while len(_cover_cache) > _MAX_CACHE_ENTRIES:
        _cover_cache.popitem(last=False)
    return cover_bytes


def extract_cover(file_path: str, max_width: int = 300) -> bytes | None:
    """按文件类型提取封面（epub/pdf），返回 JPEG bytes。"""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".epub":
        return extract_epub_cover(file_path, max_width)
    if suffix == ".pdf":
        return extract_pdf_cover(file_path, max_width)
    return None


def extract_epub_cover(file_path: str, max_width: int = 300) -> bytes | None:
    """从 EPUB 文件提取封面图，返回 JPEG bytes。

    查找策略（按优先级）：
    1. OPF manifest 中 <meta name="cover"> 指向的图片
    2. 文件名含 "cover" 的图片
    3. 第一张图片
    """
    if Path(file_path).suffix.lower() != ".epub":
        return None
    return _cached(file_path, lambda p: _extract_cover(p, max_width))


def extract_pdf_cover(file_path: str, max_width: int = 300) -> bytes | None:
    """从 PDF 第一页提取封面图（优先内嵌图片），返回 JPEG bytes。"""
    if Path(file_path).suffix.lower() != ".pdf":
        return None
    return _cached(file_path, lambda p: _extract_pdf_cover(p, max_width))


def _extract_pdf_cover(path: Path, max_width: int) -> bytes | None:
    """从 PDF 第一页提取封面：优先第一页内嵌图片，统一转 JPEG。"""
    try:
        from pypdf import PdfReader
        from PIL import Image

        reader = PdfReader(str(path))
        if not reader.pages:
            return None
        page = reader.pages[0]
        for image_file in page.images:
            raw = image_file.data
            try:
                img = Image.open(io.BytesIO(raw))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                if img.width > max_width:
                    ratio = max_width / img.width
                    img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=82)
                return buf.getvalue()
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"PDF 封面提取失败 {path.name}: {e}")
    return None


def _extract_cover(path: Path, max_width: int) -> bytes | None:
    """实际提取逻辑。"""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            # 策略 1：OPF manifest cover
            cover_name = _find_cover_from_opf(zf)
            if cover_name:
                return _read_and_resize(zf, cover_name, max_width)

            # 策略 2：文件名含 "cover"
            for name in zf.namelist():
                lower = name.lower()
                if "cover" in lower and Path(lower).suffix in _IMAGE_EXTS:
                    return _read_and_resize(zf, name, max_width)

            # 策略 3：第一张图片
            for name in zf.namelist():
                if Path(name.lower()).suffix in _IMAGE_EXTS:
                    return _read_and_resize(zf, name, max_width)

    except Exception as e:
        logger.warning(f"EPUB 封面提取失败 {path.name}: {e}")
    return None


def _find_cover_from_opf(zf: zipfile.ZipFile) -> str | None:
    """从 OPF 文件中解析封面图片路径。"""
    import re

    for name in zf.namelist():
        if not name.endswith(".opf"):
            continue
        try:
            opf = zf.read(name).decode("utf-8", errors="ignore")
        except Exception:
            continue

        # <meta name="cover" content="cover-id"/>
        m = re.search(r'<meta\s+name="cover"\s+content="([^"]+)"', opf)
        if not m:
            continue
        cover_id = m.group(1)

        # <item id="cover-id" href="images/cover.jpg" .../>
        m2 = re.search(
            rf'<item\s+[^>]*id="{re.escape(cover_id)}"[^>]*href="([^"]+)"', opf)
        if not m2:
            continue
        href = m2.group(1)

        # OPF 文件所在目录 + href
        opf_dir = str(Path(name).parent)
        if opf_dir == ".":
            return href
        return f"{opf_dir}/{href}"

    return None


def _read_and_resize(zf: zipfile.ZipFile, name: str,
                     max_width: int) -> bytes | None:
    """读取图片并用 Pillow 缩放到 max_width，返回 JPEG bytes。"""
    try:
        from PIL import Image

        raw = zf.read(name)
        img = Image.open(io.BytesIO(raw))

        # 转 RGB（PNG 可能带 alpha）
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # 缩放
        if img.width > max_width:
            ratio = max_width / img.width
            new_h = int(img.height * ratio)
            img = img.resize((max_width, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return buf.getvalue()
    except Exception:
        return None
