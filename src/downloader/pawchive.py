"""Pawchive 下载器 — Pixiv Fanbox 归档站（kemono 类）。

站点 pawchive.pw 归档 Pixiv Fanbox 作者的作品：
- 作者页：/fanbox/user/{uid}（分页 ?o=0/50/100，每页 50 个 post 卡片）
- post 页：/fanbox/user/{uid}/post/{post_id}（附件下载 + 正文）
- 附件直链：https://file.pawchive.pw/data/{hash}.{ext}?f={文件名}

一个作者 URL 展开为多个 post，每个 post 的附件下载入库。
元数据映射：作者 = 作者名，标题 = post 标题，类型 = 附件扩展名。
"""
from __future__ import annotations

import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import quote, unquote, urlparse

import requests

from src.downloader.base import BaseDownloader
from src.downloader.context import PipelineResult
from src.core.logging import get_logger

logger = get_logger("akm.pawchive")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

#: 每页 post 数量（作者页分页）
_PAGE_SIZE = 50


class PawchiveDownloader(BaseDownloader):
    name = "pawchive"
    url_patterns = [r"pawchive\.pw"]
    supports_expand = True

    def __init__(self):
        super().__init__()
        self._load_base_config()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _UA})
        cookie = self._load_cookie()
        if cookie:
            self.session.headers.update({"Cookie": cookie})
        self._load_existing_sources()
        self.max_workers = self._load_workers()
        self._zip_passwords = self._load_zip_passwords()
        self._gdrive_authors = self._load_gdrive_authors()

    def _load_cookie(self) -> str:
        """读登录 Cookie：环境变量 AKM_PAWCHIVE_COOKIE > config.json pawchive.cookie。"""
        import os
        env = os.environ.get("AKM_PAWCHIVE_COOKIE", "")
        if env:
            return env
        try:
            from src.core.config import load_config
            cfg = load_config()
            return (cfg.get("pawchive") or {}).get("cookie", "")
        except Exception:
            return ""

    def _load_workers(self) -> int:
        """读并发数：pawchive.workers > download.max_workers > 默认 3。"""
        try:
            from src.core.config import load_config
            cfg = load_config()
            w = (cfg.get("pawchive") or {}).get("workers")
            if w is None:
                w = (cfg.get("download") or {}).get("max_workers")
            if w is None:
                w = 3
            return max(1, int(w))
        except Exception:
            return 3

    def _load_zip_passwords(self) -> dict[str, str]:
        """读 zip 解压密码：config.json 的 pawchive.zip_passwords。

        按作者 uid 映射：{"12134097": "bqj111"}。命中作者的 zip 附件会
        尝试解压合并为 PDF 入库。
        """
        try:
            from src.core.config import load_config
            cfg = load_config()
            pw = (cfg.get("pawchive") or {}).get("zip_passwords") or {}
            return pw if isinstance(pw, dict) else {}
        except Exception:
            return {}

    def _load_gdrive_authors(self) -> set[str]:
        """读允许 Google Drive 下载的作者 uid 白名单。

        config.json 的 pawchive.gdrive_authors（数组），只有这些作者的
        post 才会从正文提取 Google Drive 链接下载；其余作者不尝试。
        """
        try:
            from src.core.config import load_config
            cfg = load_config()
            authors = (cfg.get("pawchive") or {}).get("gdrive_authors") or []
            if isinstance(authors, (list, tuple, set)):
                return {str(a) for a in authors}
            return set()
        except Exception:
            return set()

    # ── 抽象方法 ─────────────────────────────────────────

    def process_url(self, urls: Union[str, List[str]],
                    mode: str = "both") -> Dict[str, int]:
        """并发下载 post URL 的附件（每个附件一个作品）。"""
        if isinstance(urls, str):
            urls = [urls]
        stats = {"success": 0, "failed": 0, "skipped": 0}
        if not urls:
            return stats

        from src.core.progress import make_progress, advance
        if self._progress is not None:
            progress, main_task, counts_task = self._progress
            counts = self._progress_counts or {"success": 0, "failed": 0,
                                               "skipped": 0}
            own_progress = False
        else:
            counts = {"success": 0, "failed": 0, "skipped": 0}
            progress, main_task, counts_task = make_progress(
                counts, "下载 Fanbox", total=len(urls))
            own_progress = True
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
        if own_progress:
            progress.start()
        try:
            futures = {pool.submit(self._download_one, u): u for u in urls}
            for f in as_completed(futures):
                self._check_stop()
                try:
                    result = f.result()
                    status = (result.status
                              if isinstance(result, PipelineResult)
                              else "failed")
                except Exception:
                    status = "failed"
                counts[status] = counts.get(status, 0) + 1
                advance(progress, main_task, counts_task)
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            if own_progress:
                progress.stop()
            pool.shutdown(wait=False, cancel_futures=True)
        stats.update(counts)
        return stats

    def get_author_info(self, url: str) -> Optional[tuple[str, int]]:
        """返回 (作者名, post 数)。"""
        uid = self._extract_uid(url)
        if not uid:
            return None
        service = self._extract_service(url)
        try:
            posts = self._list_posts(uid, service)
            name = self._author_name(url)
            return name, len(posts)
        except Exception:
            name = self._author_name(url)
            return name, 0

    def extract_uid(self, url: str) -> str:
        return self._extract_uid(url) or ""

    def get_user_works(self, url: str) -> List[str]:
        """返回作者（post）列表的稳定 URL（供 follow 入队）。"""
        uid = self._extract_uid(url)
        if not uid:
            return []
        service = self._extract_service(url)
        try:
            posts = self._list_posts(uid, service)
        except Exception as e:
            logger.error("列出作者 post 失败: %s - %s", url, e)
            return []
        host = self._host_of(url)
        return [f"{host}/{service}/user/{uid}/post/{p['post_id']}"
                for p in posts]

    # ── 收藏 ─────────────────────────────────────────────

    def list_favorites(self) -> List[dict]:
        """返回账号收藏的作品列表（/favorites?type=post）。

        每项含 id/title/service/user_id/url/date/attachments。
        service: fanbox / patreon（两者均可下载）。
        """
        host = self._host_of("https://pawchive.pw/")
        html = self._get(f"{host}/favorites?type=post")
        if not html:
            return []
        favorites: List[dict] = []
        for m in re.finditer(
                r'<article[^>]*post-card[^>]*data-id="(\d+)"[^>]*'
                r'data-service="([^"]*)"[^>]*data-user="([^"]*)"[^>]*>'
                r'(.*?)</article>', html, re.S):
            post_id = m.group(1)
            service = m.group(2)
            user_id = m.group(3)
            body = m.group(4)
            href_m = re.search(r'href="([^"]+)"', body)
            href = href_m.group(1) if href_m else ""
            title_m = re.search(
                r'post-card__header[^>]*>\s*([^<]+?)\s*<', body)
            title = title_m.group(1).strip() if title_m else ""
            date_m = re.search(r'datetime="([^"]+)"', body)
            date = date_m.group(1) if date_m else ""
            att_m = re.search(r'(\d+)\s*attachment', body)
            attachments = int(att_m.group(1)) if att_m else 0
            favorites.append({
                "id": post_id,
                "title": title,
                "service": service,
                "user_id": user_id,
                "url": host + href if href.startswith("/") else href,
                "date": date,
                "attachments": attachments,
            })
        return favorites

    def list_favorite_creators(self) -> List[dict]:
        """返回账号收藏的作者列表（/favorites?type=artist）。

        每项含 service/name/uid/url/date。
        """
        host = self._host_of("https://pawchive.pw/")
        html = self._get(f"{host}/favorites?type=artist")
        if not html:
            return []
        creators: List[dict] = []
        for m in re.finditer(
                r'<a[^>]*href="([^"]+)"[^>]*class="user-card[^"]*"[^>]*'
                r'data-id="(\d+)"[^>]*data-service="([^"]*)"[^>]*>'
                r'(.*?)</a>', html, re.S):
            href = m.group(1)
            uid = m.group(2)
            service = m.group(3)
            body = m.group(4)
            svc_m = re.search(r'user-card__service[^>]*>\s*([^<]+?)\s*<', body)
            service_label = svc_m.group(1).strip() if svc_m else service
            name_m = re.search(r'user-card__name">\s*([^<]+?)\s*<', body)
            name = name_m.group(1).strip() if name_m else ""
            date_m = re.search(r'datetime="([^"]+)"', body)
            date = date_m.group(1) if date_m else ""
            creators.append({
                "service": service_label,
                "name": name,
                "uid": uid,
                "url": host + href if href.startswith("/") else href,
                "date": date,
            })
        return creators

    def get_favorite_works(self) -> List[str]:
        """返回收藏作品的稳定 URL（供下载，fanbox / patreon 均可）。"""
        return [f["url"] for f in self.list_favorites() if f.get("url")]

    # ── 展开 ─────────────────────────────────────────────

    def expand_urls(self, urls: List[str]) -> List[str]:
        """作者 URL / post URL → post URL 列表。

        - post URL（/fanbox|patreon/user/{uid}/post/{id}）：保持不变
        - 作者 URL（/fanbox|patreon/user/{uid}）：分页列出全部 post
        """
        if not urls:
            return []
        host = self._host_of(urls[0])
        result: List[str] = []
        for u in urls:
            if "/post/" in u:
                result.append(u)
                continue
            uid = self._extract_uid(u)
            if not uid:
                continue
            service = self._extract_service(u)
            try:
                posts = self._list_posts(uid, service)
            except Exception as e:
                logger.warning("列出作者 post 失败: %s - %s", u, e)
                continue
            for p in posts:
                result.append(f"{host}/{service}/user/{uid}/post/{p['post_id']}")
        return list(dict.fromkeys(result))

    # ── 内部方法 ─────────────────────────────────────────

    def _download_one(self, post_url: str) -> PipelineResult:
        """下载单个 post 的所有附件并入库。"""
        source = post_url.strip()
        # 入库 source 是 {post_url}?f={filename}（带附件参数），去重键是
        # post URL，需用前缀匹配判断「该 post 是否已有任一附件入库」。
        if any(s.startswith(source) for s in self.existing_sources):
            return PipelineResult.skipped(source, "已存在")

        html = self._get(post_url)
        if not html:
            return PipelineResult.failed(source, "获取 post 页失败")

        title = self._post_title(html) or self._post_id_of(post_url)
        author = self._post_author(html)
        uid = self._extract_uid(post_url)
        attachments = self._parse_attachments(html)

        if not attachments:
            # 仅白名单作者（gdrive_authors）的 post 尝试从正文提取 Google
            # Drive 链接 + 密码，下载解压入库；其余作者不碰。
            if uid in self._gdrive_authors:
                gdrives = self._parse_gdrive(html)
                if gdrives:
                    return self._download_gdrive_post(
                        source, title, author, gdrives)
            return PipelineResult.failed(source, "无附件")

        # 每个附件独立入库
        results = []
        for i, att in enumerate(attachments):
            att_title = Path(att["filename"]).stem  # 去扩展名，避免双后缀
            if len(attachments) > 1:
                final_title = f"{title} - {att_title}" if title else att_title
            else:
                # 单附件优先用 post 标题（更完整，含页数/章节信息），
                # post 标题缺失时才回退到附件名
                final_title = title or att_title
            r = self._download_attachment(att, source, final_title, author, uid)
            results.append(r)
        if any(r.status == "success" for r in results):
            return PipelineResult.success(source)
        if all(r.status == "skipped" for r in results):
            return PipelineResult.skipped(source, "已存在")
        return results[0] if results else PipelineResult.failed(source, "无附件")

    def _download_attachment(self, att: dict, source: str,
                             title: str, author: str,
                             uid: str = "") -> PipelineResult:
        """下载单个附件并入库。

        zip 附件且作者配置了解压密码时，走「解压 → 图片合并 PDF」入库；
        解压失败自动回退为直接入库 zip。
        """
        url = att["url"]
        filename = att["filename"]
        ext = Path(filename).suffix.lower() or Path(urlparse(url).path).suffix.lower()

        password = self._zip_passwords.get(uid) if uid else None
        if ext == ".zip" and password:
            result = self._download_zip_as_pdf(
                att, source, title, author, password)
            if result is not None:
                return result
            logger.warning("zip 解压合并 PDF 失败，回退为直接入库 zip: %s",
                           filename)

        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "未命名"
        tmp_dir = Path(tempfile.mkdtemp())
        tmp = tmp_dir / f"{safe_title}{ext}"
        try:
            self._download(url, tmp)
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return PipelineResult.failed(f"{source}?f={filename}", str(e))

        result = self.import_download(tmp, f"{source}?f={filename}", {
            "title": title,
            "author": author or "佚名",
            "series": "",
            "tags": ["Fanbox", "Pixiv Fanbox"],
            "source_status": "ok",
        })
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if result[1] == "ok":
            return PipelineResult.success(f"{source}?f={filename}")
        return PipelineResult.failed(f"{source}?f={filename}", result[1])

    def _download_zip_as_pdf(self, att: dict, source: str, title: str,
                             author: str, password: str) -> Optional[PipelineResult]:
        """下载 zip 附件，解压（AES 加密）后把图片合并为 PDF 入库。

        成功返回 PipelineResult；任一步失败返回 None（由调用方回退）。
        """
        import pyzipper
        from src.core.image_converter import convert_images_to_book

        url = att["url"]
        filename = att["filename"]
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "未命名"
        tmp_dir = Path(tempfile.mkdtemp())
        zip_path = tmp_dir / f"{safe_title}.zip"
        # 解压目录用标题命名，convert_images_to_book 输出的 PDF 即以标题
        # 命名（build_import_target 用临时文件名当最终文件名，避免 extract.pdf）
        extract_dir = tmp_dir / safe_title
        try:
            self._download(url, zip_path)
            extract_dir.mkdir(parents=True, exist_ok=True)

            with pyzipper.AESZipFile(str(zip_path)) as zf:
                zf.setpassword(password.encode("utf-8"))
                zf.extractall(str(extract_dir))

            # 解压后：优先直接用已存在的 PDF（作者直接打包 PDF 的场景，
            # 如诡异服装店6），否则把图片合并为 PDF
            existing_pdfs = sorted(extract_dir.rglob("*.pdf"))
            if existing_pdfs:
                pdf_path = existing_pdfs[0]
                # zip 内文件名可能是 GBK 乱码（如 ╖■╫░╡Ω6(1).pdf），
                # 重命名为标题命名的干净文件名，避免入库文件名乱码
                clean_pdf = extract_dir / f"{safe_title}.pdf"
                if pdf_path.name != clean_pdf.name:
                    shutil.move(str(pdf_path), str(clean_pdf))
                pdf_path = clean_pdf
            else:
                pdf_path = convert_images_to_book(extract_dir, "pdf",
                                                  delete_original=False)
            result = self.import_download(pdf_path, f"{source}?f={filename}", {
                "title": title,
                "author": author or "佚名",
                "series": "",
                "tags": ["Fanbox", "Pixiv Fanbox"],
                "source_status": "ok",
            })
            if result[1] == "ok":
                return PipelineResult.success(f"{source}?f={filename}")
            return PipelineResult.failed(f"{source}?f={filename}", result[1])
        except Exception as e:
            logger.debug("zip 解压合并失败: %s - %s", filename, e)
            return None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Google Drive 下载（Patreon post 正文里的外链）─────

    def _parse_gdrive(self, html: str) -> List[dict]:
        """从正文提取 Google Drive 链接 + 解压密码。

        返回 [{file_id, password}]。密码取自正文 `pw：xxx`（按出现顺序
        与链接配对，若只有一个密码则应用到所有链接）。
        """
        file_ids = list(dict.fromkeys(
            re.findall(r'https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)',
                       html)))
        if not file_ids:
            return []
        passwords = re.findall(r'[pP][wW]\s*[：:]\s*([^\s<]+)', html)
        results = []
        for i, fid in enumerate(file_ids):
            pw = passwords[i] if i < len(passwords) else (
                passwords[0] if passwords else "")
            results.append({"file_id": fid, "password": pw})
        return results

    def _download_gdrive_post(self, source: str, title: str, author: str,
                              gdrives: List[dict]) -> PipelineResult:
        """下载 Google Drive 文件，解压（rar/zip）并入库。"""
        tmp_dir = Path(tempfile.mkdtemp())
        all_results: List[PipelineResult] = []
        try:
            for g in gdrives:
                file_id = g["file_id"]
                password = g.get("password", "")
                # 正文未提取到密码时，回退到 config zip_passwords 按作者 uid 兜底
                if not password:
                    uid = self._extract_uid(source)
                    password = self._load_zip_passwords().get(uid, "")
                gsource = f"{source}?gdrive={file_id}"
                try:
                    archive = self._download_gdrive(file_id, tmp_dir)
                except Exception as e:
                    all_results.append(PipelineResult.failed(
                        gsource, f"Google Drive 下载失败: {e}"))
                    continue

                ext = archive.suffix.lower()
                if ext in (".rar", ".zip", ".7z"):
                    extract_dir = tmp_dir / f"extract_{file_id}"
                    extract_dir.mkdir(exist_ok=True)
                    try:
                        self._extract_archive(archive, password, extract_dir)
                    except Exception as e:
                        logger.warning("解压失败，直接入库原文件: %s - %s",
                                       archive.name, e)
                        all_results.append(self._import_file(
                            archive, gsource, title, author))
                        continue
                    all_results.extend(self._import_extracted(
                        extract_dir, source, title, author))
                else:
                    # 非压缩包（pdf/图片等）直接入库
                    all_results.append(self._import_file(
                        archive, gsource, title, author))

            if any(r.status == "success" for r in all_results):
                return PipelineResult.success(source)
            if all_results and all(r.status == "skipped" for r in all_results):
                return PipelineResult.skipped(source, "已存在")
            return (all_results[0] if all_results
                    else PipelineResult.failed(source, "Google Drive 无文件"))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _download_gdrive(self, file_id: str, dest_dir: Path) -> Path:
        """下载 Google Drive 文件（处理大文件的 confirm token），返回路径。"""
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        r = self.session.get(url, timeout=30, allow_redirects=True)
        r.raise_for_status()
        html = r.text

        if "download-form" in html or "Virus scan warning" in html:
            confirm_m = re.search(r'name="confirm" value="([^"]*)"', html)
            uuid_m = re.search(r'name="uuid" value="([^"]*)"', html)
            name_m = re.search(r'uc-name-size"><a[^>]*>([^<]+)</a>', html)
            if not confirm_m:
                raise RuntimeError("无法解析 Google Drive confirm 页")
            confirm = confirm_m.group(1)
            uuid = uuid_m.group(1) if uuid_m else ""
            filename = name_m.group(1) if name_m else f"{file_id}.bin"
            dl_url = (f"https://drive.usercontent.google.com/download?"
                      f"id={file_id}&export=download&confirm={confirm}")
            if uuid:
                dl_url += f"&uuid={uuid}"
            r2 = self.session.get(dl_url, stream=True, timeout=120)
            r2.raise_for_status()
        else:
            filename = f"{file_id}.bin"
            cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m:
                filename = m.group(1)
            r2 = r

        dest = Path(dest_dir) / filename
        with open(dest, "wb") as f:
            for chunk in r2.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
        return dest

    def _extract_archive(self, archive_path: Path, password: str,
                         dest_dir: Path) -> None:
        """用 unar 解压 rar/zip（支持 RAR5 与密码）。失败抛 RuntimeError。"""
        import subprocess
        cmd = ["unar"]
        if password:
            cmd += ["-p", password]
        cmd += ["-o", str(dest_dir), str(archive_path)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            raise RuntimeError(f"unar 解压失败: {res.stderr.strip()[-200:]}")

    def _import_extracted(self, extract_dir: Path, source: str, title: str,
                          author: str) -> List[PipelineResult]:
        """入库解压目录里的文件：多图合并 PDF，其余逐个入库。"""
        from src.core.image_converter import convert_images_to_book
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        files = [p for p in extract_dir.rglob("*")
                 if p.is_file() and not p.name.startswith(".")]
        if not files:
            return []
        images = [f for f in files if f.suffix.lower() in image_exts]
        others = [f for f in files if f.suffix.lower() not in image_exts]

        results: List[PipelineResult] = []
        # 多图合并 PDF（仅当图片都在同一目录）
        if len(images) >= 2 and len({f.parent for f in images}) == 1:
            try:
                pdf = convert_images_to_book(images[0].parent, "pdf",
                                             delete_original=False)
                results.append(self._import_file(pdf, source, title, author))
                images = []
            except Exception as e:
                logger.warning("图片合并 PDF 失败，改为逐个入库: %s", e)
        for f in images:
            results.append(self._import_file(f, source, f.stem or title, author))
        # 非图片（pdf 等）：单个文件用 post 标题，多个加文件名区分
        for f in others:
            f_title = title if len(others) == 1 else (f.stem or title)
            results.append(self._import_file(f, source, f_title, author))
        return results

    def _import_file(self, file: Path, source: str, title: str,
                     author: str) -> PipelineResult:
        """单个文件入库（通用）。"""
        result = self.import_download(file, f"{source}?f={file.name}", {
            "title": title,
            "author": author or "佚名",
            "series": "",
            "tags": ["Fanbox", "Pixiv Fanbox"],
            "source_status": "ok",
        })
        if result[1] == "ok":
            return PipelineResult.success(f"{source}?f={file.name}")
        return PipelineResult.failed(f"{source}?f={file.name}", result[1])

    def _download(self, url: str, dest: Path) -> None:
        """流式下载附件到 dest。"""
        with self.session.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)

    def _get(self, url: str) -> Optional[str]:
        """GET 页面 HTML。"""
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.debug("请求失败: %s - %s", url, e)
            return None

    def _list_posts(self, uid: str, service: str = "fanbox") -> List[dict]:
        """分页列出作者全部 post，返回 [{post_id, title, date}]。"""
        host = self._host_of("https://pawchive.pw/")
        posts: List[dict] = []
        offset = 0
        while True:
            html = self._get(f"{host}/{service}/user/{uid}?o={offset}")
            if not html:
                break
            page_posts = self._parse_post_cards(html)
            if not page_posts:
                break
            posts.extend(page_posts)
            if len(page_posts) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        # 去重（按 post_id）
        seen = set()
        unique = []
        for p in posts:
            if p["post_id"] not in seen:
                seen.add(p["post_id"])
                unique.append(p)
        return unique

    def _parse_post_cards(self, html: str) -> List[dict]:
        """解析作者页 post 卡片列表。"""
        cards = []
        for m in re.finditer(
                r'<article[^>]*data-id="(\d+)"[^>]*>(.*?)</article>', html, re.S):
            post_id = m.group(1)
            body = m.group(2)
            title_m = re.search(
                r'post-card__header[^>]*>\s*([^<]+?)\s*<', body)
            title = title_m.group(1).strip() if title_m else ""
            date_m = re.search(r'datetime="([^"]+)"', body)
            date = date_m.group(1) if date_m else ""
            cards.append({"post_id": post_id, "title": title, "date": date})
        return cards

    def _parse_attachments(self, html: str) -> List[dict]:
        """解析 post 页附件下载链接，返回 [{url, filename}]。"""
        attachments = []
        for m in re.finditer(
                r'<a[^>]*post__attachment-link[^>]*href="([^"]+)"[^>]*'
                r'(?:download="([^"]*)")?[^>]*>', html):
            url = m.group(1)
            filename = unquote(m.group(2) or "")
            if not filename:
                qm = re.search(r"[?&]f=([^&]+)", url)
                if qm:
                    filename = unquote(qm.group(1))
            if not filename:
                filename = Path(urlparse(url).path).name
            attachments.append({"url": url, "filename": filename})
        return attachments

    def _post_title(self, html: str) -> str:
        """从 post 页提取标题（JSON-LD headline 优先，含 unicode 转义解码）。"""
        m = re.search(r'"headline":\s*"([^"]*)"', html)
        if m:
            try:
                import json as _json
                return _json.loads(f'"{m.group(1)}"')
            except Exception:
                return m.group(1)
        m = re.search(r'class="post__title"[^>]*>\s*([^<]+?)\s*<', html)
        if m:
            return m.group(1).strip()
        return ""

    def _post_author(self, html: str) -> str:
        """从 post 页提取作者名。

        HTML 内嵌 JSON 中的中文名是 \\uXXXX 转义形式（如 \\u5c0f\\u6797...），
        正则提取的是转义字面量，需解码为真实字符再返回。
        """
        m = re.search(r'"author":\s*{[^}]*"name":\s*"([^"]*)"', html)
        if m:
            name = m.group(1)
            # 只解码 JSON unicode 转义（\\u5c0f → 小），不动 \n 等其他转义
            return re.sub(r'\\u[0-9a-fA-F]{4}',
                          lambda mm: chr(int(mm.group(0)[2:], 16)), name)
        return ""

    def _author_name(self, url: str) -> str:
        """从作者页 title 提取作者名（'Posts of {name} from ...'）。"""
        html = self._get(url)
        if not html:
            return self._extract_uid(url) or "佚名"
        m = re.search(r"<title>Posts of ([^<]+) from", html)
        if m:
            return m.group(1).strip()
        return self._extract_uid(url) or "佚名"

    # ── URL 解析 ─────────────────────────────────────────

    @staticmethod
    def _host_of(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    @staticmethod
    def _extract_uid(url: str) -> str:
        """作者 URL / post URL → uid（兼容 fanbox 与 patreon）。"""
        m = re.search(r"/(?:fanbox|patreon)/user/(\d+)", url)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_service(url: str) -> str:
        """URL → service（fanbox/patreon），默认 fanbox。"""
        if "/patreon/" in url:
            return "patreon"
        return "fanbox"

    @staticmethod
    def _post_id_of(url: str) -> str:
        m = re.search(r"/post/(\d+)", url)
        return m.group(1) if m else ""
