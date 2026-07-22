"""EPUB 封面提取 — 从 EPUB (ZIP) 中查找并缩放封面图。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from src.core.logging import logger

# 内存缓存：{file_path: (mtime, cover_bytes)}
_cover_cache: dict[str, tuple[float, bytes | None]] = {}

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def extract_epub_cover(file_path: str, max_width: int = 300) -> bytes | None:
    """从 EPUB 文件提取封面图，返回 JPEG bytes。

    查找策略（按优先级）：
    1. OPF manifest 中 <meta name="cover"> 指向的图片
    2. 文件名含 "cover" 的图片
    3. 第一张图片

    结果缓存（按文件路径 + mtime）。
    """
    path = Path(file_path)
    if not path.exists() or path.suffix.lower() != ".epub":
        return None

    # 缓存检查
    mtime = path.stat().st_mtime
    cache_key = str(path)
    if cache_key in _cover_cache:
        cached_mtime, cached_data = _cover_cache[cache_key]
        if cached_mtime == mtime:
            return cached_data

    cover_bytes = _extract_cover(path, max_width)
    _cover_cache[cache_key] = (mtime, cover_bytes)
    return cover_bytes


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
