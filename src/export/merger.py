import html as _html
import uuid
import zipfile
from pathlib import Path

from ebooklib import epub as _epub
import ebooklib
from bs4 import BeautifulSoup
from pypdf import PdfWriter

from .models import MergeMeta, TypeGroup
from src.core.logging import logger


from src.domain.cdbook import normalize_series_name as _safe_filename


def _build_separator_html(vol_num: int, book_title: str, book_author: str) -> str:
    safe_title = _html.escape(book_title)
    safe_author = _html.escape(book_author)
    return f"""<html xmlns="http://www.w3.org/1999/xhtml">
<body>
  <div style="text-align:center; margin-top:30%; font-family:sans-serif;">
    <h2 style="color:#888; font-weight:normal; font-size:1.4em;">第 {vol_num} 卷</h2>
    <h1 style="font-size:1.8em;">《{safe_title}》</h1>
    <p style="color:#aaa; font-size:1.1em;">作者：{safe_author}</p>
  </div>
</body>
</html>"""


def merge_epubs(paths: list[Path], output_path: Path,
                title: str, author: str,
                book_metas: list[MergeMeta] = None) -> bool:
    try:
        _ITEM_COVER = getattr(ebooklib, 'ITEM_COVER', ebooklib.ITEM_IMAGE)
        use_hierarchy = book_metas is not None and len(book_metas) > 0

        book = _epub.EpubBook()
        book.set_identifier(str(uuid.uuid4()))
        book.set_title(title)
        book.set_language('zh')
        book.add_author(author)

        spine_items = []
        image_name_map = {}
        chapter_count = 0
        cover_set = False
        chapters_flat = []

        pairs = zip(paths, book_metas) if use_hierarchy else [(p, None) for p in paths]

        for idx, (path, meta) in enumerate(pairs):
            if not path.exists():
                continue
            try:
                in_book = _epub.read_epub(str(path))
            except Exception as e:
                logger.warning("读取 EPUB 失败 %s: %s", path.name, e)
                continue

            for item in in_book.get_items():
                item_type = item.get_type()
                if item_type in (ebooklib.ITEM_IMAGE, _ITEM_COVER):
                    old_name = item.get_name()
                    ext = Path(old_name).suffix
                    new_name = f"images/img_{uuid.uuid4().hex[:8]}{ext}"
                    image_name_map[old_name] = new_name

                    new_item = _epub.EpubItem(
                        uid=f"img_{uuid.uuid4().hex[:8]}",
                        file_name=new_name,
                        media_type=item.media_type,
                        content=item.get_content()
                    )
                    book.add_item(new_item)

                    if not cover_set and idx == 0:
                        book.set_cover("cover.jpg", item.get_content())
                        cover_set = True

            book_chapters = []

            if use_hierarchy and meta:
                sep = _epub.EpubHtml(
                    title=meta.book_title,
                    file_name=f'sep_{idx:04d}.xhtml',
                    lang='zh'
                )
                sep.content = _build_separator_html(idx + 1, meta.book_title, meta.book_author)
                book.add_item(sep)
                spine_items.append(sep)

            reading_order = []
            if in_book.spine:
                for spine_entry in in_book.spine:
                    uid = spine_entry[0] if isinstance(spine_entry, (tuple, list)) else spine_entry
                    doc_item = in_book.get_item_with_id(uid)
                    if doc_item and doc_item.get_type() == ebooklib.ITEM_DOCUMENT:
                        reading_order.append(doc_item)
            if not reading_order:
                for doc_item in in_book.get_items():
                    if doc_item.get_type() == ebooklib.ITEM_DOCUMENT:
                        reading_order.append(doc_item)

            for doc_item in reading_order:
                item_name = Path(doc_item.get_name() or "").stem
                if item_name.lower() in ('cover', 'titlepage', 'title-page', 'title_page'):
                    continue

                soup = BeautifulSoup(doc_item.get_content(), 'html.parser')

                for img in soup.find_all('img'):
                    img_src = img.get('src')
                    if img_src:
                        clean_src = img_src.rsplit('/', 1)[-1]
                        for old_n, new_n in image_name_map.items():
                            if clean_src == old_n.rsplit('/', 1)[-1]:
                                img['src'] = new_n
                                break

                body = soup.find('body')
                if not body:
                    continue

                text_content = body.get_text(strip=True)
                has_img = body.find('img') is not None
                if not text_content and not has_img:
                    continue

                if use_hierarchy and meta:
                    part_title = meta.book_title
                else:
                    h1 = body.find('h1')
                    part_title = h1.text.strip() if h1 else f"第 {chapter_count + 1} 部分"

                safe_part_title = _html.escape(part_title)
                c = _epub.EpubHtml(
                    title=safe_part_title,
                    file_name=f'chapter_{chapter_count}.xhtml',
                    lang='zh'
                )
                c.content = ''.join(str(tag) for tag in body.contents)
                book.add_item(c)
                spine_items.append(c)
                chapters_flat.append(c)

                chapter_count += 1

        if chapter_count == 0:
            return False

        book.toc = tuple(chapters_flat)

        book.add_item(_epub.EpubNcx())
        book.add_item(_epub.EpubNav())

        style = '''
        body { font-family: sans-serif; }
        h1 { text-align: center; }
        img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
        '''
        nav_css = _epub.EpubItem(
            uid="style_nav",
            file_name="style/nav.css",
            media_type="text/css",
            content=style
        )
        book.add_item(nav_css)
        book.spine = ['nav'] + spine_items

        _epub.write_epub(str(output_path), book, {})
        return True
    except Exception as e:
        logger.error("合并 EPUB 发生错误: %s", e)
        return False


def merge_pdfs(paths: list[Path], output_path: Path) -> bool:
    try:
        writer = PdfWriter()
        for path in paths:
            if path.exists():
                try:
                    writer.append(str(path))
                except Exception as e:
                    logger.warning(f"无法合并 PDF {path.name}: {e}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer.write(str(output_path))
        writer.close()
        return True
    except Exception as e:
        logger.error(f"合并 PDF 发生错误: {e}")
        return False


def merge_to_zip(rows: list[dict], output_path: Path) -> bool:
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, row in enumerate(rows):
                fp = Path(row.get("文件路径", ""))
                if fp.exists():
                    fname = row.get("标题", "") or fp.name
                    if not fname.lower().endswith(fp.suffix.lower()):
                        fname += fp.suffix
                    fname = _safe_filename(fname)
                    zf.write(fp, arcname=f"{i + 1:03d}_{fname}")
        return True
    except Exception as e:
        logger.error(f"打包 ZIP 失败: {e}")
        return False


def merge_series_group(series_groups: dict[str, list[dict]], content_dir: Path,
                       is_tag_mode: bool, query: str,
                       progress: object | None = None) -> int:
    count = 0
    for series_name, srows in series_groups.items():
        safe_name = _safe_filename(series_name)
        srows.sort(key=lambda x: x.get("ID", ""))

        all_epub = all((r.get("后缀", "") or "").lower() == ".epub" for r in srows)
        all_pdf = all((r.get("后缀", "") or "").lower() == ".pdf" for r in srows)
        merged = False

        if all_epub:
            epub_paths = [Path(r.get("文件路径", "")) for r in srows]
            epub_paths = [p for p in epub_paths if p.exists()]
            if epub_paths:
                output = content_dir / f"{safe_name}.epub"
                author_name = "Tag_Export" if is_tag_mode else query
                book_metas = [
                    MergeMeta(book_title=r.get("标题", ""), book_author=r.get("作者", ""))
                    for r in srows if Path(r.get("文件路径", "")).exists()
                ]
                if merge_epubs(epub_paths, output, series_name, author_name, book_metas=book_metas):
                    count += 1
                    merged = True
                else:
                    logger.error(f"合并系列 {series_name} 失败，回退为 ZIP 压缩包")

        if all_pdf and not merged:
            pdf_paths = [Path(r.get("文件路径", "")) for r in srows]
            pdf_paths = [p for p in pdf_paths if p.exists()]
            if pdf_paths:
                output = content_dir / f"{safe_name}.pdf"
                if merge_pdfs(pdf_paths, output):
                    count += 1
                    merged = True
                else:
                    logger.error(f"合并系列 {series_name} (PDF) 失败，回退为 ZIP 压缩包")

        if not merged:
            output = content_dir / f"{safe_name}.zip"
            if merge_to_zip(srows, output):
                count += 1

    return count


def merge_by_completeness(type_groups: dict[str, TypeGroup], dest_dir: Path,
                          export_name: str, is_tag_mode: bool, query: str) -> dict:
    results = {}
    safe_name = _safe_filename(export_name)

    for file_type, tg in type_groups.items():
        paths = []
        metas = []

        for series_name in sorted(tg.series_groups.keys()):
            for row in tg.series_groups[series_name]:
                fp = Path(row.get("文件路径", ""))
                if fp.exists():
                    paths.append(fp)
                    metas.append(MergeMeta(
                        book_title=row.get("标题", fp.stem),
                        book_author=row.get("作者", ""),
                        series=series_name,
                    ))

        for row in tg.standalone:
            fp = Path(row.get("文件路径", ""))
            if fp.exists():
                paths.append(fp)
                metas.append(MergeMeta(
                    book_title=row.get("标题", fp.stem),
                    book_author=row.get("作者", ""),
                ))

        if not paths:
            results[file_type] = {"status": "skipped", "reason": "无有效文件路径"}
            continue

        first_row = tg.standalone[0] if tg.standalone else list(tg.series_groups.values())[0][0]
        suffix = (first_row.get("后缀", "") or "").lower()

        output_filename = f"{file_type}_{safe_name}{suffix}"
        output_path = dest_dir / output_filename

        merged = False
        if suffix == ".epub":
            author_name = "Tag_Export" if is_tag_mode else query
            merged = merge_epubs(paths, output_path, f"{file_type}_全集", author_name, book_metas=metas)
        elif suffix == ".pdf":
            merged = merge_pdfs(paths, output_path)

        if merged:
            results[file_type] = {"status": "merged", "output": str(output_path), "count": len(paths)}
        else:
            results[file_type] = {"status": "failed", "reason": "合并失败"}

    return results
