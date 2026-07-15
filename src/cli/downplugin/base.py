import json
import time
import random
import threading
import concurrent.futures
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, Set, List, Callable, Union
from tqdm import tqdm

from src.core.config import get_project_root, get_library_path
from src.core.logging import logger
from .context import PipelineResult, DownloadContext, DownloadControl


class AuthError(Exception):
    pass


class BaseDownloader(ABC):
    name: str = ""
    url_patterns: list[str] = []

    supports_expand: bool = False
    supports_user_name: bool = False
    supports_author_works: bool = False
    supports_search: bool = False
    supports_ranking: bool = False

    METADATA_SCHEMA: dict[str, dict] = {
        "title":         {"column": "标题",    "required": True},
        "author":        {"column": "作者",    "required": False, "fallback": ""},
        "series":        {"column": "系列",    "required": False, "fallback": ""},
        "tags":          {"column": "标签",    "required": False, "fallback": [], "join": ","},
        "source":        {"column": "来源",    "required": True},
        "source_status": {"column": "源状态",   "required": False, "fallback": "ok"},
        "like_count":    {"column": "点赞",    "required": False, "fallback": 0},
        "description":   {"column": "简介",    "required": False, "fallback": ""},
        "create_date":   {"column": "导入时间", "required": False, "fallback": "", "normalize": "iso_date"},
    }

    @classmethod
    def _apply_metadata(cls, plugin_meta: dict, csv_row: dict) -> None:
        for key, spec in cls.METADATA_SCHEMA.items():
            value = plugin_meta.get(key)
            if value is None:
                value = spec.get("fallback", "")
            col = spec["column"]
            if isinstance(value, list) and "join" in spec:
                csv_row[col] = spec["join"].join(str(v) for v in value if v)
            elif isinstance(value, int):
                csv_row[col] = str(value)
            elif value:
                text = str(value)
                if spec.get("normalize") == "iso_date" and "T" in text:
                    text = text.split("+")[0].split("Z")[0].replace("T", " ")
                    if len(text) < 10:
                        continue
                csv_row[col] = text

    @classmethod
    def _plugin_meta_keys(cls) -> list[str]:
        return list(cls.METADATA_SCHEMA.keys())
    def __init__(self):
        self.existing_sources: Set[str] = set()
        self._sources_lock = threading.Lock()
        self.download_file_path: str = "downloads"
        self.stop_event = threading.Event()
        self._ctrl = DownloadControl()

    @abstractmethod
    def process_url(self, urls: Union[str, List[str]], mode: str = "both") -> Dict[str, int]:
        ...

    @abstractmethod
    def get_author_info(self, url: str) -> Optional[tuple[str, int]]:
        ...

    @abstractmethod
    def extract_uid(self, url: str) -> str:
        ...

    def expand_urls(self, urls: List[str]) -> List[str]:
        raise NotImplementedError

    def get_user_name(self, uid: str) -> Optional[str]:
        raise NotImplementedError

    def get_user_works(self, uid: str) -> List[str]:
        raise NotImplementedError

    def search(self, keyword: str, content_type: str = "illust", page: int = 1) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def ranking(self, mode: str = "daily", content_type: str = "illust", page: int = 1) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def stop(self):
        logger.info("🛑 收到停止信号，正在通知所有线程...")
        self.stop_event.set()

    def set_download_control(self, ctrl: DownloadControl):
        self._ctrl = ctrl

    def _check_stop(self):
        if self.stop_event.is_set():
            raise KeyboardInterrupt("Download interrupted by user")

    def _retry(self, fn: Callable[[], "PipelineResult"], work_url: str,
               max_retries: int = 3) -> "PipelineResult":
        for attempt in range(max_retries):
            self._check_stop()
            try:
                result = fn()
            except KeyboardInterrupt:
                return PipelineResult.failed(work_url, "用户取消")
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = random.uniform(1.5, 4.5) * (attempt + 1)
                    logger.debug("重试 %d/%d: 异常 %s 等待 %.1fs",
                                 attempt + 1, max_retries, work_url, delay)
                    self.stop_event.wait(delay)
                    continue
                return PipelineResult.failed(work_url, str(e))

            if result.status in ("success", "skipped"):
                return result
            if attempt < max_retries - 1:
                delay = 3.0 * (2 ** attempt) * random.uniform(0.5, 1.5)
                logger.debug("重试 %d/%d: %s 等待 %.1fs",
                             attempt + 1, max_retries, work_url, delay)
                self.stop_event.wait(delay)
                continue
            return result
        return PipelineResult.failed(work_url, "重试耗尽")

    def _batch_executor(self, max_workers: int) -> concurrent.futures.ThreadPoolExecutor:
        return concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def _batch_shutdown(self, executor: Optional[concurrent.futures.ThreadPoolExecutor]) -> None:
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_batch(
        self, works: list[str], worker_fn: Callable, on_result_fn: Callable,
        max_workers: int, desc: str = "下载进度",
        chunk_size: int = 50,
    ) -> list[tuple[float, int]]:
        executor = self._batch_executor(max_workers)
        try:
            with tqdm(total=len(works), unit="个", desc=desc, ncols=80, colour='MAGENTA') as pbar:
                import concurrent.futures
                timeline: list[tuple[float, int]] = []
                start_time = time.monotonic()
                completed = 0
                all_futures: Dict[concurrent.futures.Future, Any] = {}
                work_iter = iter(works)
                paused_stage = 0  # 0=正常, 1=正在暂停, 2=已暂停
                paused_cancelled: list[str] = []

                def _fill():
                    for _ in range(min(chunk_size, 100)):
                        try:
                            u = next(work_iter)
                            all_futures[executor.submit(worker_fn, u)] = u
                        except StopIteration:
                            break

                _fill()

                while True:
                    self._check_stop()

                    if self._ctrl.cancelled:
                        pbar.set_description("⏹ 已取消")
                        self._batch_shutdown(executor)
                        break

                    if not all_futures:
                        if self._ctrl.paused:
                            if paused_stage < 2:
                                pbar.set_description("⏸ 已暂停，按 o 继续 / c 退出")
                                paused_stage = 2
                            if self._ctrl.sigint_count > 0:
                                pbar.set_description("⏹ 已取消")
                                self._batch_shutdown(executor)
                                break
                            self.stop_event.wait(0.3)
                            continue

                        # Not paused, try to refill
                        paused_stage = 0
                        pbar.set_description(desc)
                        if paused_cancelled:
                            for u in paused_cancelled:
                                all_futures[executor.submit(worker_fn, u)] = u
                            paused_cancelled.clear()
                        _fill()
                        if not all_futures:
                            break
                        continue

                    paused_stage = 0

                    try:
                        for future in concurrent.futures.as_completed(all_futures, timeout=5):
                            completed += 1
                            pbar.update(1)
                            timeline.append((time.monotonic() - start_time, completed))
                            item = all_futures.pop(future)
                            try:
                                result = future.result()
                                if on_result_fn:
                                    on_result_fn(item, result)
                            except KeyboardInterrupt:
                                raise
                            except Exception as e:
                                logger.error("任务异常: %s: %s", type(e).__name__, e)
                            if self._ctrl.paused:
                                if paused_stage < 1:
                                    pbar.set_description("⏸ 正在暂停...")
                                    paused_stage = 1
                                    for f, u in list(all_futures.items()):
                                        if f.cancel():
                                            all_futures.pop(f)
                                            paused_cancelled.append(u)
                            else:
                                if paused_cancelled:
                                    for u in paused_cancelled:
                                        all_futures[executor.submit(worker_fn, u)] = u
                                    paused_cancelled.clear()
                                try:
                                    u = next(work_iter)
                                    all_futures[executor.submit(worker_fn, u)] = u
                                except StopIteration:
                                    pass
                            break
                    except concurrent.futures.TimeoutError:
                        if self._ctrl.paused and paused_stage < 1:
                            pbar.set_description("⏸ 正在暂停...")
                            paused_stage = 1
                            for f, u in list(all_futures.items()):
                                if f.cancel():
                                    all_futures.pop(f)
                                    paused_cancelled.append(u)
            return timeline
        finally:
            self._batch_shutdown(executor)

    def _load_base_config(self):
        try:
            from src.core.config import load_config
            cfg = load_config()
            path = cfg.get("download_file_path", "downloads")
            if path:
                self.download_file_path = path
                logger.debug("📂 [Base] 下载路径已配置为: %s", self.download_file_path)
        except Exception as e:
            logger.error("加载基类配置失败: %s", e)

    def check_network(self, url: str, timeout: int = 5) -> bool:
        import requests
        try:
            proxies = None
            try:
                config_path = get_project_root() / "config.json"
                if config_path.exists():
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                    proxy = config.get("project_settings", {}).get("proxy", "")
                    if proxy:
                        proxies = {"http": proxy, "https": proxy}
            except Exception:
                pass

            elapsed = time.time()
            response = requests.get(url, timeout=timeout, proxies=proxies, stream=True)
            response.close()
            elapsed = (time.time() - elapsed) * 1000

            if response.status_code >= 500:
                logger.error("❌ 服务器返回异常状态码: %d", response.status_code)
                return False

            if elapsed > 1200:
                logger.warning("⚠️ 网络延迟过高 (%.0fms > 1200ms)，下载已取消", elapsed)
                return False

            return True
        except Exception as e:
            logger.error("❌ 无法连接到目标服务器: %s", e)
            return False

    def _load_existing_sources(self):
        self.existing_sources.clear()
        try:
            from src.core.work_manager import WorkManager
            self.existing_sources = WorkManager.source_set()
        except Exception as e:
            logger.error("加载现有记录失败: %s", e)

    def _get_friendly_error_message(self, e: Exception, url: str) -> str:
        status = getattr(getattr(e, "response", None), "status_code", None)
        error_msg = str(e)
        if status == 429:
            return f"HTTP 429 (限流): {url}"
        if status in (401, 403):
            return f"HTTP {status} (认证失败): {url}"
        if status:
            return f"HTTP {status}: {url}"
        if isinstance(e, OSError):
            return f"IO错误: {e} - {url}"
        if isinstance(e, KeyboardInterrupt):
            return "已中断"
        return f"请求失败: {e} - {url}"

    def _handle_request_exception(self, e: Exception, url: str) -> None:
        logger.error(str(e))

    def _is_source_in_manifest(self, work_url: str) -> bool:
        if not work_url:
            return False
        return work_url.strip() in self.existing_sources

    def import_download(self, file_path: Path, work_url: str, metadata_info: Dict[str, Any]) -> tuple[Optional[Path], str]:
        """
        通用导入逻辑：将下载的文件委托给导入中心。

        Args:
            file_path: 下载的临时文件路径
            work_url: 来源 URL
            metadata_info: 包含元数据的字典，应包含:
                - author: 作者名
                - series: 系列名 (可选)
                - title: 标题 (可选，用于重命名)
                - tags: 标签列表或字符串 (可选)
                - like_count: 点赞数 (可选)
                - description: 简介 (可选)
                - create_date: 创建日期 (可选)

        Returns:
            (目标路径, 状态消息)
        """
        from src.core.importer import import_one, ImportResult

        author = metadata_info.get("author", "")
        series = metadata_info.get("series", "")
        title = metadata_info.get("title", "")
        tags = metadata_info.get("tags", [])
        tags_str = ",".join(str(t) for t in tags if t) if isinstance(tags, list) else str(tags)
        description = metadata_info.get("description", "")
        like_count = metadata_info.get("like_count", 0)
        create_date = metadata_info.get("create_date", "")
        source_status = metadata_info.get("source_status", "ok")

        result = import_one(
            file_path=str(file_path),
            author=author or "佚名",
            series=series,
            tags=tags_str,
            source=work_url,
            description=description,
            like_count=like_count,
            create_date=create_date,
            source_status=source_status,
            title=title,
            user_id=metadata_info.get("user_id", ""),
            convert_doc=False,
        )

        if result.success:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
            return Path(result.storage_path), "ok"
        else:
            return None, result.error
