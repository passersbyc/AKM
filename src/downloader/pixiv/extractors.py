import re
import html as _html
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generator, Optional
from urllib.parse import urlparse, parse_qs

from src.domain.cdbook import normalize_series_name
from src.core.utils import description_to_text
from src.core.config import get_project_root
from src.core.converter import convert_images_to_book
from src.core.logging import get_logger
from .client import PixivClient
from .config import PixivConfig
from .types import ExtractMessage, WorkInfo
from .convert import (
    extract_tags, extract_novel_images, build_inline_images,
    convert_novel_markup, write_novel_epub, download_ugoira_gif,
    get_illust_pages, _unique_path,
)

logger = get_logger("akm.pixiv_extractor")

BASE_URL = "https://www.pixiv.net"


def extract_pixiv_id(url: str) -> str:
    m = re.search(r"/(?:artworks|illust(?:ration)?)/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(?:novel/show\.php\?|illust_)?id=(\d+)", url)
    if m:
        return m.group(1)
    return ""


class PixivBaseExtractor(ABC):
    category: str = "pixiv"
    subcategory: str = ""
    pattern: Optional[re.Pattern] = None
    child: Optional[type["PixivBaseExtractor"]] = None

    def __init__(self, client: PixivClient, config: PixivConfig):
        self.client = client
        self.config = config

    @abstractmethod
    def items(self, url: str) -> Generator[ExtractMessage, None, None]:
        ...

    @classmethod
    def find(cls, url: str) -> Optional[type["PixivBaseExtractor"]]:
        if "/users/" in url:
            return PixivUserExtractor
        if "/novel/series/" in url:
            return PixivNovelSeriesExtractor
        if "/series/" in url:
            return PixivSeriesExtractor
        if "/artworks/" in url or "/novel/show.php" in url:
            return PixivWorkExtractor
        return None

    @staticmethod
    def _extract_novel_text(body: dict, nid: str) -> str:
        text = body.get("text") or body.get("content") or body.get("novelText") or ""
        if not text:
            novel_entry = (body.get("userNovels") or {}).get(str(nid)) or {}
            text = novel_entry.get("text") or ""
        return text

    @staticmethod
    def _extract_novel_cover_url(body: dict, nid: str) -> str:
        cover_url = body.get("coverUrl") or body.get("coverURL") or body.get("cover_url")
        if not cover_url:
            novel_entry = (body.get("userNovels") or {}).get(str(nid)) or {}
            cover_url = novel_entry.get("url") or ""
        if cover_url and "limit_unviewable" in cover_url:
            cover_url = ""
        if not cover_url:
            image_urls = body.get("image_urls") or {}
            cover_url = image_urls.get("large") or image_urls.get("medium") or image_urls.get("square_medium") or ""
        return cover_url

    @staticmethod
    def _build_work_url(pid: str, content_type: str = "illust") -> str:
        if content_type == "novel":
            return f"{BASE_URL}/novel/show.php?id={pid}"
        return f"{BASE_URL}/artworks/{pid}"


def _text_has_content(text: str, description: str) -> bool:
    if not text or not text.strip():
        return False
    clean_text = re.sub(r'<[^>]+>', '', text).strip()
    clean_desc = re.sub(r'<[^>]+>', '', description).strip()
    if clean_text and clean_desc and len(clean_text) == len(clean_desc):
        if clean_text == clean_desc:
            return False
    return True


def _extract_thumbnail_url(body: dict, pid: str) -> str:
    user_illusts = body.get("userIllusts") or {}
    entry = user_illusts.get(pid, {})
    if isinstance(entry, dict):
        return entry.get("url", "") or ""
    return ""


def _thumbnail_to_original_urls(thumbnail_url: str, page_count: int, quality: str = "high") -> list[str]:
    if not thumbnail_url or not page_count:
        return []
    import re
    m = re.match(
        r"(https?://i\.pximg\.net)/c/\d+x\d+.*?/(?:img-master|custom-thumb)/(.+?)(\d+)(-[0-9a-f]+)?_p(\d+).*",
        thumbnail_url,
    )
    if not m:
        return []
    base, path_prefix, pid, hash_suffix, first_page = m.groups()
    hash_suffix = hash_suffix or ""
    first_page_num = int(first_page)
    urls = []
    for i in range(page_count):
        page_num = first_page_num + i
        if quality == "original":
            urls.append(f"{base}/img-original/{path_prefix}{pid}{hash_suffix}_p{page_num}.png")
        else:
            urls.append(f"{base}/img-master/{path_prefix}{pid}{hash_suffix}_p{page_num}_master1200.jpg")
    return urls


def _parse_work_info(ajax_data: dict, work_url: str) -> Optional[WorkInfo]:
    if ajax_data.get("error"):
        return None
    body = ajax_data.get("body", {})
    is_novel = "/novel/show.php" in work_url

    s = body.get("seriesNavData") or body.get("series")
    series = None
    series_id = None
    if isinstance(s, dict):
        series = s.get("title") or s.get("seriesTitle")
        series_id = s.get("seriesId") or s.get("id")

    stats = body.get("stats", {})
    like_count = int(stats.get("bookmarksCount") or stats.get("bookmarkCount") or
                     stats.get("likeCount") or body.get("bookmarkCount") or
                     stats.get("num_bookmarks") or 0)

    if is_novel:
        tags = extract_tags(body)
        title = body.get("title")
        author = body.get("userName") or body.get("user_name")
        description = body.get("caption") or body.get("description") or ""
        return WorkInfo(
            id=str(body.get("id", "")),
            type="novel",
            title=title or "",
            author=author or "",
            series=series,
            series_id=str(series_id) if series_id else None,
            tags=tags,
            description=description_to_text(description),
            like_count=like_count,
            view_count=body.get("viewCount", 0),
            bookmark_count=body.get("bookmarkCount", 0),
            comment_count=body.get("commentCount", 0),
            create_date=body.get("createDate", ""),
            user_id=str(body.get("userId", "")),
            _body=body,
        )

    tags_list = body.get("tags", {}).get("tags") or []
    tags = [t.get("tag") for t in tags_list if isinstance(t, dict) and t.get("tag")]
    illust_type_raw = body.get("illustType", 0)
    pid = str(body.get("illustId", "") or body.get("id", ""))
    thumbnail_url = _extract_thumbnail_url(body, pid)
    return WorkInfo(
        id=pid,
        type={0: "illust", 1: "manga", 2: "ugoira"}.get(illust_type_raw, "illust"),
        title=body.get("title") or "",
        author=body.get("userName") or "",
        series=series,
        series_id=str(series_id) if series_id else None,
        tags=tags,
        description=description_to_text(body.get("description") or ""),
        like_count=like_count,
        view_count=body.get("viewCount", 0),
        bookmark_count=body.get("bookmarkCount", 0),
        comment_count=body.get("commentCount", 0),
        page_count=body.get("pageCount", 1),
        illust_type=illust_type_raw,
        create_date=body.get("createDate", ""),
        user_id=str(body.get("userId", "")),
        _original_url=(body.get("urls", {}) or {}).get("original", ""),
        _thumbnail_url=thumbnail_url,
    )


def _fetch_novel_text_fallback(client, work_url: str, info: WorkInfo) -> Optional[str]:
    for attempt in range(3):
        try:
            client._api_rate_limit()
            html = client.get_text(work_url, timeout=20)
            if not html:
                return None

            og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
            if og_desc and not info.description:
                info.description = description_to_text(_html.unescape(og_desc.group(1)))
            if not info.title:
                og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
                if og_title:
                    t = _html.unescape(og_title.group(1))
                    for sep in (" - pixiv", " | ", " - "):
                        if sep in t:
                            t = t.split(sep)[0]
                    info.title = t

            novel_text = _extract_preload_text(html)
            if novel_text:
                return novel_text

            return description_to_text(info.description) if info.description else None
        except Exception:
            if attempt < 2:
                import time
                time.sleep(2)
                continue
            return None
    return None


def _extract_preload_text(html: str) -> Optional[str]:
    start_marker = 'id="meta-preload-data" content="'
    start_idx = html.find(start_marker)
    quote_char = '"'
    if start_idx == -1:
        start_marker = "id=\"meta-preload-data\" content='"
        start_idx = html.find(start_marker)
        quote_char = "'"
    if start_idx == -1:
        return _extract_nextjs_novel_text(html)

    start_idx += len(start_marker)
    end_idx = html.find(quote_char, start_idx)
    if end_idx == -1:
        return None

    json_str = html[start_idx:end_idx]
    try:
        import json
        data = json.loads(json_str)
    except (json.JSONDecodeError, Exception):
        import json
        json_str = json_str.replace("&quot;", '"').replace("&#39;", "'")
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, Exception):
            return None

    novel = data.get("novel", {})
    if not isinstance(novel, dict):
        return None

    text = novel.get("content") or novel.get("text") or novel.get("novelText") or ""
    if not text:
        return None

    if "<" in text:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(text, "html.parser").get_text(separator="\n")

    return text.strip()


def _extract_nextjs_novel_text(html: str) -> Optional[str]:
    import re, json
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        m = re.search(r'<script[^>]*>\s*(\{"props":\{"pageProps":.*?"novel":)', html, re.DOTALL)
    if not m:
        return None

    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, Exception):
        return None

    novel = None
    for path in [
        ["props", "pageProps", "novel"],
        ["props", "pageProps", "data", "novel"],
        ["props", "pageProps"],
    ]:
        d = data
        for key in path:
            d = d.get(key) if isinstance(d, dict) else None
            if d is None:
                break
        if isinstance(d, dict) and d.get("content"):
            novel = d
            break

    if not isinstance(novel, dict):
        return None

    text = novel.get("content") or novel.get("text") or novel.get("novelText") or ""
    if not text:
        return None

    if "<" in text:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(text, "html.parser").get_text(separator="\n")

    return text.strip()


class PixivWorkExtractor(PixivBaseExtractor):
    subcategory = "work"

    def items(self, url: str) -> Generator[ExtractMessage, None, None]:
        if "/novel/show.php" in url:
            yield from self._process_novel(url)
        elif "/artworks/" in url:
            yield from self._process_illust(url)

    def _process_illust(self, url: str) -> Generator[ExtractMessage, None, None]:
        pid = extract_pixiv_id(url)
        if not pid:
            yield ExtractMessage.error_msg(url, "作品ID解析失败")
            return

        ajax_data = self.client.get_json(f"{BASE_URL}/ajax/illust/{pid}")
        if not ajax_data:
            yield ExtractMessage.error_msg(url, "获取作品信息失败（网络异常或作品不存在）")
            return
        info = _parse_work_info(ajax_data, url)
        if not info:
            yield ExtractMessage.error_msg(url, "解析作品信息失败（可能需登录或已被删除）")
            return

        yield ExtractMessage.metadata_msg(url, info.to_metadata_dict())

        illust_error = ""
        if info.illust_type == 2:
            file_path = download_ugoira_gif(self.client, pid, info.title,
                                            self._download_dir(), self.client._stop_event)
            if not file_path:
                illust_error = "动图下载失败"
        else:
            quality = self.config.get("extractor", "pixiv-work", "image_quality", default="high")
            urls = self._resolve_image_urls(info, pid, quality)
            if not urls:
                yield ExtractMessage.error_msg(url, "获取图片列表失败（可能 R-18 受限、作品已删除或需登录）")
                return
            file_path, illust_error = self._download_illust_pages(pid, info.title, urls)

        if file_path:
            yield ExtractMessage.file_msg(url, file_path, info.to_metadata_dict())
        else:
            yield ExtractMessage.error_msg(url, illust_error or "文件下载失败")

    def _process_novel(self, url: str) -> Generator[ExtractMessage, None, None]:
        p = urlparse(url)
        nid = parse_qs(p.query).get("id", [None])[0]
        if not nid:
            yield ExtractMessage.error_msg(url, "小说ID解析失败")
            return

        ajax_data = self.client.get_json(f"{BASE_URL}/ajax/novel/{nid}", timeout=20)
        if not ajax_data:
            yield ExtractMessage.error_msg(url, "获取小说信息失败（网络异常或需登录）")
            return
        info = _parse_work_info(ajax_data, url)
        if not info:
            yield ExtractMessage.error_msg(url, "解析小说信息失败（可能需登录或已被删除）")
            return

        yield ExtractMessage.metadata_msg(url, info.to_metadata_dict())

        body = ajax_data.get("body", {})
        text = self._extract_novel_text(body, nid)
        if not text:
            fallback = _fetch_novel_text_fallback(self.client, url, info)
            text = fallback or ""

        description = description_to_text(body.get("description") or body.get("caption") or "")
        if not _text_has_content(text, description):
            yield ExtractMessage.error_msg(url, f"正文不完整：内容无法获取")
            return

        text, markup_items = convert_novel_markup(text, "m_")
        text, img_items = build_inline_images(
            text, body, "", self.client.download_binary, self.client._stop_event
        )
        inline_images = (markup_items or []) + (img_items or [])

        tags = extract_tags(body)
        author = info.author or body.get("userName") or body.get("user_name") or ""
        pub_date = body.get("createDate") or body.get("uploadDate") or body.get("published") or ""

        cover_url = self._extract_novel_cover_url(body, nid)
        cover_bytes = None
        cover_ext = None
        cover_mime = None
        if cover_url:
            cover_bytes, cover_ext, cover_mime = self.client.download_binary(cover_url, timeout=20, image_limit=True)

        safe_title = normalize_series_name(info.title)
        out = _unique_path(self._download_dir(), safe_title, ".epub")
        meta = {"title": info.title, "author": author, "description": description, "tags": tags, "date": pub_date}

        if write_novel_epub(text, meta, nid, out, cover_bytes, cover_ext, cover_mime, inline_images):
            yield ExtractMessage.file_msg(url, out, info.to_metadata_dict())
        else:
            yield ExtractMessage.error_msg(url, "EPUB生成失败")

    def _resolve_image_urls(self, info: WorkInfo, pid: str, quality: str = "high") -> list[str]:
        urls = []
        if info._original_url and info.page_count == 1:
            urls = [info._original_url]
        elif info._original_url and info.page_count > 1:
            urls = [info._original_url.replace("_p0.", f"_p{i}.") for i in range(info.page_count)]
        if not urls and info._thumbnail_url:
            urls = _thumbnail_to_original_urls(info._thumbnail_url, info.page_count, quality)
            if urls:
                logger.info("通过缩略图推断原图 URL (pid=%s, %d 页, %s)", pid, len(urls), quality)
        if not urls:
            logger.warning(
                "图片原始URL缺失 (pid=%s, page_count=%d, "
                "urls.original=%s), "
                "回退到 /ajax/illust/%s/pages 接口",
                pid, info.page_count,
                '有' if info._original_url else '无',
                pid,
            )
            urls, is_404 = get_illust_pages(self.client, pid)
            if not urls:
                logger.warning(
                    "图片列表解析失败 (pid=%s), 可能原因: R-18限制 / 作品已删除 / 需登录",
                    pid,
                )
                if is_404:
                    self._mark_deleted_by_pid(pid)
        return urls

    def _download_illust_pages(self, pid: str, title: str, urls: list[str]) -> tuple[Optional[Path], str]:
        import shutil
        safe_title = normalize_series_name(title)
        tmp_dir = self._download_dir() / f"{safe_title}__{pid}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        pairs: list[tuple[str, Path]] = []
        for u in urls:
            fn = u.split("/")[-1]
            fp = tmp_dir / fn
            if fp.exists():
                from PIL import Image as _PILImage
                try:
                    with _PILImage.open(fp) as img:
                        img.verify()
                    continue
                except Exception:
                    try:
                        fp.unlink()
                    except OSError:
                        pass
            pairs.append((u, fp))

        if pairs:
            if self.client.is_stopped:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return None, "用户取消"
            count = self.client.download_files_parallel(pairs, max_workers=4)
            if count < len(pairs):
                shutil.rmtree(tmp_dir, ignore_errors=True)
                if self.client.is_stopped:
                    return None, "用户取消"
                failed = len(pairs) - count
                return None, f"{failed}/{len(urls)} 页图片下载失败"

        try:
            pdf_path = convert_images_to_book(tmp_dir, target_format="pdf", delete_original=True)
            final = _unique_path(self._download_dir(), safe_title, ".pdf")
            pdf_path.rename(final)
            return final, ""
        except Exception as e:
            logger.error("打包PDF失败: %s", e)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None, "PDF打包失败"

    def _download_dir(self) -> Path:
        return getattr(self, "_save_dir", None) or Path("downloads")

    def _mark_deleted_by_pid(self, pid: str) -> None:
        from src.core.database import get_db
        db = get_db()
        db.execute(
            "UPDATE works SET source_status = 'deleted' WHERE source LIKE ?",
            (f"%artworks/{pid}%",)
        )
        db.commit()
        logger.info("已标记作品为已删除 (pid=%s)", pid)


class PixivUserExtractor(PixivBaseExtractor):
    subcategory = "user"
    child = PixivWorkExtractor

    def items(self, url: str) -> Generator[ExtractMessage, None, None]:
        uid = self._extract_uid(url)
        if not uid:
            yield ExtractMessage.error_msg(url, "用户ID解析失败")
            return

        works = self._get_user_works(uid)
        for work_url in works:
            yield ExtractMessage.url_msg(work_url, parent=url)

    def _extract_uid(self, url: str) -> str:
        m = re.search(r"/users/(\d+)", url)
        return m.group(1) if m else ""

    def _get_user_works(self, user_id: str) -> list[str]:
        data = self.client.get_json(
            f"{BASE_URL}/ajax/user/{user_id}/profile/all",
            params={"lang": "zh"},
        )
        if not data or data.get("error"):
            return []
        body = data.get("body", {})
        work_urls = []
        for pid in body.get("illusts", {}):
            work_urls.append(self._build_work_url(pid, "illust"))
        for pid in body.get("manga", {}):
            work_urls.append(self._build_work_url(pid, "illust"))
        for nid in body.get("novels", {}):
            work_urls.append(self._build_work_url(nid, "novel"))
        return work_urls

    def get_user_name(self, user_id: str) -> Optional[str]:
        url = f"{BASE_URL}/ajax/user/{user_id}"
        data = self.client.get_json(url, params={"full": "1", "lang": "zh"})
        if not data or data.get("error"):
            return None
        body = data.get("body", {})
        name = body.get("name") or body.get("userName") or body.get("user_name")
        return name.strip() if isinstance(name, str) and name.strip() else None


class PixivSeriesExtractor(PixivBaseExtractor):
    subcategory = "series"
    child = PixivWorkExtractor

    def items(self, url: str) -> Generator[ExtractMessage, None, None]:
        sid = self._extract_sid(url)
        if not sid:
            yield ExtractMessage.error_msg(url, "系列ID解析失败")
            return

        works = self._get_series_works(sid)
        for work_url in works:
            yield ExtractMessage.url_msg(work_url, parent=url)

    def _extract_sid(self, url: str) -> str:
        m = re.search(r"/series/(\d+)", url)
        return m.group(1) if m else ""

    def _get_series_works(self, series_id: str) -> list[str]:
        works = []
        page = 1
        while True:
            data = self.client.get_json(
                f"{BASE_URL}/ajax/series/{series_id}",
                params={"p": page, "limit": 30, "lang": "zh"},
            )
            if not data or data.get("error"):
                break
            body = data.get("body", {})
            page_works = body.get("work", [])
            if not page_works:
                break
            for w in page_works:
                if "id" in w:
                    works.append(self._build_work_url(w['id'], "illust"))
            if len(page_works) < 30:
                break
            page += 1
        return works


class PixivNovelSeriesExtractor(PixivBaseExtractor):
    subcategory = "novel-series"

    def _get_series_work_urls(self, sid: str) -> list[str]:
        data = self.client.get_json(
            f"{BASE_URL}/ajax/novel/series/{sid}/content_titles", timeout=15)
        if not data or data.get("error"):
            return []
        body = data.get("body", [])
        return [f"{BASE_URL}/novel/show.php?id={item['id']}"
                for item in body if "id" in item]

    def items(self, url: str) -> Generator[ExtractMessage, None, None]:
        m = re.search(r"/novel/series/(\d+)", url)
        if not m:
            yield ExtractMessage.error_msg(url, "系列ID解析失败")
            return
        sid = m.group(1)

        series_info = self.client.get_json(f"{BASE_URL}/ajax/novel/series/{sid}", timeout=20)
        if not series_info or series_info.get("error"):
            yield ExtractMessage.error_msg(url, "系列信息接口错误（网络异常或作品不存在）")
            return

        series_body = series_info.get("body", {}) if isinstance(series_info, dict) else {}
        series_title = normalize_series_name(
            series_body.get("title") or series_body.get("seriesTitle") or f"series_{sid}"
        )
        author = series_body.get("userName") or series_body.get("user_name") or ""
        description = description_to_text(
            series_body.get("description") or series_body.get("caption") or ""
        )
        pub_date = series_body.get("updateDate") or series_body.get("lastUpdated") or ""

        yield ExtractMessage.metadata_msg(url, {
            "type": "novel_series", "id": sid, "title": series_title, "author": author,
            "description": description, "date": pub_date,
        })

        cover_url = series_body.get("coverUrl") or series_body.get("coverURL") or series_body.get("cover_url")
        cover_bytes = None
        cover_ext = None
        cover_mime = None
        if cover_url:
            cover_bytes, cover_ext, cover_mime = self.client.download_binary(cover_url, timeout=20, image_limit=True)

        titles_info = self.client.get_json(
            f"{BASE_URL}/ajax/novel/series/{sid}/content_titles", timeout=20
        )
        if not titles_info or titles_info.get("error"):
            yield ExtractMessage.error_msg(url, "系列章节接口错误（网络异常或 Cookie 失效）")
            return

        items = titles_info.get("body", []) if isinstance(titles_info, dict) else []
        if not items:
            yield ExtractMessage.error_msg(url, "系列章节为空")
            return

        chapters = []
        inline_images = []
        for idx, item in enumerate(items, start=1):
            nid = item.get("id")
            if not nid:
                continue
            data = self.client.get_json(f"{BASE_URL}/ajax/novel/{nid}", timeout=20)
            if not data or data.get("error"):
                continue
            body = data.get("body", {}) if isinstance(data, dict) else {}

            if cover_bytes is None:
                fallback_cover = self._extract_novel_cover_url(body, str(nid))
                if not fallback_cover:
                    imgs = extract_novel_images(body)
                    if imgs:
                        fallback_cover = next(iter(imgs.values()))
                if fallback_cover:
                    cover_bytes, cover_ext, cover_mime = self.client.download_binary(
                        fallback_cover, timeout=20, image_limit=True)

            text = self._extract_novel_text(body, str(nid))
            ch_description = description_to_text(body.get("description") or body.get("caption") or "")
            if not text:
                text = ch_description
            if not _text_has_content(text, ch_description):
                continue
            text, markup_items = convert_novel_markup(text, f"mk{idx}_")
            inline_images.extend(markup_items)
            ch_title = item.get("title") or body.get("title") or f"第{idx}话"
            serial = item.get("serial")
            if serial and serial not in str(ch_title):
                ch_title = f"{serial} {ch_title}"
            text, ch_images = build_inline_images(
                text, body, f"{idx}_", self.client.download_binary, self.client._stop_event
            )
            inline_images.extend(ch_images)
            chapters.append({"title": ch_title, "text": text})

        if not chapters:
            yield ExtractMessage.error_msg(url, "系列章节下载失败（所有章节正文不完整或无法获取）")
            return

        out = _unique_path(self._download_dir(), series_title, ".epub")
        meta = {"title": series_title, "author": author, "description": description,
                "tags": extract_tags(series_body), "date": pub_date}
        if write_novel_epub("", meta, sid, out, cover_bytes, cover_ext, cover_mime, inline_images, chapters):
            yield ExtractMessage.file_msg(url, out, {
                "type": "novel_series", "id": sid, "title": series_title, "author": author,
            })
        else:
            yield ExtractMessage.error_msg(url, "EPUB生成失败")

    def _download_dir(self) -> Path:
        return getattr(self, "_save_dir", None) or Path("downloads")


class PixivSearchExtractor(PixivBaseExtractor):
    subcategory = "search"
    child = PixivWorkExtractor

    def items(self, keyword: str, page: int = 1, content_type: str = "illust",
              max_pages: int = 10) -> Generator[ExtractMessage, None, None]:
        results = self._search(keyword, page, max_pages, content_type)
        for item in results:
            pid = item.get("id", "")
            if not pid:
                continue
            yield ExtractMessage.url_msg(self._build_work_url(pid, item.get("type", "illust")))

    def _search(self, keyword: str, page: int, max_pages: int, content_type: str) -> list[dict]:
        import requests as _requests
        is_novel = content_type == "novel"
        api_path = "novels" if is_novel else "illustrations"
        params = {"word": keyword, "order": "date_d", "mode": "all",
                  "s_mode": "s_tag", "lang": "zh"}
        if is_novel:
            params["gs"] = 0

        all_items = []
        encoded = _requests.utils.quote(keyword)
        for p in range(page, page + max_pages):
            params["p"] = p
            data = self.client.get_json(f"{BASE_URL}/ajax/search/{api_path}/{encoded}", params=params)
            if not data or data.get("error"):
                break
            body = data.get("body", {})
            if is_novel:
                items = body.get("novel", {}).get("data", [])
            else:
                items = body.get("illust", {}).get("data", []) + body.get("manga", {}).get("data", [])
                content_type = "illust"
            if not items:
                break
            all_items.extend([{"id": str(it.get("id", "")), "type": content_type, **it} for it in items])
        return all_items


class PixivRankingExtractor(PixivBaseExtractor):
    subcategory = "ranking"
    child = PixivWorkExtractor

    def items(self, mode: str = "daily", content_type: str = "illust", page: int = 1
              ) -> Generator[ExtractMessage, None, None]:
        results = self._ranking(mode, content_type, page)
        for item in results:
            pid = item.get("id", "")
            if not pid:
                continue
            yield ExtractMessage.url_msg(self._build_work_url(pid, content_type))

    def _ranking(self, mode: str, content_type: str, page: int) -> list[dict]:
        if content_type == "novel":
            url = f"{BASE_URL}/ranking.php?mode={mode}&format=json&content=novel&p={page}"
        else:
            url = f"{BASE_URL}/ranking.php?mode={mode}&format=json&p={page}"
        data = self.client.get_json(url)
        if not data:
            return []
        contents = data.get("contents", [])
        return [
            {"id": str(item.get("illust_id", "")), "title": item.get("title", ""),
             "author": item.get("user_name", ""), "author_id": str(item.get("user_id", "")),
             "url": item.get("url", ""), "type": content_type}
            for item in contents
        ]
