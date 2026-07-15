import json
import re
import time
import random
import signal
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from src.cli.downplugin.base import BaseDownloader, AuthError
from .config import PixivConfig
from .client import PixivClient
from .types import ExtractMessage, WorkInfo
from .extractors import (
    PixivBaseExtractor, PixivWorkExtractor,
    PixivUserExtractor, PixivSeriesExtractor,
    PixivNovelSeriesExtractor, PixivSearchExtractor, PixivRankingExtractor,
    extract_pixiv_id,
)
from src.core.config import get_project_root
from src.core.logging import logger
from src.core.logging import get_logger

log = get_logger("akm.pixiv")


class PixivDownloader(BaseDownloader):
    name = "pixiv"
    url_patterns = [r"pixiv\.net"]
    supports_expand = True
    supports_user_name = True
    supports_author_works = True
    supports_search = True
    supports_ranking = True

    _download_dir_lock = threading.Lock()

    def __init__(self):
        super().__init__()
        self._last_error = ""
        self._download_mode = "both"
        self._load_base_config()

        self.config = PixivConfig.from_file()
        self.client = PixivClient(self.config)
        self._load_existing_sources()
        self._install_signal_handler()
        self._pull_base_mapping: dict = {}

    @property
    def max_workers(self) -> int:
        return self.config.max_workers

    def _install_signal_handler(self):
        def handler(signum, frame):
            self.stop_event.set()
            self.client.stop()
        try:
            signal.signal(signal.SIGINT, handler)
        except (ValueError, OSError):
            pass

    def set_pull_base_mapping(self, mapping: dict):
        self._pull_base_mapping = mapping

    def authenticate(self) -> bool:
        return self.client.authenticate()

    def _create_extractor(self, work_url):
        if "/novel/series/" in work_url:
            return PixivNovelSeriesExtractor(self.client, self.config)
        return PixivWorkExtractor(self.client, self.config)

    def get_info(self, work_url: str) -> Optional[Dict[str, Any]]:
        try:
            extractor = self._create_extractor(work_url)
            for msg in extractor.items(work_url):
                if msg.type == "metadata":
                    return msg.data
                if msg.type == "error":
                    self._set_last_error(msg.error or "获取信息失败")
                    return None
        except AuthError:
            raise
        except Exception as e:
            self._set_last_error(f"解析失败: {e}")
            return None
        return None

    _download_dir_lock = threading.Lock()

    def download(self, work_url: str, save_dir: Optional[Path] = None
                 ) -> tuple[Optional[Path], Optional[Dict[str, Any]]]:
        if save_dir is None:
            save_dir = Path(self.download_file_path)
            if not save_dir.is_absolute():
                save_dir = get_project_root() / save_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        old_novel_dir = PixivWorkExtractor._download_dir
        old_series_dir = PixivNovelSeriesExtractor._download_dir
        with self._download_dir_lock:
            PixivWorkExtractor._download_dir = lambda self_ext: save_dir
            PixivNovelSeriesExtractor._download_dir = lambda self_ext: save_dir
            try:
                extractor = self._create_extractor(work_url)
                metadata = None
                for msg in extractor.items(work_url):
                    if msg.type == "metadata":
                        metadata = msg.data
                    elif msg.type == "file":
                        return msg.path, metadata or msg.data
                    elif msg.type == "error":
                        self._set_last_error(msg.error or "下载失败")
                        return None, None
            finally:
                PixivWorkExtractor._download_dir = old_novel_dir
                PixivNovelSeriesExtractor._download_dir = old_series_dir

        return None, None

    def _do_import(self, file_path: Path, work_url: str, metadata: Dict) -> tuple[bool, str]:
        res, reason = self.import_download(file_path, work_url, metadata)
        if res:
            self.existing_sources.add(work_url.strip())
        return res, reason

    def download_and_import(self, work_url: str) -> tuple[Optional[Path], str]:
        self._clear_last_error()
        if self._is_source_in_manifest(work_url):
            return None, "清单已存在来源"

        dl, info = self.download(work_url)
        if not dl:
            return None, self._last_error or "下载失败"

        metadata = self._build_metadata(info, work_url)
        res, reason = self._do_import(dl, work_url, metadata)
        return dl if res else None, reason

    def process_url(self, url: Union[str, List[str]], mode: str = "both") -> Dict[str, int]:
        stats = {"success": 0, "failed": 0, "skipped": 0}
        self.stop_event.clear()
        self.client.clear_stop()
        self._download_mode = mode

        if not self.check_network("https://www.pixiv.net"):
            logger.error("无法访问 Pixiv，下载已停止")
            return stats

        works = []
        if isinstance(url, list):
            works = [u.strip() for u in url if u.strip()]
        else:
            u = url.strip()
            if not u:
                return stats
            logger.info("解析链接: %s", u)
            supported = ("/users/", "/series/", "/novel/series/", "/artworks/", "/novel/show.php")
            if any(prefix in u for prefix in supported):
                works = self.expand_urls([u])
            else:
                logger.warning("不支持的链接: %s", u)
                return stats

        works = list(dict.fromkeys(works))
        if not works:
            return stats

        logger.info("共 %d 个作品待下载，线程数: %d", len(works), self.max_workers)

        lock = threading.Lock()

        def _on_result(item, result):
            work_url, status, reason, file_path, metadata = result
            if status == "success":
                if file_path and metadata:
                    imported, msg = self._do_import(file_path, work_url, metadata)
                    if imported:
                        with lock:
                            stats["success"] += 1
                    else:
                        with lock:
                            stats["failed"] += 1
                else:
                    with lock:
                        stats["success"] += 1
            elif status == "skipped":
                with lock:
                    stats["skipped"] += 1
            else:
                with lock:
                    stats["failed"] += 1
                logger.warning("下载失败: %s 原因: %s", work_url, reason)

        try:
            timeline = self._run_batch(works, self._download_worker, _on_result, self.max_workers)
            logger.info("完成: 成功 %d | 跳过 %d | 失败 %d", stats['success'], stats['skipped'], stats['failed'])
        except KeyboardInterrupt:
            logger.info("收到停止信号")
            self.stop_event.set()
            self.client.stop()
            stats["_interrupted"] = True
        finally:
            if works:
                self._reindex_works(works)

        return stats

    def _download_worker(self, work_url: str) -> tuple[str, str, str, Any, Any]:
        # 抖动分散启动，避免同时请求
        self.stop_event.wait(random.uniform(0.05, 0.5))
        self._check_stop()

        max_retries = 3
        last_reason = ""
        for attempt in range(max_retries):
            self._check_stop()
            try:
                status, reason, file_path, metadata = self._process_single_work(work_url)
                last_reason = reason
                if status == "success":
                    return work_url, status, reason, file_path, metadata
                elif status == "skipped":
                    return work_url, status, reason, None, None
                else:
                    if attempt < max_retries - 1:
                        # 指数退避 + 抖动
                        delay = base_delay = 3.0 * (2 ** attempt)
                        delay = random.uniform(base_delay * 0.5, base_delay * 1.5)
                        logger.debug("重试 %d/%d: %s 等待 %.1fs", attempt + 1, max_retries, work_url, delay)
                        self.stop_event.wait(delay)
                        continue
                    return work_url, status, reason, None, None
            except KeyboardInterrupt:
                return work_url, "failed", "用户取消", None, None
            except Exception as e:
                last_reason = str(e)
                if attempt < max_retries - 1:
                    delay = random.uniform(1.5, 4.5) * (attempt + 1)
                    logger.debug("重试 %d/%d 异常: %s 等待 %.1fs", attempt + 1, max_retries, work_url, delay)
                    self.stop_event.wait(delay)
                    continue
                return work_url, "failed", str(e), None, None
        logger.warning("下载重试耗尽: %s 原因: %s", work_url, last_reason)
        return work_url, "failed", last_reason, None, None

    def _process_single_work(self, work_url: str
                             ) -> tuple[str, str, Optional[Path], Optional[Dict]]:
        try:
            if self._is_source_in_manifest(work_url):
                return "skipped", "已存在", None, None

            if self._pull_base_mapping and work_url in self._pull_base_mapping:
                return self._pull_base_import(work_url, self._pull_base_mapping[work_url])

            if self._download_mode == "meta":
                return self._import_metadata_only(work_url)

            dl, info = self.download(work_url)
            if not dl:
                if not self._last_error:
                    self._last_error = "下载失败(无详细信息)"
                logger.warning("作品下载失败: %s 原因: %s", work_url, self._last_error)
                return "failed", self._last_error or "下载失败", None, None

            metadata = self._build_metadata(info, work_url)
            return "success", "ok", dl, metadata
        except AuthError:
            raise
        except Exception as e:
            return "failed", str(e), None, None

    @staticmethod
    def _resolve_work_format(work_type: str) -> tuple[str, str]:
        mapping = {
            "novel": ("小说", ".epub"),
            "manga": ("漫画", ".pdf"),
            "ugoira": ("漫画", ".gif"),
            "illust": ("插画", ".pdf"),
        }
        return mapping.get(work_type, ("插画", ".pdf"))

    def _pull_base_import(self, work_url: str, old_entry: dict
                          ) -> tuple[str, str, Optional[Path], Optional[Dict]]:
        old_path = Path(old_entry["file_path"])
        if not old_path.is_absolute():
            logger.warning("旧库文件路径非绝对路径，跳过: %s", old_path)
            return "failed", "旧库文件路径非绝对路径", None, None
        if not old_path.exists():
            logger.warning("旧库文件不存在，回退正常下载: %s", old_path)
            dl, info = self.download(work_url)
            if not dl:
                return "failed", self._last_error or "下载失败", None, None
            metadata = self._build_metadata(info, work_url)
            return "success", "ok", dl, metadata

        info = self.get_info(work_url)
        if not info:
            return "failed", "获取元数据失败", None, None

        import tempfile, shutil
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_path = tmp_dir / old_path.name
        shutil.copy2(old_path, tmp_path)

        metadata = self._build_metadata(info, work_url)
        logger.info("复用旧库文件: %s → %s", old_path.name, work_url)
        return "success", "ok", tmp_path, metadata

    def _import_metadata_only(self, work_url: str
                              ) -> tuple[str, str, Optional[Path], Optional[Dict]]:
        if work_url.strip() in self.existing_sources:
            return "skipped", "已存在", None, None
        try:
            info = self.get_info(work_url)
            if not info:
                return "failed", "获取详情失败", None, None

            from src.core.paths import build_import_target
            from src.domain.cdbook import normalize_series_name
            from src.core.registry import generate_id
            from src.operations.import_op import register_entry

            author = info.get("author", "")
            series = normalize_series_name(info.get("series", "") or "")
            tags = info.get("tags", [])
            title = info.get("title", "")
            file_type, suffix = self._resolve_work_format(info.get("type", "illust"))

            book_id = generate_id(file_type, author, series)
            safe_title = normalize_series_name(title)
            placeholder_name = f"{book_id}_{safe_title}{suffix}"
            target = build_import_target(Path(placeholder_name), author, series, book_id=book_id)

            entry = {
                "ID": book_id, "标题": title, "作者": author or "佚名",
                "系列": series or "", "标签": ",".join(str(t) for t in tags if t) if isinstance(tags, list) else str(tags or ""),
                "来源": work_url, "源状态": "metadata_only", "后缀": suffix,
                "分类": file_type, "导入时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "文件大小(KB)": "0", "MD5": "", "文件路径": str(target.absolute()),
                "收藏": "否", "评分": "", "简介": info.get("description", ""),
                "点赞": str(info.get("like_count", 0)),
            }
            register_entry(entry)
            self.existing_sources.add(work_url.strip())
            return "success", "ok", None, None
        except Exception as e:
            return "failed", str(e), None, None

    def expand_urls(self, urls: List[str]) -> List[str]:
        works = []
        expandable = {
            "/novel/series/": (r"/novel/series/(\d+)",
                                lambda sid: self._get_novel_series_work_urls(sid)),
            "/series/": (r"/series/(\d+)",
                          lambda sid: self._get_illust_series_work_urls(sid)),
            "/users/": (r"/users/(\d+)",
                         lambda uid: self._get_user_work_urls(uid)),
        }
        for u in urls:
            u = u.strip()
            if not u:
                continue
            expanded = False
            for prefix, (pattern, expander) in expandable.items():
                if prefix in u:
                    m = re.search(pattern, u)
                    if m:
                        try:
                            works.extend(expander(m.group(1)))
                        except Exception as e:
                            log.debug("expand_urls %s: %s", u, e)
                        expanded = True
                        break
            if not expanded:
                if "/artworks/" in u or "/novel/show.php" in u:
                    works.append(u)
                else:
                    works.append(u)
        return list(dict.fromkeys(works))

    def get_user_name(self, user_id: str) -> Optional[str]:
        extractor = PixivUserExtractor(self.client, self.config)
        uid = user_id
        m = re.search(r"/users/(\d+)", user_id)
        if m:
            uid = m.group(1)
        return extractor.get_user_name(uid)

    def get_user_works(self, user_id: str) -> List[str]:
        uid = user_id
        m = re.search(r"/users/(\d+)", user_id)
        if m:
            uid = m.group(1)
        return self._get_user_work_urls(uid)

    def _get_user_work_urls(self, uid: str) -> List[str]:
        extractor = PixivUserExtractor(self.client, self.config)
        return extractor._get_user_works(uid)

    def get_series_works(self, series_id: str, is_novel: bool = False) -> List[str]:
        return self._get_illust_series_work_urls(series_id) if not is_novel else self._get_novel_series_work_urls(series_id)

    def _get_illust_series_work_urls(self, sid: str) -> List[str]:
        extractor = PixivSeriesExtractor(self.client, self.config)
        return extractor._get_series_works(sid)

    def _get_novel_series_work_urls(self, sid: str) -> List[str]:
        extractor = PixivNovelSeriesExtractor(self.client, self.config)
        return extractor._get_series_work_urls(sid)

    def search(self, keyword: str, content_type: str = "illust", page: int = 1
               ) -> List[Dict[str, Any]]:
        extractor = PixivSearchExtractor(self.client, self.config)
        results = []
        results = extractor._search(keyword, page, max_pages=1, content_type=content_type)
        return results

    def ranking(self, mode: str = "daily", content_type: str = "illust", page: int = 1
                ) -> List[Dict[str, Any]]:
        extractor = PixivRankingExtractor(self.client, self.config)
        return extractor._ranking(mode, content_type, page)

    def get_author_info(self, url: str) -> Optional[tuple[str, int]]:
        if "/users/" not in url:
            return None
        m = re.search(r"/users/(\d+)", url)
        if not m:
            return None
        uid = m.group(1)
        name = self.get_user_name(uid)
        if not name:
            return None
        return name, -1

    @staticmethod
    def extract_uid(url: str) -> str:
        m = re.search(r"/users/(\d+)", url)
        return m.group(1) if m else ""

    def _build_metadata(self, info: Optional[Dict], work_url: str) -> Dict:
        meta = {"source": work_url}
        if info:
            meta.update({
                "title": info.get("title"),
                "author": info.get("author"),
                "series": info.get("series"),
                "tags": [t for t in (info.get("tags") or []) if t],
                "like_count": info.get("like_count", 0),
                "description": info.get("description", ""),
                "create_date": info.get("create_date", ""),
                "user_id": info.get("user_id", ""),
            })
        return meta

    def _reindex_works(self, urls: List[str]) -> None:
        from src.core.work_manager import WorkManager

        url_set = set(urls)
        all_rows = WorkManager.read()
        if not all_rows:
            return

        affected_keys = set()
        for row in all_rows:
            if row.get("来源", "") in url_set:
                key = f"{row.get('分类', '')}||{row.get('作者', '')}||{row.get('系列', '') or ''}"
                affected_keys.add(key)
        if not affected_keys:
            return

        affected_rows = [r for r in all_rows
                         if f"{r.get('分类', '')}||{r.get('作者', '')}||{r.get('系列', '') or ''}" in affected_keys]
        WorkManager.reindex_groups(affected_rows, sort_key=lambda r: int(extract_pixiv_id(r.get("来源", "")) or 0))

        reindexed = {r["来源"]: r for r in affected_rows}
        for row in all_rows:
            source = row.get("来源", "")
            if source in reindexed:
                row.update(reindexed[source])

        WorkManager.write(all_rows)

    def stop(self):
        super().stop()
        self.client.stop()

    def _set_last_error(self, msg: str):
        self._last_error = msg

    def _clear_last_error(self):
        self._last_error = ""
