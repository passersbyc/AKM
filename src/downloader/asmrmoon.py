"""ASMR Moon 下载器 — 基于 AList V3 协议的音声资源站。

站点 asmrmoon.com 由 AList 搭建，提供标准 API：
- 列目录：POST /api/fs/list  {path, password, page, per_page, refresh}
- 下载文件：GET /d{path}?sign={sign}   （支持 Range，音频直链）

一个目录 URL（如 /中文音声/烛灵儿）展开为多个音频文件作品。
元数据映射：作者 = 目录名，系列 = 父目录名，标题 = 文件名去扩展名。
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

logger = get_logger("akm.asmrmoon")

#: 可下载的音频扩展名
_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"}

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")


class AsmrMoonDownloader(BaseDownloader):
    name = "asmrmoon"
    url_patterns = [r"asmrmoon\.com"]
    supports_expand = True

    def __init__(self):
        super().__init__()
        self._load_base_config()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _UA})
        cookie = self._load_cookie()
        if cookie:
            self.session.headers.update({"Cookie": cookie})
        # asmrmoon 的登录态是 localStorage 里的 token，以 Authorization 头
        # 发送（见前端 JS: localStorage.getItem("token") → Authorization），
        # 不是 Cookie。配置 token 后才有会员权限 / 收藏等登录能力。
        token = self._load_token()
        if token:
            self.session.headers.update({"Authorization": token})
        self._load_existing_sources()
        self.max_workers = self._load_workers()

    def _load_cookie(self) -> str:
        """读登录 Cookie：环境变量 AKM_ASMRMOON_COOKIE > config.json asmrmoon.cookie。

        仅供 Cloudflare 反爬通过等场景；会员/收藏权限靠 token（见 _load_token）。
        """
        import os
        env = os.environ.get("AKM_ASMRMOON_COOKIE", "")
        if env:
            return env
        try:
            from src.core.config import load_config
            cfg = load_config()
            return (cfg.get("asmrmoon") or {}).get("cookie", "")
        except Exception:
            return ""

    def _load_token(self) -> str:
        """读登录 token：环境变量 AKM_ASMRMOON_TOKEN > config.json asmrmoon.token。

        该 token 是站点登录后存在 localStorage["token"] 里的值，随请求以
        Authorization 头携带。配置后解锁会员文件与收藏列表。
        """
        import os
        env = os.environ.get("AKM_ASMRMOON_TOKEN", "")
        if env:
            return env
        try:
            from src.core.config import load_config
            cfg = load_config()
            return (cfg.get("asmrmoon") or {}).get("token", "")
        except Exception:
            return ""

    def _load_workers(self) -> int:
        """读并发数，优先级：asmrmoon.workers > download.max_workers > 默认 3。"""
        try:
            from src.core.config import load_config
            cfg = load_config()
            w = (cfg.get("asmrmoon") or {}).get("workers")
            if w is None:
                w = (cfg.get("download") or {}).get("max_workers")
            if w is None:
                w = 3
            return max(1, int(w))
        except Exception:
            return 3

    # ── 抽象方法 ─────────────────────────────────────────

    def process_url(self, urls: Union[str, List[str]],
                    mode: str = "both") -> Dict[str, int]:
        """并发下载展开后的文件 URL（每个音频文件一个作品）。"""
        if isinstance(urls, str):
            urls = [urls]
        stats = {"success": 0, "failed": 0, "skipped": 0}
        if not urls:
            return stats

        from src.core.progress import make_progress, advance
        counts = {"success": 0, "failed": 0, "skipped": 0}
        progress, main_task, counts_task = make_progress(
            counts, "下载音声", total=len(urls))
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
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
            progress.stop()
            pool.shutdown(wait=False, cancel_futures=True)
        stats.update(counts)
        return stats

    def get_author_info(self, url: str) -> Optional[tuple[str, int]]:
        path = self._extract_path(url)
        if not path:
            return None
        try:
            files = self._list_files(url, path)
            return Path(path).name or path, len(files)
        except Exception:
            return Path(path).name or path, 0

    def extract_uid(self, url: str) -> str:
        return self._extract_path(url) or ""

    def get_user_works(self, url: str, exts: Optional[set] = None,
                       max_size_mb: Optional[float] = None) -> List[str]:
        """返回作者（目录）下所有可下载音频文件的稳定 URL（不带 sign）。

        无 sign 的文件 = 会员专属/无权限（如 insufficient membership tier），
        列表 API 不返回 sign，直接跳过不入队。
        exts: 只保留这些扩展名（如 {".mp3", ".flac"}），None = 不过滤。
        max_size_mb: 跳过超过该大小（MB）的文件，None = 不过滤。
        """
        path = self._extract_path(url)
        if not path:
            return []
        try:
            files = self._list_files(url, path)
        except Exception as e:
            logger.error("列出目录失败: %s - %s", url, e)
            return []
        host = self._host_of(url)
        result = []
        for f in files:
            name = f.get("name", "")
            ext = Path(name).suffix.lower()
            if ext not in _AUDIO_EXTS:
                continue
            if exts and ext not in exts:
                continue
            if not f.get("path"):
                continue
            if not f.get("sign"):
                logger.info("跳过无权限文件（会员专属）: %s", name)
                continue
            if max_size_mb and f.get("size", 0) > max_size_mb * 1024 * 1024:
                logger.info("跳过超大文件: %s (%.1f MB)", name,
                            f.get("size", 0) / 1024 / 1024)
                continue
            result.append(f"{host}{f['path']}")
        return result

    def get_favorite_works(self) -> List[str]:
        """返回收藏文件的稳定 URL（不带 sign），供标准下载管线展开。

        收藏列表响应虽含 sign，但 sign 会过期；这里返回稳定 URL，
        交给 expand_urls 按父目录重新列目录取最新 sign，更稳健。
        """
        host = self._host_of("https://asmrmoon.com/")
        result = []
        for f in self.list_favorites():
            path = f.get("path", "")
            if path and Path(path).suffix.lower() in _AUDIO_EXTS:
                result.append(f"{host}{path}")
        return result

    def list_favorites(self) -> List[dict]:
        """返回当前账号收藏的文件列表（需登录 token）。

        前端收藏接口：GET /api/favorite/list，响应 data.content 为收藏项，
        每项含 path/name/is_dir 等字段，与 fs/list 的文件项同构。
        未配置 token（访客）时后端返回 403 "You are a guest"。
        """
        host = self._host_of("https://asmrmoon.com/")
        resp = self.session.get(f"{host}/api/favorite/list", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"收藏列表获取失败: {data.get('message')}")
        d = data.get("data") or {}
        content = d.get("content") or d.get("items") or []
        return [c for c in content if not c.get("is_dir")]

    def list_favorite_authors(self) -> List[dict]:
        """返回当前账号收藏的作者列表（需登录 token）。

        前端接口：GET /api/favorite/authors，返回 [{author, category, count, thumb}]。
        未配置 token（访客）时返回 403 "You are a guest"。
        """
        host = self._host_of("https://asmrmoon.com/")
        resp = self.session.get(f"{host}/api/favorite/authors", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            return []
        d = data.get("data") or []
        return d if isinstance(d, list) else []

    def check_credentials(self) -> dict:
        """检查 cookie（Cloudflare 反爬）和 token（登录态）的状态。

        返回 {"cookie": {"status", "detail"}, "token": {"status", "detail"}}。
        status ∈ valid / expired / offline（offline = 网络不可达，不应据此判定失效）。
        """
        host = self._host_of("https://asmrmoon.com/")
        cookie = self._load_cookie()
        token = self._load_token()
        result = {
            "cookie": {"status": "offline", "detail": "未配置"},
            "token": {"status": "offline", "detail": "未配置"},
        }

        if token:
            result["token"] = self._check_token(host, token, cookie)
        if cookie:
            result["cookie"] = self._check_cookie(host, cookie)

        return result

    def _check_token(self, host: str, token: str,
                     cookie: str) -> dict:
        """验证登录 token：调收藏接口，code=200 有效，403 为访客。"""
        headers = {"User-Agent": _UA, "Authorization": token}
        if cookie:
            headers["Cookie"] = cookie
        try:
            r = requests.get(f"{host}/api/favorite/list", headers=headers,
                             timeout=15)
        except requests.exceptions.ConnectionError:
            return {"status": "offline", "detail": "网络不可达"}
        except requests.exceptions.Timeout:
            return {"status": "offline", "detail": "请求超时"}
        except Exception as e:
            return {"status": "offline", "detail": str(e)}

        if r.status_code != 200:
            return {"status": "expired", "detail": f"HTTP {r.status_code}"}
        j = r.json()
        if j.get("code") == 200:
            return {"status": "valid", "detail": "登录态有效"}
        msg = j.get("message", "无效")
        return {"status": "expired", "detail": f"{msg}（token 过期/失效）"}

    def _check_cookie(self, host: str, cookie: str) -> dict:
        """验证反爬 cookie：调 fs/list 根目录，正常返回则通过。"""
        headers = {"User-Agent": _UA, "Cookie": cookie}
        try:
            r = requests.post(
                f"{host}/api/fs/list",
                json={"path": "/", "password": "", "page": 1,
                      "per_page": 1, "refresh": False},
                headers=headers, timeout=15,
            )
        except requests.exceptions.ConnectionError:
            return {"status": "offline", "detail": "网络不可达"}
        except requests.exceptions.Timeout:
            return {"status": "offline", "detail": "请求超时"}
        except Exception as e:
            return {"status": "offline", "detail": str(e)}

        if r.status_code == 200:
            j = r.json()
            if j.get("code") == 200:
                return {"status": "valid", "detail": "反爬通过"}
            return {"status": "expired", "detail": j.get("message", "无效")}
        return {"status": "offline", "detail": f"HTTP {r.status_code}"}

    # ── 展开 ─────────────────────────────────────────────

    def expand_urls(self, urls: List[str]) -> List[str]:
        """目录 URL / 文件 URL → 下载 URL 列表（带 sign）。

        - 目录 URL（如 /中文音声/烛灵儿）：列出目录，展开为全部音频文件
        - 文件 URL（follow 后队列里的稳定 URL）：按父目录重新拿 sign 构造下载链接
        """
        if not urls:
            return []
        host = self._host_of(urls[0])

        # 1. 收集所有目标文件 path
        file_paths: set = set()
        for u in urls:
            path = self._extract_path(u)
            if not path:
                continue
            if Path(path).suffix.lower() in _AUDIO_EXTS:
                file_paths.add(path)  # 文件 URL
            else:
                # 目录 URL：列出目录拿文件
                try:
                    files = self._list_files(u, path)
                except Exception as e:
                    logger.warning("列出目录失败: %s - %s", u, e)
                    continue
                for f in files:
                    if (Path(f.get("name", "")).suffix.lower() in _AUDIO_EXTS
                            and f.get("path") and f.get("sign")):
                        file_paths.add(f["path"])

        if not file_paths:
            return []

        # 2. 按父目录分组，各列一次目录拿 sign（sign 只在此次列表响应里返回）
        by_parent: dict = {}
        for fp in file_paths:
            by_parent.setdefault(str(Path(fp).parent), []).append(fp)
        sign_map: dict = {}
        for parent in by_parent:
            try:
                files = self._list_files(host + "/", parent)
            except Exception as e:
                logger.warning("列目录拿 sign 失败: %s - %s", parent, e)
                continue
            for f in files:
                if f.get("sign"):
                    sign_map[f["path"]] = f["sign"]

        # 3. 构造下载 URL
        works = []
        for fp in sorted(file_paths):
            sign = sign_map.get(fp, "")
            if not sign:
                logger.warning("未找到 sign，跳过: %s", fp)
                continue
            works.append(f"{host}/d{quote(fp)}?sign={quote(sign, safe='')}")
        return works

    # ── 内部方法 ─────────────────────────────────────────

    def _download_one(self, url: str) -> PipelineResult:
        """下载单个文件 URL 并入库。"""
        path = self._extract_file_path(url)
        if not path:
            return PipelineResult.failed(url, "无法解析文件路径")
        source = self._stable_source(url)
        if self._is_source_in_manifest(source):
            return PipelineResult.skipped(source, "已存在")

        title = Path(path).stem
        author = Path(path).parent.name or "佚名"
        # asmrmoon 目录是「分类/作者」两层，父目录是分类（如"中文音声"），
        # 不是系列——音频是独立作品，无系列概念，分类放进标签
        category = Path(path).parent.parent.name
        if category in ("/", ""):
            category = ""

        # 临时文件名用 title（清理非法字符），让 build_import_target
        # 以标题命名最终文件，而非 tempfile 随机名（tmpXXXX）
        ext = Path(path).suffix.lower()
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "未命名"
        tmp_dir = Path(tempfile.mkdtemp())
        tmp = tmp_dir / f"{safe_title}{ext}"
        try:
            self._download(url, tmp)
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return PipelineResult.failed(source, str(e))

        result = self.import_download(tmp, source, {
            "title": title,
            "author": author,
            "series": "",
            "tags": ["音声", "ASMR"] + ([category] if category else []),
            "source_status": "ok",
        })
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if result[1] == "ok":
            return PipelineResult.success(source)
        return PipelineResult.failed(source, result[1])

    def _download(self, url: str, dest: Path) -> None:
        """流式下载文件到 dest（带 UA，支持断点）。"""
        with self.session.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)

    def _list_files(self, url: str, path: str) -> List[dict]:
        """分页列出目录下的所有文件（忽略子目录）。"""
        host = self._host_of(url)
        all_files: List[dict] = []
        page = 1
        per_page = 200
        while True:
            resp = self.session.post(
                f"{host}/api/fs/list",
                json={"path": path, "password": "", "page": page,
                      "per_page": per_page, "refresh": False},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                raise RuntimeError(f"AList API 错误: {data.get('message')}")
            d = data.get("data") or {}
            content = d.get("content") or []
            all_files.extend(c for c in content if not c.get("is_dir"))
            total = d.get("total", 0)
            if not content or len(all_files) >= total:
                break
            page += 1
        return all_files

    # ── URL 解析 ─────────────────────────────────────────

    @staticmethod
    def _host_of(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    @staticmethod
    def _extract_path(url: str) -> str:
        """目录 URL → AList path（如 /中文音声/烛灵儿）。"""
        p = urlparse(url)
        path = unquote(p.path or "")
        return path if path.startswith("/") else f"/{path}"

    @staticmethod
    def _extract_file_path(url: str) -> str:
        """文件下载 URL（/d{path}?sign=） → AList path。"""
        p = urlparse(url)
        path = unquote(p.path or "")
        if path.startswith("/d"):
            path = path[2:] or "/"
        return path if path.startswith("/") else f"/{path}"

    def _stable_source(self, url: str) -> str:
        """稳定去重键（不带会过期的 sign）。"""
        path = self._extract_file_path(url)
        return f"{self._host_of(url)}{path}"
