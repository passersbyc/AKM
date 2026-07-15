"""EPUB 构建与后处理模块。"""

import hashlib
import random
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from src.core.logging import logger
from src.core.docx_converter import convert_to_txt


_CDBOOK_AD_PATTERNS: list[str] = []


def _init_cdbook_patterns() -> None:
    global _CDBOOK_AD_PATTERNS
    if _CDBOOK_AD_PATTERNS:
        return

    def _fuzzy_word(s: str) -> str:
        return r"[^\u4e00-\u9fff]*?".join(s)

    _AD_GROUPS = [
        ["一次购买", "终身免费更新", "缺失章节", "唯一联系方式"],
        ["更多", "更全", "小说", "漫画", "视频", "账号"],
        ["一次购买", "永久更新", "请联系唯一"],
        ["最新", "最全", "无广告", "完整版", "请联系"],
        ["完整版", "请联系"],
        ["缺章", "断章", "更多", "同类", "请联系"],
        ["一手", "资源", "第一时间", "更新", "请联系"],
        ["专业", "各类", "一手", "小说", "请联系"],
        ["想要", "去广告版", "想要", "最新", "最全", "文章", "请联系"],
    ]
    for group in _AD_GROUPS:
        fuzzy = [_fuzzy_word(w) for w in group]
        pattern = r"\[?\s*" + r".*?".join(fuzzy) + r".*?(?:以及备用|QQ\d+)?"
        _CDBOOK_AD_PATTERNS.append(pattern)
    _CDBOOK_AD_PATTERNS.append(r"\[[^\]]*QQ\d+[^\]]*请联系[^\]]*\]")
    _CDBOOK_AD_PATTERNS.append(
        r"请记住" + _fuzzy_word("唯一联系方式") + r".*?QQ\d+.*?" + _fuzzy_word("以及备用")
    )
    _CDBOOK_AD_PATTERNS.append(
        _fuzzy_word("24小时在线客服QQ") + r"[^\u4e00-\u9fff]*\d[^\u4e00-\u9fff]*" + _fuzzy_word("以及备用")
    )
    _CDBOOK_AD_PATTERNS.append(
        r"[^\u4e00-\u9fff]*" + _fuzzy_word("小时在线客服QQ") + r"[^\u4e00-\u9fff]*\d" +
        r"[^\u4e00-\u9fff]*" + _fuzzy_word("以及备用")
    )
    _CDBOOK_AD_PATTERNS.append(
        r"请记住" + _fuzzy_word("唯一联系方式") + r".*?QQ[^\u4e00-\u9fff]*\d+" +
        r"[^\u4e00-\u9fff]*" + _fuzzy_word("以及备用")
    )


_CJK_PUNCT = set("。！？，、；：""（）【】《》…—·～")


def _strip_trailing_junk(text: str) -> str:
    last_good = -1
    for i in range(len(text) - 1, -1, -1):
        c = text[i]
        cp = ord(c)
        if (0x4e00 <= cp <= 0x9fff) or (0x3400 <= cp <= 0x4dbf) or c in _CJK_PUNCT:
            last_good = i
            break
    if last_good < 0:
        return text
    return text[:last_good + 1]


def _strip_leading_junk(text: str) -> str:
    first_cn = -1
    for i, ch in enumerate(text):
        cp = ord(ch)
        if (0x4e00 <= cp <= 0x9fff) or (0x3400 <= cp <= 0x4dbf):
            first_cn = i
            break
    if first_cn <= 0:
        return text
    return text[first_cn:]


def _re_fuzzy(s: str) -> str:
    return r"[^\u4e00-\u9fff]*?".join(s)


def _clean_html_text(content: str) -> str:
    from bs4 import BeautifulSoup, NavigableString
    from bs4.element import Tag

    _init_cdbook_patterns()

    soup = BeautifulSoup(content, "html.parser")

    _SKIP_PARENTS = {"style", "script", "a", "img", "link", "meta", "pre", "code"}

    for text_node in list(soup.find_all(string=True)):
        if not text_node.strip():
            continue
        parent = text_node.parent
        if parent and isinstance(parent, Tag):
            if parent.name in _SKIP_PARENTS:
                continue

            skip = False
            for ancestor in parent.parents:
                if ancestor and isinstance(ancestor, Tag) and ancestor.name in _SKIP_PARENTS:
                    skip = True
                    break
            if skip:
                continue

        text = text_node.string
        if text is None:
            continue

        text = _strip_trailing_junk(text)
        text = _strip_leading_junk(text)

        for pattern in _CDBOOK_AD_PATTERNS:
            text = re.sub(pattern, "", text)
        text = re.sub(r"等，\s*" + _re_fuzzy("请记住唯一联系方式") + r".*", "", text)
        text = re.sub(_re_fuzzy("请记住唯一联系方式") + r".*", "", text)
        text = re.sub(
            r"[^\u4e00-\u9fff]*" + _re_fuzzy("小时在线客服QQ") + r"[^\u4e00-\u9fff]*", "", text
        )

        if not re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text):
            text_node.replace_with("")
        else:
            text_node.replace_with(text)

    return str(soup)


def _add_cover_to_epub(epub_path: Path, cover_dir: Path = None) -> bool:
    """Add a random cover image to EPUB if none exists. Returns True if modified."""
    if cover_dir is None:
        cover_dir = Path(__file__).resolve().parents[2] / "cover"
    if not cover_dir.is_dir():
        return False

    img_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    cover_files = [p for p in cover_dir.iterdir() if p.suffix.lower() in img_exts]
    if not cover_files:
        return False

    cover_src = random.choice(cover_files)
    cover_suffix = cover_src.suffix.lower()
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.gif': 'image/gif', '.bmp': 'image/bmp', '.webp': 'image/webp'}

    try:
        cover_data = cover_src.read_bytes()
    except Exception:
        return False

    cover_name = f"cover{cover_suffix}"
    cover_media_path = f"EPUB/media/{cover_name}"
    cover_id = "cover-img"
    cover_item_xml = f'    <item id="{cover_id}" href="media/{cover_name}" media-type="{mime_map.get(cover_suffix, "image/jpeg")}" properties="cover-image" />\n'
    cover_meta_xml = f'    <meta name="cover" content="{cover_id}" />\n'

    temp_path = epub_path.with_suffix(".epub.cover")
    modified = False

    try:
        with zipfile.ZipFile(epub_path, 'r') as zr:
            file_list = zr.namelist()
            compress_info = {}
            file_data = {}

            for name in file_list:
                info = zr.getinfo(name)
                compress_info[name] = info.compress_type
                data = zr.read(name)
                if name.endswith('.opf'):
                    content = data.decode('utf-8')
                    if 'name="cover"' not in content and 'properties="cover-image"' not in content:
                        content = content.replace('  </manifest>', f'{cover_item_xml}  </manifest>')
                        content = content.replace('  </metadata>', f'{cover_meta_xml}  </metadata>')
                        file_data[name] = content.encode('utf-8')
                        modified = True
                    else:
                        file_data[name] = data
                else:
                    file_data[name] = data

            if not modified:
                try:
                    temp_path.unlink()
                except Exception:
                    pass
                return False

            file_data[cover_media_path] = cover_data

            with zipfile.ZipFile(temp_path, 'w') as zw:
                if 'mimetype' in file_data:
                    zw.writestr('mimetype', file_data['mimetype'], compress_type=zipfile.ZIP_STORED)
                for name in file_list:
                    if name != 'mimetype':
                        ct = compress_info.get(name, zipfile.ZIP_DEFLATED)
                        zw.writestr(name, file_data[name], compress_type=ct)
                zw.writestr(cover_media_path, cover_data, compress_type=zipfile.ZIP_DEFLATED)

        temp_path.replace(epub_path)
        logger.info(f"已添加随机封面: {cover_src.name}")
        return True
    except Exception:
        logger.debug("添加封面失败", exc_info=True)
        try:
            temp_path.unlink()
        except Exception:
            pass
        return False


def _clean_epub_text_content(epub_path: Path) -> bool:
    """Post-process EPUB: clean garbled text and set font-family. Returns True if modified."""
    temp_path = epub_path.with_suffix(".epub.clean")
    modified = False

    try:
        with zipfile.ZipFile(epub_path, 'r') as zr:
            file_list = zr.namelist()
            compress_info = {}
            file_data = {}
            for name in file_list:
                info = zr.getinfo(name)
                compress_info[name] = info.compress_type
                data = zr.read(name)
                if name.endswith(('.xhtml', '.html', '.htm')):
                    content = data.decode('utf-8')
                    cleaned = _clean_html_text(content)
                    if cleaned != content:
                        file_data[name] = cleaned.encode('utf-8')
                        modified = True
                    else:
                        file_data[name] = data
                elif name.endswith('.css'):
                    content = data.decode('utf-8')
                    font_rule = "body { font-family: \"Hannotate SC\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; }\n"
                    if font_rule not in content:
                        content = font_rule + content
                        file_data[name] = content.encode('utf-8')
                        modified = True
                    else:
                        file_data[name] = data
                else:
                    file_data[name] = data

        if not modified:
            try:
                temp_path.unlink()
            except Exception:
                pass
            return False

        with zipfile.ZipFile(temp_path, 'w') as zw:
            if 'mimetype' in file_data:
                zw.writestr('mimetype', file_data['mimetype'], compress_type=zipfile.ZIP_STORED)
            for name in file_list:
                if name != 'mimetype':
                    ct = compress_info.get(name, zipfile.ZIP_DEFLATED)
                    zw.writestr(name, file_data[name], compress_type=ct)

        temp_path.replace(epub_path)
        return True
    except Exception:
        logger.debug("EPUB 后处理失败", exc_info=True)
        try:
            temp_path.unlink()
        except Exception:
            pass
        return False


def _extract_images_from_doc(doc_path: Path) -> list[tuple[str, bytes]]:
    """Extract embedded JPEG/PNG images from .doc OLE Data stream.

    Returns list of (suffix, image_bytes) tuples.
    """
    try:
        import olefile
    except ImportError:
        return []

    try:
        ole = olefile.OleFileIO(str(doc_path))
    except Exception:
        return []

    images = []
    try:
        if ole.exists('Data'):
            stream = ole.openstream('Data')
            data = stream.read()
            stream.close()

            jpeg_starts = [(m.start(), m.end()) for m in re.finditer(b'\xff\xd8\xff', data)]
            for start, _ in jpeg_starts:
                end = data.find(b'\xff\xd9', start)
                if end > start:
                    img_data = data[start:end + 2]
                    if len(img_data) > 1000:
                        images.append(('.jpg', img_data))

            png_starts = [m.start() for m in re.finditer(b'\x89PNG', data)]
            for start in png_starts:
                end = data.find(b'IEND\xaeB`\x82', start)
                if end > start:
                    img_data = data[start:end + 8]
                    if len(img_data) > 1000:
                        images.append(('.png', img_data))
    except Exception:
        pass
    finally:
        ole.close()

    return images


def _embed_images_in_epub(epub_path: Path, images: list[tuple[str, bytes]]) -> bool:
    """Add extracted images to an existing EPUB. Returns True if modified."""
    if not images:
        return False

    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}

    temp_path = epub_path.with_suffix(".epub.imgs")
    modified = False

    try:
        with zipfile.ZipFile(epub_path, 'r') as zr:
            file_list = zr.namelist()
            compress_info = {}
            file_data = {}

            for name in file_list:
                info = zr.getinfo(name)
                compress_info[name] = info.compress_type
                data = zr.read(name)
                if name.endswith('.opf'):
                    content = data.decode('utf-8')
                    img_manifest_entries = ""
                    spine_entries = ""
                    for idx, (suffix, _) in enumerate(images):
                        img_id = f"ole-img-{idx}"
                        img_name = f"ole-img-{idx}{suffix}"
                        img_manifest_entries += f'    <item id="{img_id}" href="media/{img_name}" media-type="{mime_map.get(suffix, "image/jpeg")}" />\n'
                        img_manifest_entries += f'    <item id="{img_id}_xhtml" href="text/{img_id}.xhtml" media-type="application/xhtml+xml" />\n'
                        spine_entries += f'    <itemref idref="{img_id}_xhtml" />\n'

                    content = content.replace('  </manifest>', f'{img_manifest_entries}  </manifest>')
                    if '</spine>' in content:
                        content = content.replace('  </spine>', f'{spine_entries}  </spine>')
                    file_data[name] = content.encode('utf-8')
                else:
                    file_data[name] = data

            for idx, (suffix, img_bytes) in enumerate(images):
                img_id = f"ole-img-{idx}"
                img_name = f"ole-img-{idx}{suffix}"
                file_data[f"EPUB/media/{img_name}"] = img_bytes

                xhtml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh" xml:lang="zh">
<head><title>插图 {idx + 1}</title></head>
<body epub:type="bodymatter">
<section>
<h2>插图 {idx + 1}</h2>
<p><img src="../media/{img_name}" alt="插图 {idx + 1}" /></p>
</section>
</body>
</html>'''
                file_data[f"EPUB/text/{img_id}.xhtml"] = xhtml.encode('utf-8')
                modified = True

        if not modified:
            try:
                temp_path.unlink()
            except Exception:
                pass
            return False

        with zipfile.ZipFile(temp_path, 'w') as zw:
            if 'mimetype' in file_data:
                zw.writestr('mimetype', file_data['mimetype'], compress_type=zipfile.ZIP_STORED)
            for name in file_list:
                if name != 'mimetype':
                    ct = compress_info.get(name, zipfile.ZIP_DEFLATED)
                    zw.writestr(name, file_data[name], compress_type=ct)
            for key in file_data:
                if key not in ['mimetype'] and key not in {n for n in file_list}:
                    zw.writestr(key, file_data[key], compress_type=zipfile.ZIP_DEFLATED)

        temp_path.replace(epub_path)
        return True
    except Exception:
        logger.debug("嵌入 OLE 图片失败", exc_info=True)
        try:
            temp_path.unlink()
        except Exception:
            pass
        return False


def convert_to_epub(file_path: Path, output_path: Path = None,
                    title: str = "", author: str = "") -> Path:
    from src.core.paths import extract_pdf_cover, extract_epub_cover

    suffix = file_path.suffix.lower()

    if not title:
        title = file_path.stem
    if not author:
        author = "未知"

    if output_path is None:
        output_path = file_path.with_suffix(".epub")

    if suffix in (".docx", ".doc"):
        pandoc_input = file_path
        temp_docx = None

        if suffix == ".doc":
            temp_docx = Path(tempfile.mktemp(suffix=".docx"))
            try:
                result = subprocess.run(
                    ["textutil", "-convert", "docx", str(file_path), "-output", str(temp_docx)],
                    capture_output=True, timeout=30,
                )
                if result.returncode == 0 and temp_docx.exists():
                    pandoc_input = temp_docx
                    logger.info("已通过 textutil 将 .doc 转为 .docx")
            except Exception:
                pass

        try:
            result = subprocess.run(
                ["pandoc", str(pandoc_input), "-o", str(output_path),
                 "--metadata", f"title={title}",
                 "--metadata", f"author={author}",
                 "--metadata", "lang=zh",
                 "--to=epub"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and output_path.exists():
                _clean_epub_text_content(output_path)
                _add_cover_to_epub(output_path)
                if suffix == ".doc":
                    ole_imgs = _extract_images_from_doc(file_path)
                    if ole_imgs:
                        _embed_images_in_epub(output_path, ole_imgs)
                        logger.info(f"已从 .doc 提取 {len(ole_imgs)} 张图片")
                logger.info("已后处理 EPUB（乱码清理 + 字体设置 + 封面）")
                if temp_docx and temp_docx.exists():
                    temp_docx.unlink()
                return output_path
            else:
                stderr = result.stderr.strip()
                if stderr:
                    logger.warning(f"pandoc 转换警告: {stderr[:200]}")
                raise RuntimeError("pandoc 转换失败")
        except FileNotFoundError:
            logger.info("未找到 pandoc，使用内置转换器")
        except Exception as e:
            stderr = result.stderr.strip()[:200] if 'result' in dir() and result.stderr else ""
            logger.warning(f"pandoc 转换失败: {e} {stderr}，回退到内置转换器")
        finally:
            if temp_docx and temp_docx.exists():
                try:
                    temp_docx.unlink()
                except Exception:
                    pass

        text = convert_to_txt(file_path)
        return _build_epub_from_text(text, title, author, file_path, output_path,
                                     extract_pdf_cover, extract_epub_cover, suffix)

    text = convert_to_txt(file_path)
    return _build_epub_from_text(text, title, author, file_path, output_path,
                                 extract_pdf_cover, extract_epub_cover, suffix)


def _build_epub_from_text(text: str, title: str, author: str,
                          file_path: Path, output_path: Path,
                          extract_pdf_cover, extract_epub_cover,
                          suffix: str) -> Path:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(f"akm-epub-{hashlib.md5(str(file_path).encode()).hexdigest()[:8]}")
    book.set_title(title)
    book.set_language("zh")
    book.add_author(author)

    chapters = []
    paragraphs = text.split("\n\n")
    chunk_size = 50
    for i in range(0, len(paragraphs), chunk_size):
        chunk_paragraphs = paragraphs[i:i + chunk_size]
        chunk_title = title if i == 0 else f"{title} ({i // chunk_size + 2})"
        chapter = epub.EpubHtml(
            title=chunk_title,
            file_name=f"chap_{i // chunk_size + 1}.xhtml",
            lang="zh"
        )
        content = "<h2>" + chunk_title + "</h2>\n"
        for p in chunk_paragraphs:
            if p.strip():
                content += f"<p>{p.strip()}</p>\n"
        chapter.content = content
        book.add_item(chapter)
        chapters.append(chapter)

    cover_data = None
    if suffix == ".pdf":
        cover_data = extract_pdf_cover(file_path)
    elif suffix == ".epub":
        cover_data = extract_epub_cover(file_path)

    if not cover_data:
        cover_dir = Path(__file__).resolve().parents[2] / "cover"
        if cover_dir.is_dir():
            img_exts = {'.jpg', '.jpeg', '.png', '.gif'}
            cover_files = [p for p in cover_dir.iterdir() if p.suffix.lower() in img_exts]
            if cover_files:
                cover_src = random.choice(cover_files)
                try:
                    cover_data = cover_src.read_bytes()
                    logger.info(f"已添加随机封面: {cover_src.name}")
                except Exception:
                    pass

    if cover_data:
        book.set_cover("cover.jpg", cover_data)

    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    style = epub.EpubItem(
        uid="style",
        file_name="style/default.css",
        media_type="text/css",
        content="body { font-family: \"Hannotate SC\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; line-height: 1.8; } h2 { text-align: center; } p { text-indent: 2em; }"
    )
    book.add_item(style)
    spine = ["nav"] + chapters
    book.spine = spine

    epub.write_epub(str(output_path), book)
    return output_path
