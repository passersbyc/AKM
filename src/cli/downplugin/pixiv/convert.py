import re
import html
import zipfile
import tempfile
import mimetypes
from pathlib import Path
from typing import Optional, Generator

from PIL import Image
import io as _io

from src.domain.cdbook import normalize_series_name
from src.core.utils import description_to_text
from src.core.converter import convert_images_to_book
from src.core.logging import get_logger
from .types import ExtractMessage

logger = get_logger("akm.pixiv_convert")


def _unique_path(base: Path, stem: str, ext: str) -> Path:
    return base / f"{stem}{ext}"




def _collect_image_url(value) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        url = value.get("url") or value.get("original") or value.get("originalUrl")
        if url:
            return str(url)
        urls = value.get("urls") or value.get("imageUrls") or value.get("image_urls")
        if isinstance(urls, dict):
            for key in ["original", "originalImageUrl", "raw", "1200x1200", "large", "regular", "medium", "small"]:
                u = urls.get(key)
                if u:
                    return str(u)
    return None


def extract_tags(body: dict) -> list[str]:
    tags = body.get("tags")
    res = []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and t.strip():
                res.append(t.strip())
            elif isinstance(t, dict) and t.get("tag"):
                res.append(str(t.get("tag")).strip())
    elif isinstance(tags, dict):
        tl = tags.get("tags") or []
        for t in tl:
            if isinstance(t, dict) and t.get("tag"):
                res.append(str(t.get("tag")).strip())
            elif isinstance(t, str) and t.strip():
                res.append(t.strip())
    return [t for t in res if t]


def extract_novel_images(body: dict) -> dict[str, str]:
    result = {}
    candidates = []
    for key in ["textEmbeddedImages", "images", "imageUrls", "image_urls", "illusts", "illustImages",
                "illustsMap", "uploadedImages", "uploadedImage", "uploadedimage"]:
        v = body.get(key)
        if v:
            candidates.append(v)
    for obj in candidates:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, dict):
                    vid = v.get("novelImageId") or v.get("id") or v.get("imageId") or v.get("image_id") or v.get(
                        "illustId") or v.get("illust_id")
                    url = _collect_image_url(v)
                    if url:
                        result[str(vid or k)] = url
                else:
                    url = _collect_image_url(v)
                    if url:
                        result[str(k)] = url
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                if isinstance(v, dict):
                    vid = v.get("id") or v.get("imageId") or v.get("image_id") or v.get("illustId") or v.get("illust_id")
                    url = _collect_image_url(v)
                    if url:
                        result[str(vid or idx)] = url
                else:
                    url = _collect_image_url(v)
                    if url:
                        result[str(idx)] = url
    return result


def convert_novel_markup(text: str, prefix: str = "") -> "tuple[str, list[dict]]":
    replacements: list[dict] = []
    index = 0

    def _replace_bold(m: "re.Match[str]") -> str:
        nonlocal index
        index += 1
        content = m.group(1)
        ph = f"__PIXIV_BOLD_{prefix}{index}__"
        replacements.append({"placeholder": ph, "href": "", "html": f"<b>{html.escape(content)}</b>"})
        return ph

    def _replace_ruby(m: "re.Match[str]") -> str:
        nonlocal index
        index += 1
        kanji = m.group(1).strip()
        reading = m.group(2).strip()
        ph = f"__PIXIV_RUBY_{prefix}{index}__"
        replacements.append(
            {"placeholder": ph, "href": "", "html": f"<ruby>{html.escape(kanji)}<rt>{html.escape(reading)}</rt></ruby>"})
        return ph

    text = re.sub(r'\{\{(.*?)\}\}', _replace_bold, text, flags=re.DOTALL)
    text = re.sub(r'\[\[rb:\s*(\S+?)\s*>\s*(.+?)\]\]', _replace_ruby, text, flags=re.DOTALL)
    return text, replacements


def build_inline_images(text: str, body: dict, prefix: str = "",
                        download_fn=None, stop_event=None) -> tuple[str, list[dict]]:
    images = extract_novel_images(body)
    pattern = re.compile(r"\[(?:pixivimage|uploadedimage):(\d+)\]")
    text = text or ""
    matches = list(pattern.finditer(text))
    if not matches:
        return text, []

    image_ids = [m.group(1) for m in matches]
    url_map = {}
    for image_id in set(image_ids):
        url = images.get(image_id)
        if url:
            url_map[image_id] = url

    cache = {}
    if download_fn:
        import concurrent.futures
        tasks = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            for image_id, url in url_map.items():
                tasks[image_id] = executor.submit(download_fn, url)
            for image_id, future in tasks.items():
                if stop_event and stop_event.is_set():
                    break
                try:
                    data, ext, mime = future.result()
                    if data and ext and mime:
                        cache[image_id] = (data, ext, mime)
                except Exception:
                    pass

    parts = []
    last = 0
    inline_images = []
    for idx, m in enumerate(matches, start=1):
        parts.append(text[last:m.start()])
        image_id = m.group(1)
        cached = cache.get(image_id)
        if cached:
            data, ext, mime = cached
            href = f"images/inline_{prefix}{idx}{ext}"
            placeholder = f"__PIXIV_IMAGE_{prefix}{idx}__"
            inline_images.append({"placeholder": placeholder, "href": href, "bytes": data, "mime": mime})
            parts.append(placeholder)
        last = m.end()
    parts.append(text[last:])
    replaced = "".join(parts)
    return replaced, inline_images


def write_novel_epub(text: str, metadata: dict, identifier: str, output_path: Path,
                     cover_bytes: Optional[bytes] = None, cover_ext: Optional[str] = None,
                     cover_mime: Optional[str] = None, inline_images: Optional[list[dict]] = None,
                     chapters: Optional[list[dict]] = None) -> bool:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        title = metadata.get("title") or "untitled"
        author = metadata.get("author") or ""
        description = metadata.get("description") or ""
        tags = metadata.get("tags") or []
        pub_date = metadata.get("date") or ""
        safe_title = html.escape(title)
        safe_author = html.escape(author)
        safe_id = html.escape(identifier or title or "pixiv-novel")
        safe_desc = html.escape(description)
        inline_images = inline_images or []
        placeholder_map = {i["placeholder"]: i for i in inline_images if i.get("placeholder")}
        placeholder_pattern = None
        if placeholder_map:
            placeholder_pattern = re.compile("(" + "|".join(re.escape(k) for k in placeholder_map.keys()) + ")")

        body_parts = []

        def render_text(txt: str):
            raw = (txt or "").replace("\r\n", "\n")
            blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
            if not blocks:
                blocks = [b.strip() for b in raw.splitlines() if b.strip()]
            for b in blocks:
                if placeholder_pattern and placeholder_pattern.search(b):
                    parts_list = placeholder_pattern.split(b)
                    for part in parts_list:
                        if part in placeholder_map:
                            entry = placeholder_map[part]
                            if "html" in entry:
                                body_parts.append('<span class="markup">' + entry["html"] + '</span>')
                            elif entry.get("href"):
                                body_parts.append(
                                    '<div class="illust"><img src="' + entry["href"] + '" alt="illustration"/></div>')
                            else:
                                lines = [html.escape(x) for x in part.split("\n") if x.strip()]
                                if lines:
                                    body_parts.append("<p>" + "<br/>".join(lines) + "</p>")
                        else:
                            lines = [html.escape(x) for x in part.split("\n") if x.strip()]
                            if lines:
                                body_parts.append("<p>" + "<br/>".join(lines) + "</p>")
                else:
                    lines = [html.escape(x) for x in b.split("\n") if x.strip()]
                    if lines:
                        body_parts.append("<p>" + "<br/>".join(lines) + "</p>")

        if chapters:
            for idx, ch in enumerate(chapters, start=1):
                ch_title = ch.get("title") or f"第{idx}话"
                body_parts.append('<h2 id="ch' + str(idx) + '">' + html.escape(str(ch_title)) + "</h2>")
                ch_text = ch.get("text") or ""
                ch_text, markup_items = convert_novel_markup(ch_text, f"ch{idx}_")
                for mi in markup_items:
                    placeholder_map[mi["placeholder"]] = mi
                if placeholder_map:
                    placeholder_pattern = re.compile(
                        "(" + "|".join(re.escape(k) for k in placeholder_map.keys()) + ")")
                render_text(ch_text)
        else:
            text, markup_items = convert_novel_markup(text or "", "m_")
            for mi in markup_items:
                placeholder_map[mi["placeholder"]] = mi
            if placeholder_map:
                placeholder_pattern = re.compile("(" + "|".join(re.escape(k) for k in placeholder_map.keys()) + ")")
            render_text(text or "")

        body_html = "\n".join(body_parts) if body_parts else "<p></p>"

        meta_lines = [
            '    <dc:identifier id="BookId">' + safe_id + "</dc:identifier>",
            '    <dc:title>' + safe_title + "</dc:title>",
            '    <dc:creator>' + safe_author + "</dc:creator>",
            '    <dc:language>zh</dc:language>',
        ]
        if safe_desc:
            meta_lines.append("    <dc:description>" + safe_desc + "</dc:description>")
        if pub_date:
            meta_lines.append("    <dc:date>" + html.escape(str(pub_date)) + "</dc:date>")
        for t in tags:
            if t:
                meta_lines.append("    <dc:subject>" + html.escape(str(t)) + "</dc:subject>")
        if cover_bytes:
            meta_lines.append('    <meta name="cover" content="cover-image"/>')
        meta_block = "\n".join(meta_lines)

        styles_css = (
            "body{font-family:\"Hannotate SC\",\"PingFang SC\",\"Microsoft YaHei\",sans-serif;line-height:1.6;}"
            "h1{margin:0.6em 0;}h2{margin:1em 0 0.4em;}"
            "p{margin:0.5em 0;} .meta{font-size:0.9em;color:#555;} .cover{display:flex;justify-content:center;"
            "align-items:center;height:100vh;} .illust{margin:1em 0;text-align:center;} img{max-width:100%;height:auto;}"
        )

        content_xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">\n'
            "<head><title>" + safe_title + '</title><meta charset="utf-8"/>'
            '<link rel="stylesheet" type="text/css" href="styles.css"/></head>\n'
            "<body>\n"
            "<h1>" + safe_title + "</h1>\n"
            '<div class="meta">' + (safe_author or "") + "</div>\n"
            + (f'<div class="meta">{safe_desc}</div>\n' if safe_desc else "")
            + (f'<div class="meta">标签：{", ".join([html.escape(str(t)) for t in tags])}</div>\n' if tags else "")
            + body_html + "\n</body>\n</html>\n"
        )

        manifest_items = [
            '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
            '    <item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>',
            '    <item id="style" href="styles.css" media-type="text/css"/>',
        ]
        spine_items = []
        cover_xhtml = None
        cover_href = None
        cover_image_href = None
        if cover_bytes:
            cover_ext = cover_ext or ".jpg"
            cover_mime = cover_mime or mimetypes.types_map.get(cover_ext.lower(), "image/jpeg")
            cover_image_href = f"images/cover{cover_ext}"
            cover_href = "cover.xhtml"
            manifest_items.append(
                '    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
            manifest_items.append(
                f'    <item id="cover-image" href="{cover_image_href}" media-type="{cover_mime}"/>')
            spine_items.append('    <itemref idref="cover"/>')
            cover_xhtml = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">\n'
                '<head><title>Cover</title><meta charset="utf-8"/>'
                '<link rel="stylesheet" type="text/css" href="styles.css"/></head>\n'
                '<body class="cover"><img src="' + cover_image_href + '" alt="cover"/></body>\n'
                "</html>\n"
            )
        for idx, item in enumerate(inline_images, start=1):
            href = item.get("href")
            mime = item.get("mime")
            if href and mime:
                manifest_items.append(f'    <item id="inline-{idx}" href="{href}" media-type="{mime}"/>')
        spine_items.append('    <itemref idref="content"/>')

        content_opf = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            + meta_block + "\n  </metadata>\n  <manifest>\n"
            + "\n".join(manifest_items) + "\n  </manifest>\n"
            '  <spine toc="ncx">\n' + "\n".join(spine_items) + "\n  </spine>\n</package>\n"
        )

        nav_points = []
        play_order = 1
        if cover_href:
            nav_points.append(
                f'    <navPoint id="navPoint-{play_order}" playOrder="{play_order}">\n'
                f"      <navLabel><text>封面</text></navLabel>\n"
                f'      <content src="{cover_href}"/>\n    </navPoint>'
            )
            play_order += 1
        nav_points.append(
            f'    <navPoint id="navPoint-{play_order}" playOrder="{play_order}">\n'
            f"      <navLabel><text>{safe_title}</text></navLabel>\n"
            f'      <content src="content.xhtml"/>\n    </navPoint>'
        )
        play_order += 1
        if chapters:
            for idx, ch in enumerate(chapters, start=1):
                ch_title = html.escape(str(ch.get("title") or f"第{idx}话"))
                nav_points.append(
                    f'    <navPoint id="navPoint-{play_order}" playOrder="{play_order}">\n'
                    f"      <navLabel><text>{ch_title}</text></navLabel>\n"
                    f'      <content src="content.xhtml#ch{idx}"/>\n    </navPoint>'
                )
                play_order += 1

        toc_ncx = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            "  <head>\n"
            f'    <meta name="dtb:uid" content="{safe_id}"/>\n'
            '    <meta name="dtb:depth" content="1"/>\n'
            '    <meta name="dtb:totalPageCount" content="0"/>\n'
            '    <meta name="dtb:maxPageNumber" content="0"/>\n'
            f"  </head>\n  <docTitle><text>{safe_title}</text></docTitle>\n  <navMap>\n"
            + "\n".join(nav_points) + "\n  </navMap>\n</ncx>\n"
        )

        container_xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            "  <rootfiles>\n"
            '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
            "  </rootfiles>\n</container>\n"
        )

        with zipfile.ZipFile(output_path, "w") as zf:
            def _w(path: str, data, compress_type):
                info = zipfile.ZipInfo(path)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = compress_type
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)

            _w("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
            _w("META-INF/container.xml", container_xml, zipfile.ZIP_DEFLATED)
            _w("OEBPS/content.opf", content_opf, zipfile.ZIP_DEFLATED)
            _w("OEBPS/toc.ncx", toc_ncx, zipfile.ZIP_DEFLATED)
            _w("OEBPS/styles.css", styles_css, zipfile.ZIP_DEFLATED)
            if cover_xhtml and cover_image_href and cover_bytes:
                _w("OEBPS/cover.xhtml", cover_xhtml, zipfile.ZIP_DEFLATED)
                _w(f"OEBPS/{cover_image_href}", cover_bytes, zipfile.ZIP_DEFLATED)
            for item in inline_images:
                href = item.get("href")
                data = item.get("bytes")
                if href and data:
                    _w(f"OEBPS/{href}", data, zipfile.ZIP_DEFLATED)
            _w("OEBPS/content.xhtml", content_xhtml, zipfile.ZIP_DEFLATED)
        return True
    except Exception as e:
        logger.error("EPUB 生成失败: %s", e)
        return False


def download_ugoira_gif(client, pid: str, title: str, save_dir: Path,
                        stop_event=None) -> Optional[Path]:
    from urllib.parse import urlparse as _urlparse

    meta = _get_ugoira_meta(client, pid)
    if not meta:
        return None

    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        if not client.download_to_file(meta["src"], tmp_path, timeout=60, image_limit=True):
            return None

        with zipfile.ZipFile(tmp_path, "r") as zf:
            names = sorted(zf.namelist())
            frames = []
            for name in names:
                if stop_event and stop_event.is_set():
                    return None
                with zf.open(name) as zf_item:
                    frame = Image.open(_io.BytesIO(zf_item.read()))
                    frame.load()
                    frames.append(frame.copy())

        if not frames:
            return None

        frame_delays = [int(f.get("delay", 100)) for f in meta["frames"]]
        if len(frames) != len(frame_delays):
            if len(frame_delays) < len(frames):
                frame_delays.extend([frame_delays[-1]] * (len(frames) - len(frame_delays)))
            else:
                frame_delays = frame_delays[:len(frames)]

        durations = [max(d, 20) for d in frame_delays]

        safe_title = normalize_series_name(title)
        out = _unique_path(save_dir, safe_title, ".gif")

        frames[0].save(
            str(out), format="GIF", save_all=True,
            append_images=frames[1:], duration=durations,
            loop=0, disposal=2, optimize=False,
        )
        return out
    except Exception as e:
        logger.error("动图生成失败: %s", e)
        return None
    finally:
        if tmp_path:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _get_ugoira_meta(client, pid: str) -> Optional[dict]:
    url = f"https://www.pixiv.net/ajax/illust/{pid}/ugoira_meta"
    d = client.get_json(url)
    if not d or d.get("error"):
        return None
    body = d.get("body", {})
    return {
        "src": body.get("originalSrc") or body.get("src", ""),
        "frames": [f for f in body.get("frames", [])],
    }


def get_illust_pages(client, pid: str) -> tuple[list[str], bool]:
    """返回 (图片URL列表, is_404)。is_404=True 表示作品已删除/不存在。"""
    url = f"https://www.pixiv.net/ajax/illust/{pid}/pages"
    d = client.get_json(url)
    if not d or d.get("error"):
        is_404 = False
        if d is None:
            is_404 = True
        elif isinstance(d.get("error"), dict):
            is_404 = str(d["error"].get("code", "")) == "404"
        get_logger("akm.pixiv_extractor").warning(
            "/ajax/illust/%s/pages 返回空或错误 "
            "(error=%s, is_404=%s, "
            "可能原因: R-18限制 / 作品已删除 / Cookie失效)",
            pid,
            d.get('error') if d else 'None',
            is_404,
        )
        return [], is_404
    pages = d.get("body", [])
    res = []
    for p in pages:
        u = p.get("urls", {})
        o = u.get("original_medium") or u.get("original")
        if o:
            res.append(o)
    return res, False
