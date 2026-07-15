import json
import re
import time
import signal
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from src.cli.downplugin.base import BaseDownloader, AuthError
from src.cli.downplugin.context import DownloadContext, PipelineResult
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

    def download_and_import(self, work_url: str) -> tuple[Optional[Path], str]:
        result = self._run_pipeline(work_url)
        return (result.final_path, result.reason)

    # ── 流水线入口 ──────────────────────────────────────────

    def _run_pipeline(self, work_url: str) -> PipelineResult:
        ctx = DownloadContext(work_url)
        try:
            if self._is_source_in_manifest(work_url):
                return PipelineResult.skipped(work_url)

            if self._pull_base_mapping and work_url in self._pull_base_mapping:
                return self._run_pull_base_pipeline(ctx,
                                                     self._pull_base_mapping[work_url])

            if self._download_mode == "meta":
                return self._run_meta_pipeline(ctx)

            return self._run_normal_pipeline(ctx)
        except AuthError:
            raise
        except Exception as e:
            self._pipeline_cleanup(ctx)
            return PipelineResult.failed(work_url, str(e))

    # ── 标准流水线：①→⑥ ────────────────────────────────────

    def _run_normal_pipeline(self, ctx: DownloadContext) -> PipelineResult:
        # ①② 获取网页内容并处理为暂存文件
        info = self._pipeline_fetch(ctx)
        if not ctx.temp_file:
            return PipelineResult.failed(ctx.work_url, ctx.error or "下载处理失败")
        ctx.metadata = self._build_metadata(info, ctx.work_url)

        # ③ 生成作品信息
        self._pipeline_build_entry(ctx)

        # ④ 写入数据库
        self._pipeline_write_db(ctx)

        # ⑤ 移动到目标位置
        self._pipeline_move_file(ctx)

        # ⑥ 清理暂存
        self._pipeline_cleanup(ctx)

        with self._sources_lock:
            self.existing_sources.add(ctx.work_url.strip())

        return PipelineResult.success(ctx.work_url, final_path=ctx.final_path)

    # ── pull_base 流水线 — 复用旧库文件 ─────────────────────

    def _run_pull_base_pipeline(self, ctx: DownloadContext,
                                 old_entry: dict) -> PipelineResult:
        old_path = Path(old_entry["file_path"])
        if not old_path.is_absolute():
            return PipelineResult.failed(ctx.work_url, "旧库文件路径非绝对路径")
        if not old_path.exists():
            logger.warning("旧库文件不存在，回退正常下载: %s", old_path)
            return self._run_normal_pipeline(ctx)

        info = self.get_info(ctx.work_url)
        if not info:
            return PipelineResult.failed(ctx.work_url, "获取元数据失败")

        ctx.metadata = self._build_metadata(info, ctx.work_url)

        import tempfile, shutil
        tmp_dir = Path(tempfile.mkdtemp())
        ctx.temp_file = tmp_dir / old_path.name
        shutil.copy2(old_path, ctx.temp_file)
        logger.info("复用旧库文件: %s → %s", old_path.name, ctx.work_url)

        self._pipeline_build_entry(ctx)
        self._pipeline_write_db(ctx)
        self._pipeline_move_file(ctx)
        self._pipeline_cleanup(ctx)

        with self._sources_lock:
            self.existing_sources.add(ctx.work_url.strip())

        return PipelineResult.success(ctx.work_url, final_path=ctx.final_path)

    # ── meta 流水线 — 仅元数据 ──────────────────────────────

    def _run_meta_pipeline(self, ctx: DownloadContext) -> PipelineResult:
        info = self.get_info(ctx.work_url)
        if not info:
            return PipelineResult.failed(ctx.work_url, "获取详情失败")

        from src.core.paths import build_import_target
        from src.domain.cdbook import normalize_series_name
        from src.core.registry import generate_id
        from src.core.work_repository import append_one

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
            "来源": ctx.work_url, "源状态": "metadata_only", "后缀": suffix,
            "分类": file_type, "导入时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "文件大小(KB)": "0", "MD5": "", "文件路径": str(target.absolute()),
            "收藏": "否", "评分": "", "简介": info.get("description", ""),
            "点赞": str(info.get("like_count", 0)),
        }
        append_one(entry)

        with self._sources_lock:
            self.existing_sources.add(ctx.work_url.strip())

        return PipelineResult.success(ctx.work_url, final_path=target)

    # ── 流水线阶段方法 ─────────────────────────────────────

    def _pipeline_fetch(self, ctx: DownloadContext) -> Optional[dict]:
        dl, info = self.download(ctx.work_url)
        if dl:
            ctx.temp_file = dl
        else:
            ctx.error = "下载失败"
        return info

    def _pipeline_build_entry(self, ctx: DownloadContext) -> None:
        from src.core.hashing import generate_file_md5, check_duplicate_by_md5
        from src.core.filetype import determine_file_type
        from src.core.registry import generate_id
        from src.core.paths import build_import_target
        from src.domain.cdbook import normalize_series_name

        fp = ctx.temp_file
        author = ctx.metadata.get("author", "")
        series = normalize_series_name(ctx.metadata.get("series", "") or "")
        title = ctx.metadata.get("title", "")
        tags = ctx.metadata.get("tags", [])
        tags_str = ",".join(str(t) for t in tags if t) if isinstance(tags, list) else str(tags)
        description = ctx.metadata.get("description", "")
        like_count = ctx.metadata.get("like_count", 0)
        create_date = ctx.metadata.get("create_date", "")
        source_status = ctx.metadata.get("source_status", "ok")
        user_id = ctx.metadata.get("user_id", "")

        source_md5 = generate_file_md5(fp)
        is_dup, dup_id = check_duplicate_by_md5(source_md5)
        if is_dup:
            raise ValueError(f"MD5重复: {dup_id}")

        file_type = determine_file_type(str(fp))
        if file_type == "unknown":
            raise ValueError(f"无法识别的文件类型: {fp.suffix}")

        book_id = generate_id(file_type, author, series)

        if create_date and "T" in create_date:
            normalized = create_date.split("+")[0].split("Z")[0].replace("T", " ")
            if len(normalized) >= 10:
                create_date = normalized

        target = build_import_target(fp, author, series, book_id=book_id)

        ctx.entry = {
            "ID": book_id,
            "标题": title or fp.stem,
            "作者": author or "佚名",
            "系列": series,
            "标签": tags_str,
            "来源": ctx.work_url,
            "源状态": source_status,
            "后缀": fp.suffix.lower(),
            "分类": file_type,
            "导入时间": create_date or time.strftime("%Y-%m-%d %H:%M:%S"),
            "文件大小(KB)": "0",
            "MD5": source_md5,
            "文件路径": str(target.absolute()),
            "收藏": "否",
            "评分": "",
            "简介": description,
            "点赞": str(like_count),
        }
        ctx.metadata["_book_id"] = book_id
        ctx.metadata["_file_type"] = file_type
        ctx.metadata["_md5"] = source_md5
        ctx.metadata["_user_id"] = user_id
        ctx.metadata["_author"] = author
        ctx.metadata["_series"] = series
        ctx.metadata["_target_path"] = str(target.absolute())

    def _pipeline_write_db(self, ctx: DownloadContext) -> None:
        from src.core.work_repository import append_one

        append_one(ctx.entry)

        author = ctx.metadata.get("_author", "")
        user_id = ctx.metadata.get("_user_id", "")
        if author:
            try:
                from src.core.author_manager import register
                register(name=author, uid=user_id or "", homepage="")
            except Exception:
                pass

    def _pipeline_move_file(self, ctx: DownloadContext) -> None:
        import shutil

        target = Path(ctx.metadata["_target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            raise ValueError(f"目标已存在: {target}")

        shutil.copy2(ctx.temp_file, target)
        file_size_kb = round(target.stat().st_size / 1024, 2)

        ctx.entry["文件大小(KB)"] = str(file_size_kb)
        ctx.final_path = target

        from src.core.work_repository import update_entry
        update_entry(ctx.entry["ID"], {
            "文件大小(KB)": str(file_size_kb),
            "文件路径": str(target.absolute()),
        })

    def _pipeline_cleanup(self, ctx: DownloadContext) -> None:
        if ctx.temp_file:
            try:
                ctx.temp_file.unlink(missing_ok=True)
            except Exception:
                pass
            ctx.temp_file = None

    # ── process_url（调度入口） ─────────────────────────────

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

        def _on_result(work_url: str, result: PipelineResult):
            with lock:
                if result.status == "success":
                    stats["success"] += 1
                    from src.core.download import mark_downloaded
                    mark_downloaded(work_url)
                elif result.status == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
                    logger.warning("下载失败: %s 原因: %s", work_url, result.reason)
                    reason_lower = result.reason.lower()
                    if any(code in reason_lower for code in ("404", "401", "403")):
                        from src.core.download import mark_invalid
                        mark_invalid(work_url)
                    else:
                        from src.core.download import mark_failed
                        mark_failed(work_url)

        def _worker(work_url: str) -> PipelineResult:
            return self._retry(lambda: self._run_pipeline(work_url), work_url)

        try:
            timeline = self._run_batch(works, _worker, _on_result, self.max_workers)
            logger.info("完成: 成功 %d | 跳过 %d | 失败 %d",
                        stats['success'], stats['skipped'], stats['failed'])
        except KeyboardInterrupt:
            logger.info("收到停止信号")
            self.stop_event.set()
            self.client.stop()
            stats["_interrupted"] = True
        finally:
            if works:
                self._reindex_works(works)

        return stats

    # ── 兼容旧 API（rank.py 等使用） ────────────────────────

    def get_last_error(self) -> str:
        return self._last_error

    def _set_last_error(self, msg: str):
        self._last_error = msg

    def _clear_last_error(self):
        self._last_error = ""

    @staticmethod
    def _resolve_work_format(work_type: str) -> tuple[str, str]:
        mapping = {
            "novel": ("小说", ".epub"),
            "manga": ("漫画", ".pdf"),
            "ugoira": ("漫画", ".gif"),
            "illust": ("插画", ".pdf"),
        }
        return mapping.get(work_type, ("插画", ".pdf"))

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
